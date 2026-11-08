"""Validated draft file contract for the separate controller implementation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .geometry import Point, Stroke

MAX_INSTRUCTIONS = 100_000
MAX_JSON_BYTES = 32 * 1024 * 1024
NUMBER = r"-?\d+(?:\.\d+)?"
PEN_COMMAND = re.compile(rf"(?:M\d+(?: [SP]{NUMBER})*|G[01] Z{NUMBER}(?: F{NUMBER})?|G4 P{NUMBER})")


def read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON file exceeds 32 MiB")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


@dataclass(frozen=True)
class Profile:
    name: str
    simulation: bool
    width_mm: float
    height_mm: float
    margin_mm: float
    draw_feed_mm_min: float
    travel_feed_mm_min: float
    pen_up: tuple[str, ...]
    pen_down: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        if set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Profile has missing or unknown fields")
        profile = cls(
            **{**data, "pen_up": tuple(data["pen_up"]), "pen_down": tuple(data["pen_down"])}
        )
        profile.validate()
        return profile

    def validate(self) -> None:
        if type(self.simulation) is not bool or not isinstance(self.name, str) or not self.name:
            raise ValueError("Profile requires a name and a boolean simulation flag")
        for value in (
            self.width_mm,
            self.height_mm,
            self.draw_feed_mm_min,
            self.travel_feed_mm_min,
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Dimensions and feed rates must be finite and positive")
        if any(round(value, 3) <= 0 for value in (self.draw_feed_mm_min, self.travel_feed_mm_min)):
            raise ValueError("Feed rate rounds to zero at the output precision")
        if (
            type(self.margin_mm) not in (int, float)
            or not math.isfinite(self.margin_mm)
            or not 0 <= self.margin_mm < min(self.width_mm, self.height_mm) / 2
        ):
            raise ValueError("Invalid margin")
        if self.pen_up == self.pen_down:
            raise ValueError("Pen-up and pen-down commands must differ")
        for commands in (self.pen_up, self.pen_down):
            if not commands or len(commands) > 16:
                raise ValueError("Each pen transition needs 1 to 16 commands")
            for command in commands:
                if not isinstance(command, str) or len(command) > 100:
                    raise ValueError("Invalid pen command")
                if self.simulation and command in ("; SIMULATED PEN UP", "; SIMULATED PEN DOWN"):
                    continue
                if not PEN_COMMAND.fullmatch(command):
                    raise ValueError("Pen commands allow M codes, Z-only G0/G1, or G4 P dwell")
                for word in command.split()[1:]:
                    value = float(word[1:])
                    if not math.isfinite(value) or (word[0] == "F" and value <= 0):
                        raise ValueError("Pen command has a nonfinite value or nonpositive feed")
                    if command.startswith("G4 ") and value < 0:
                        raise ValueError("Dwell duration must be nonnegative")


@dataclass(frozen=True)
class Instruction:
    text: str
    kind: str
    start: Point | None = None
    end: Point | None = None


@dataclass(frozen=True)
class Job:
    job_id: str
    profile: Profile
    strokes: tuple[Stroke, ...]
    instructions: tuple[Instruction, ...]
    source: dict

    @property
    def gcode(self) -> str:
        warning = (
            "SIMULATION ONLY - DO NOT SEND TO HARDWARE"
            if self.profile.simulation
            else "UNVERIFIED MACHINE PROFILE - REVIEW WITH CONTROLLER OWNER"
        )
        return (
            f"; {warning}\n; job_id={self.job_id}\n"
            + "\n".join(item.text for item in self.instructions)
            + "\n"
        )

    def to_dict(self) -> dict:
        return {
            "schema": "plotter-job-v1",
            "job_id": self.job_id,
            "profile": asdict(self.profile),
            "source": self.source,
            "strokes": [[[p.x, p.y] for p in stroke] for stroke in self.strokes],
            "instructions": [asdict(item) for item in self.instructions],
            "gcode": self.gcode,
        }


def build_job(strokes: tuple[Stroke, ...], profile: Profile, source: dict | None = None) -> Job:
    profile.validate()
    if not strokes or sum(map(len, strokes)) > MAX_INSTRUCTIONS - 100:
        raise ValueError("Toolpath is empty or too large")
    instructions = [Instruction("G21", "setup"), Instruction("G90", "setup")]
    position = None

    def pen(commands: tuple[str, ...], kind: str) -> None:
        instructions.extend(Instruction(text, kind) for text in commands)

    pen(profile.pen_up, "pen_up")
    normalized = []
    for stroke in strokes:
        if len(stroke) < 2:
            raise ValueError("Each stroke needs at least two points")
        points = []
        for point in stroke:
            if (
                not all(type(v) in (int, float) and math.isfinite(v) for v in (point.x, point.y))
                or not 0 <= point.x <= profile.width_mm
                or not 0 <= point.y <= profile.height_mm
            ):
                raise ValueError("Toolpath coordinate is nonfinite or outside the work area")
            rounded = Point(round(point.x, 3), round(point.y, 3))
            if not 0 <= rounded.x <= profile.width_mm or not 0 <= rounded.y <= profile.height_mm:
                raise ValueError("Rounded coordinate is outside the work area")
            if not points or points[-1] != rounded:
                points.append(rounded)
        if len(points) < 2:
            raise ValueError("Stroke collapses at the 0.001 mm output precision")
        normalized.append(tuple(points))
        first = points[0]
        instructions.append(
            Instruction(
                f"G0 X{first.x:.3f} Y{first.y:.3f} F{profile.travel_feed_mm_min:.3f}",
                "travel",
                position,
                first,
            )
        )
        pen(profile.pen_down, "pen_down")
        position = first
        for point in points[1:]:
            instructions.append(
                Instruction(
                    f"G1 X{point.x:.3f} Y{point.y:.3f} F{profile.draw_feed_mm_min:.3f}",
                    "draw",
                    position,
                    point,
                )
            )
            position = point
        pen(profile.pen_up, "pen_up")
    if len(instructions) > MAX_INSTRUCTIONS:
        raise ValueError("Too many instructions; reduce image resolution")
    identity = {
        "profile": asdict(profile),
        "source": source or {},
        "instructions": [asdict(item) for item in instructions],
    }
    job_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return Job(job_id, profile, tuple(normalized), tuple(instructions), source or {})


def validate_gcode(job: Job, text: str) -> None:
    """Validate this generator's exact dialect; do not claim generic G-code support."""
    rebuilt = build_job(job.strokes, job.profile, job.source)
    if rebuilt != job or text != rebuilt.gcode:
        raise ValueError("G-code or metadata differs from the validated toolpath")


def load_job(path: Path) -> Job:
    data = read_json(path)
    if data.get("schema") != "plotter-job-v1":
        raise ValueError("Unsupported job schema")
    try:
        strokes = tuple(tuple(Point(*p) for p in stroke) for stroke in data["strokes"])
        job = build_job(strokes, Profile.from_dict(data["profile"]), data["source"])
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed job metadata") from exc
    # Compare JSON-normalized values to include both instruction mappings and file text.
    if json.loads(json.dumps(job.to_dict())) != data:
        raise ValueError("Job contents or identity do not match the toolpath")
    return job


def save_job(job: Job, path: Path) -> None:
    validate_gcode(job, job.gcode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".gcode").write_text(job.gcode, encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(job.to_dict(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

"""Execution evidence, separate from submission and planner acceptance."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .gcode import Job
from .geometry import Point

STATES = {"running", "paused", "completed", "error", "disconnected"}
KINDS = STATES | {"progress", "heartbeat", "submitted", "accepted"}


@dataclass(frozen=True)
class ExecutionEvent:
    job_id: str
    sequence: int
    kind: str
    simulation: bool
    confirmed: int | None = None
    position: Point | None = None
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> ExecutionEvent:
        if not isinstance(data, dict):
            raise ValueError("Event must be an object")
        allowed = {
            "schema",
            "job_id",
            "sequence",
            "kind",
            "simulation",
            "confirmed",
            "position",
            "message",
        }
        if data.get("schema") != "plotter-event-v1" or set(data) - allowed:
            raise ValueError("Unknown event schema or fields")
        try:
            position = data.get("position")
            return cls(
                data["job_id"],
                data["sequence"],
                data["kind"],
                data["simulation"],
                data.get("confirmed"),
                Point(*position) if position is not None else None,
                data.get("message", ""),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("Malformed execution event") from exc

    def to_dict(self) -> dict:
        result = {
            "schema": "plotter-event-v1",
            "job_id": self.job_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "simulation": self.simulation,
        }
        if self.confirmed is not None:
            result["confirmed"] = self.confirmed
        if self.position is not None:
            result["position"] = [self.position.x, self.position.y]
        if self.message:
            result["message"] = self.message
        return result


class Monitor:
    def __init__(self, job: Job, simulation: bool, stale_seconds: float = 5.0):
        if not math.isfinite(stale_seconds) or stale_seconds <= 0:
            raise ValueError("Feedback timeout must be positive")
        if job.profile.simulation and not simulation:
            raise ValueError("A simulation-only job cannot be monitored as a real machine job")
        self.job = job
        self.simulation = simulation
        self.stale_seconds = stale_seconds
        self.state = "ready"
        self.confirmed: int | None = None
        self.sequence = -1
        self.position: Point | None = None
        self.message = "Waiting for execution feedback"
        self.last_feedback = time.monotonic()

    @property
    def fraction(self) -> float | None:
        return None if self.confirmed is None else self.confirmed / len(self.job.instructions)

    @property
    def completed_draws(self) -> int:
        return sum(item.kind == "draw" for item in self.job.instructions[: self.confirmed or 0])

    def apply(self, event: ExecutionEvent, now: float | None = None) -> bool:
        """Apply a cumulative executed prefix, validated before any state change."""
        if event.job_id != self.job.job_id:
            raise ValueError("Event belongs to another job")
        if type(event.sequence) is not int or event.sequence < 0:
            raise ValueError("Event sequence must be a nonnegative integer")
        if type(event.simulation) is not bool or event.simulation != self.simulation:
            raise ValueError("Event simulation label does not match this monitor")
        if not isinstance(event.kind, str) or event.kind not in KINDS:
            raise ValueError("Unknown execution event kind")
        if not isinstance(event.message, str) or len(event.message) > 1000:
            raise ValueError("Invalid event message")
        if event.confirmed is not None:
            if (
                type(event.confirmed) is not int
                or not 0 <= event.confirmed <= len(self.job.instructions)
                or event.kind in {"submitted", "accepted"}
            ):
                raise ValueError("Invalid executed instruction count")
        if event.position is not None:
            if (
                event.kind in {"submitted", "accepted"}
                or not all(
                    type(v) in (int, float) and math.isfinite(v)
                    for v in (event.position.x, event.position.y)
                )
                or not 0 <= event.position.x <= self.job.profile.width_mm
                or not 0 <= event.position.y <= self.job.profile.height_mm
            ):
                raise ValueError("Invalid reported machine position")
        if event.sequence <= self.sequence:
            return False
        if event.confirmed is not None and event.confirmed < (self.confirmed or 0):
            raise ValueError("Executed prefix cannot move backward")
        if self.state in {"completed", "error"}:
            raise ValueError("Terminal job requires a new monitor session")
        if event.kind == "progress" and event.confirmed is None:
            raise ValueError("Progress event requires a confirmed instruction count")
        if event.kind == "completed" and event.confirmed != len(self.job.instructions):
            raise ValueError("Completion must explicitly confirm the entire instruction prefix")
        self.sequence = event.sequence
        if event.kind in {"submitted", "accepted"}:
            # These are not execution feedback and do not refresh the watchdog.
            return True
        if event.confirmed is not None:
            self.confirmed = event.confirmed
        if event.position is not None:
            self.position = event.position
        if event.kind in STATES:
            self.state = event.kind
        elif event.kind == "progress" and self.state in {"ready", "disconnected"}:
            self.state = "running"
        self.last_feedback = time.monotonic() if now is None else now
        self.message = event.message
        return True

    def check_stale(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.state not in {"completed", "error", "disconnected"} and (
            now - self.last_feedback > self.stale_seconds
        ):
            self.disconnect("No execution feedback; completion is unknown")

    def disconnect(self, message: str) -> None:
        if self.state not in {"completed", "error"}:
            self.state = "disconnected"
            self.message = message

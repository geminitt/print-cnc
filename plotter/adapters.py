"""Read-only event sources. No adapter sends machine commands."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Protocol

from .gcode import Job
from .progress import ExecutionEvent


class EventSource(Protocol):
    simulation: bool

    def events(self, job: Job, stop: Event) -> Iterator[ExecutionEvent]: ...


class MockSource:
    simulation = True

    def __init__(self, scenario: str = "completed", delay: float = 0.05):
        if scenario not in {"completed", "paused", "error", "disconnected", "unconfirmed"}:
            raise ValueError("Unknown mock scenario")
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Mock delay must be finite and nonnegative")
        self.scenario, self.delay = scenario, delay

    def events(self, job: Job, stop: Event) -> Iterator[ExecutionEvent]:
        sequence = 0

        def event(kind: str, confirmed: int | None = None) -> ExecutionEvent:
            nonlocal sequence
            sequence += 1
            return ExecutionEvent(
                job.job_id,
                sequence,
                kind,
                True,
                confirmed,
                message="MOCK execution feedback; no hardware connected",
            )

        yield event("running", 0)
        total = len(job.instructions)
        step = max(1, math.ceil(total / 80))
        middle_seen = False
        for count in list(range(step, total, step)) + [total]:
            if stop.wait(self.delay):
                return
            yield event("progress", count)
            if count >= total / 2 and not middle_seen:
                middle_seen = True
                if self.scenario in {"error", "disconnected", "paused"}:
                    yield event(self.scenario, count)
                    return
                yield event("paused", count)
                if stop.wait(self.delay * 3):
                    return
                yield event("running", count)
        if self.scenario != "unconfirmed" and not stop.wait(self.delay):
            yield event("completed", total)


class JsonlSource:
    """Tail an append-only regular NDJSON file written by the controller adapter.

    A partial final record is held until its newline arrives. File truncation,
    replacement, malformed events, and overlong lines fail visibly. The monitor
    owns the no-feedback watchdog; the reader never invents controller completion.
    """

    def __init__(self, path: Path, simulation: bool = False):
        self.path, self.simulation = path, simulation

    def events(self, job: Job, stop: Event) -> Iterator[ExecutionEvent]:
        import stat

        if not stat.S_ISREG(self.path.stat().st_mode):
            raise ValueError("Event source must be a regular file")
        with self.path.open("rb") as stream:
            identity = self.path.stat()
            while not stop.is_set():
                current = self.path.stat()
                if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
                    raise ValueError("Event file was replaced; reload the monitor")
                offset = stream.tell()
                if current.st_size < offset:
                    raise ValueError("Event file was truncated; reload the monitor")
                line = stream.readline(8193)
                if len(line) > 8192:
                    raise ValueError("Execution event exceeds 8192 bytes")
                if not line.endswith(b"\n"):
                    stream.seek(offset)
                    stop.wait(0.05)
                    continue
                if line.strip():
                    yield ExecutionEvent.from_dict(json.loads(line))

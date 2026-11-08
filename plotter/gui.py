"""Tkinter execution monitor. All Tk access stays on the main thread."""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from collections.abc import Iterator
from pathlib import Path

from .adapters import EventSource
from .gcode import load_job
from .progress import Monitor

LOG = logging.getLogger(__name__)


class MonitorWindow:
    def __init__(self, root, job_path: Path, source: EventSource, stale_seconds: float = 5):
        import tkinter as tk
        from tkinter import ttk

        self.root, self.source = root, source
        self.model: Monitor | None = None
        self.stale_seconds = stale_seconds
        self.stop = threading.Event()
        self.messages: queue.Queue = queue.Queue(maxsize=256)
        self.items: list[tuple[int, int]] = []
        self.pending_draw: Iterator | None = None
        self.pending_colors: deque[tuple[int, int]] = deque()
        self.displayed_count = None
        self.redraw_needed = True
        root.title("XY Plotter — Execution Monitor")
        root.geometry("960x700")
        root.minsize(600, 440)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text="XY Plotter / Execution Monitor", font=("TkDefaultFont", 18, "bold")
        ).pack(anchor="w")
        self.mode = ttk.Label(
            frame,
            text=(
                "SIMULATION — MOCK / REPLAY — no hardware verification"
                if source.simulation
                else "CONTROLLER EVENT MONITOR"
            ),
            foreground="#a34216",
        )
        self.mode.pack(anchor="w", pady=(6, 12))
        self.status = ttk.Label(frame, text="Loading validated job…")
        self.status.pack(anchor="w")
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.pack(fill="x", pady=8)
        self.detail = ttk.Label(
            frame, text="Execution progress is unavailable until feedback arrives"
        )
        self.detail.pack(anchor="w")
        self.canvas = tk.Canvas(frame, background="#f4f6f8", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=12)
        ttk.Label(
            frame,
            text="Gray: remaining • Green: confirmed drawn • Dashed: pen-up travel",
            foreground="#465362",
        ).pack(anchor="w")
        self.error = ttk.Label(frame, text="", foreground="#ad321c", wraplength=850)
        self.error.pack(anchor="w", pady=(8, 0))
        self.canvas.bind("<Configure>", self._resize)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker = threading.Thread(target=self._read, args=(job_path,), daemon=True)
        self.worker.start()
        self.after_id = root.after(40, self._poll)

    def _enqueue(self, kind: str, payload) -> bool:
        while not self.stop.is_set():
            try:
                self.messages.put((kind, payload), timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def _read(self, path: Path) -> None:
        try:
            job = load_job(path)
            if not self._enqueue("job", job):
                return
            for event in self.source.events(job, self.stop):
                if not self._enqueue("event", event):
                    return
        except Exception as exc:
            LOG.exception("Job or event reader failed")
            self._enqueue("failure", str(exc))

    def _resize(self, _event=None) -> None:
        self.redraw_needed = True

    def _draw(self) -> Iterator[None]:
        if self.model is None:
            return
        job = self.model.job
        self.canvas.delete("all")
        self.items.clear()
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = min(
            max(1, width - 40) / job.profile.width_mm, max(1, height - 40) / job.profile.height_mm
        )
        left = (width - job.profile.width_mm * scale) / 2
        top = (height - job.profile.height_mm * scale) / 2

        def screen(point):
            return left + point.x * scale, top + (job.profile.height_mm - point.y) * scale

        self.canvas.create_rectangle(
            left,
            top,
            left + job.profile.width_mm * scale,
            top + job.profile.height_mm * scale,
            outline="#bbc3cd",
        )
        for index, item in enumerate(job.instructions):
            if item.start is None or item.end is None:
                yield
                continue
            if item.kind == "draw":
                canvas_id = self.canvas.create_line(
                    *screen(item.start),
                    *screen(item.end),
                    fill=("#187a51" if index < (self.model.confirmed or 0) else "#a0a9b5"),
                    width=2,
                )
                self.items.append((index, canvas_id))
            elif item.kind == "travel":
                self.canvas.create_line(
                    *screen(item.start), *screen(item.end), fill="#c7cdd5", dash=(3, 5)
                )
            yield

    def _render(self) -> None:
        if self.model is None:
            return
        model = self.model
        if self.redraw_needed:
            self.pending_draw = self._draw()
            self.pending_colors.clear()
            self.redraw_needed = False
        if self.pending_draw is not None:
            for _ in range(300):
                try:
                    next(self.pending_draw)
                except StopIteration:
                    self.pending_draw = None
                    break
        count = model.confirmed
        if count != self.displayed_count:
            low, high = sorted((self.displayed_count or 0, count or 0))
            self.pending_colors.extend(item for item in self.items if low <= item[0] < high)
            self.displayed_count = count
        for _ in range(min(300, len(self.pending_colors))):
            index, canvas_id = self.pending_colors.popleft()
            self.canvas.itemconfigure(
                canvas_id, fill=("#187a51" if index < (count or 0) else "#a0a9b5")
            )
        state = model.state.upper()
        if model.fraction == 1 and model.state not in {"completed", "error", "disconnected"}:
            state += " — awaiting explicit job completion"
        self.status.configure(text=f"{state} / job {model.job.job_id[:12]}")
        self.progress["value"] = (model.fraction or 0) * 100
        text = (
            "Executed instructions: unknown"
            if count is None
            else f"Executed instructions: {count}/{len(model.job.instructions)} "
            f"({model.fraction:.1%}) • Drawn segments: {model.completed_draws}"
        )
        if model.position is not None:
            text += f" • Reported position: ({model.position.x:.3f}, {model.position.y:.3f}) mm"
        self.detail.configure(text=text + " • Not an estimate of remaining time")
        self.error.configure(text=model.message)

    def _poll(self) -> None:
        # Bound work per tick so a busy event producer cannot starve the Tk loop.
        for _ in range(100):
            try:
                kind, payload = self.messages.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "job":
                    self.model = Monitor(payload, self.source.simulation, self.stale_seconds)
                    self.redraw_needed = True
                elif kind == "event" and self.model is not None:
                    self.model.apply(payload)
                elif kind == "failure":
                    raise ValueError(payload)
            except (ValueError, TypeError, AttributeError) as exc:
                LOG.error("Monitor rejected input: %s", exc)
                if self.model is not None:
                    self.model.disconnect(f"Invalid/unavailable feedback: {exc}")
                    self.model.message = f"Invalid/unavailable feedback: {exc}"
                else:
                    self.error.configure(text=f"Cannot load monitor: {exc}")
                self.stop.set()
                break
        if self.model is not None:
            self.model.check_stale()
        self._render()
        if not self.stop.is_set():
            self.after_id = self.root.after(40, self._poll)

    def close(self) -> None:
        self.stop.set()
        self.root.after_cancel(self.after_id)
        self.root.destroy()


def run_monitor(job_path: Path, source: EventSource, stale_seconds: float = 5) -> None:
    try:
        import tkinter as tk
    except ImportError as exc:
        raise ValueError(
            "Tkinter is missing. On Linux install your Python distribution's Tk package"
        ) from exc
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise ValueError(f"Cannot open the GUI display: {exc}") from exc
    MonitorWindow(root, job_path, source, stale_seconds)
    root.mainloop()

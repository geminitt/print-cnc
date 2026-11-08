"""Real Tk integration, explicitly skipped when the host has no Tk/display."""

import queue
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path

from plotter.__main__ import simulation_profile
from plotter.adapters import MockSource
from plotter.gcode import build_job, save_job
from plotter.geometry import Point
from plotter.progress import ExecutionEvent, Monitor


class GuiDispatchTests(unittest.TestCase):
    def test_large_preview_builds_in_bounded_batches(self):
        from plotter.gui import MonitorWindow

        class Widget:
            def configure(self, **kwargs):
                pass

        class Canvas:
            def __init__(self):
                self.lines = {}

            def delete(self, _):
                self.lines.clear()

            def winfo_width(self):
                return 800

            def winfo_height(self):
                return 500

            def create_rectangle(self, *args, **kwargs):
                pass

            def create_line(self, *args, **kwargs):
                identity = len(self.lines) + 1
                self.lines[identity] = kwargs["fill"]
                return identity

            def itemconfigure(self, identity, **kwargs):
                self.lines[identity] = kwargs["fill"]

        stroke = tuple(Point(i % 100, i % 80) for i in range(650))
        job = build_job((stroke,), simulation_profile())
        window = MonitorWindow.__new__(MonitorWindow)
        window.model = Monitor(job, True)
        window.canvas = Canvas()
        window.items = []
        window.pending_draw = None
        window.pending_colors = deque()
        window.redraw_needed = True
        window.displayed_count = None
        window.status = window.detail = window.error = Widget()
        window.progress = {}
        window._render()
        self.assertLessEqual(len(window.canvas.lines), 300)
        self.assertIsNotNone(window.pending_draw)
        while window.pending_draw is not None:
            before = len(window.canvas.lines)
            window._render()
            self.assertLessEqual(len(window.canvas.lines) - before, 300)
        window.model.apply(ExecutionEvent(job.job_id, 1, "progress", True, len(job.instructions)))
        window._render()
        self.assertLessEqual(sum(color == "#187a51" for color in window.canvas.lines.values()), 300)
        while window.pending_colors:
            window._render()
        self.assertEqual(len(window.items), 649)
        self.assertTrue(
            all(window.canvas.lines[identity] == "#187a51" for _, identity in window.items)
        )

    def test_invalid_event_stops_before_queued_completion(self):
        from plotter.gui import MonitorWindow

        job = build_job(((Point(1, 1), Point(2, 2)),), simulation_profile())
        window = MonitorWindow.__new__(MonitorWindow)
        window.model = Monitor(job, True)
        window.messages = queue.Queue()
        window.stop = threading.Event()
        window._render = lambda: None
        window.messages.put(("event", ExecutionEvent(job.job_id, 1, "progress", True, 9999)))
        window.messages.put(
            ("event", ExecutionEvent(job.job_id, 2, "completed", True, len(job.instructions)))
        )
        with self.assertLogs("plotter.gui", level="ERROR"):
            window._poll()
        self.assertTrue(window.stop.is_set())
        self.assertEqual(window.model.state, "disconnected")
        self.assertIsNone(window.model.confirmed)


class GuiTests(unittest.TestCase):
    def test_mock_states_and_confirmed_geometry_in_real_tk(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tkinter unavailable: {exc}")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"GUI display unavailable: {exc}")
        from plotter.gui import MonitorWindow

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            job = build_job(((Point(1, 1), Point(2, 2)),), simulation_profile())
            save_job(job, path)
            window = MonitorWindow(root, path, MockSource(delay=0.01))
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    root.update()
                    if window.model and window.model.state == "completed":
                        break
                    time.sleep(0.01)
                self.assertIsNotNone(window.model)
                self.assertEqual(window.model.state, "completed")
                self.assertIn("SIMULATION", window.mode.cget("text"))
                self.assertTrue(
                    all(
                        window.canvas.itemcget(item, "fill") == "#187a51"
                        for _, item in window.items
                    )
                )
            finally:
                window.close()

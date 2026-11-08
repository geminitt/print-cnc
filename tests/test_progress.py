import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from plotter.__main__ import simulation_profile
from plotter.adapters import JsonlSource, MockSource
from plotter.gcode import build_job
from plotter.geometry import Point
from plotter.progress import ExecutionEvent, Monitor


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.job = build_job(((Point(1, 1), Point(2, 2)),), simulation_profile())
        self.model = Monitor(self.job, True)
        self.sequence = 0

    def event(self, kind, confirmed=None, **kwargs):
        self.sequence += 1
        return ExecutionEvent(self.job.job_id, self.sequence, kind, True, confirmed, **kwargs)

    def test_submission_and_acceptance_do_not_claim_execution(self):
        before = self.model.last_feedback
        for kind in ("submitted", "accepted"):
            self.model.apply(self.event(kind))
        self.assertIsNone(self.model.fraction)
        self.assertEqual(self.model.completed_draws, 0)
        self.assertEqual(self.model.last_feedback, before)
        self.assertEqual(self.model.state, "ready")

    def test_execution_requires_explicit_completion_even_after_all_counts(self):
        total = len(self.job.instructions)
        self.model.apply(self.event("running"))
        self.model.apply(self.event("progress", total))
        self.assertEqual(self.model.fraction, 1)
        self.assertEqual(self.model.state, "running")
        self.model.apply(self.event("completed", total))
        self.assertEqual(self.model.state, "completed")

    def test_exact_draw_segment_prefix(self):
        self.model.apply(self.event("progress", 5))
        self.assertEqual(self.model.completed_draws, 0)
        self.model.apply(self.event("progress", 6))
        self.assertEqual(self.model.completed_draws, 1)
        self.assertNotEqual(self.model.state, "completed")

    def test_invalid_feedback_does_not_mutate_state(self):
        for event in (
            self.event("progress", -1),
            self.event("progress", True),
            self.event("progress", 100),
            self.event("completed"),
            self.event("completed", 1),
            self.event("progress"),
            self.event("accepted", 1),
            self.event("invented"),
        ):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.model.apply(event)
            self.assertEqual(self.model.sequence, -1)
            self.assertIsNone(self.model.confirmed)

    def test_wrong_job_mode_and_sequence(self):
        for event in (
            ExecutionEvent("wrong", 0, "running", True),
            ExecutionEvent(self.job.job_id, 0, "running", False),
            ExecutionEvent(self.job.job_id, True, "running", True),
        ):
            with self.assertRaises(ValueError):
                self.model.apply(event)

    def test_duplicates_ignored_and_fresh_count_cannot_regress(self):
        event = self.event("progress", 4)
        self.assertTrue(self.model.apply(event))
        self.assertFalse(self.model.apply(event))
        with self.assertRaises(ValueError):
            self.model.apply(self.event("progress", 3))
        self.assertEqual(self.model.confirmed, 4)

    def test_pause_error_disconnect_and_stale_feedback(self):
        self.model.apply(self.event("running", 0), now=10)
        self.model.apply(self.event("paused", 2), now=11)
        self.assertEqual(self.model.state, "paused")
        self.model.check_stale(now=17)
        self.assertEqual(self.model.state, "disconnected")
        self.assertEqual(self.model.confirmed, 2)
        self.model.apply(self.event("running", 2), now=18)
        self.assertEqual(self.model.state, "running")
        self.model.apply(self.event("error", 2, message="Controller error"))
        self.model.check_stale(now=100000)
        self.assertEqual(self.model.state, "error")
        with self.assertRaises(ValueError):
            self.model.apply(self.event("completed", len(self.job.instructions)))

    def test_reported_position_is_optional_and_validated(self):
        self.model.apply(self.event("running", 0))
        self.assertIsNone(self.model.position)
        self.model.apply(self.event("heartbeat", position=Point(5, 6)))
        self.assertEqual(self.model.position, Point(5, 6))
        with self.assertRaises(ValueError):
            self.model.apply(self.event("heartbeat", position=Point(float("nan"), 6)))

    def test_event_roundtrip_and_schema(self):
        event = self.event("progress", 2, position=Point(1, 2))
        self.assertEqual(ExecutionEvent.from_dict(event.to_dict()), event)
        for data in (
            [],
            {},
            {"schema": "wrong"},
            {**event.to_dict(), "sent": 99},
            {**event.to_dict(), "position": [1]},
        ):
            with self.assertRaises(ValueError):
                ExecutionEvent.from_dict(data)

    def test_mock_scenarios(self):
        for scenario in ("completed", "paused", "error", "disconnected", "unconfirmed"):
            model = Monitor(self.job, True)
            states = []
            for event in MockSource(scenario, delay=0).events(self.job, threading.Event()):
                model.apply(event)
                states.append(model.state)
            self.assertEqual(model.state, "running" if scenario == "unconfirmed" else scenario)
            if scenario == "completed":
                self.assertIn("paused", states)

    def test_simulation_cannot_be_labeled_live(self):
        with self.assertRaises(ValueError):
            Monitor(self.job, False)


class AdapterTests(unittest.TestCase):
    setUp = ProgressTests.setUp
    event = ProgressTests.event

    def test_partial_line_waits_then_reads_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.ndjson"
            encoded = json.dumps(self.event("progress", 3).to_dict())
            path.write_text(encoded[:20])
            stop = threading.Event()
            received = []

            def reader():
                for event in JsonlSource(path, True).events(self.job, stop):
                    received.append(event)
                    stop.set()

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            time.sleep(0.08)
            self.assertEqual(received, [])
            with path.open("a") as stream:
                stream.write(encoded[20:] + "\n")
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(received[0].confirmed, 3)

    def test_invalid_json_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.ndjson"
            path.write_text("not json\n")
            with self.assertRaises(ValueError):
                next(JsonlSource(path).events(self.job, threading.Event()))

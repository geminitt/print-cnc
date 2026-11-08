import math
import re
import tempfile
import unittest
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

from plotter.__main__ import simulation_profile
from plotter.gcode import Profile, build_job, load_job, save_job, validate_gcode
from plotter.geometry import Point, boundaries, fit_image


class GeometryTests(unittest.TestCase):
    def test_rectangle_collinear_reduction(self):
        (stroke,) = boundaries([[True] * 4 for _ in range(3)])
        self.assertEqual(len(stroke), 5)
        self.assertEqual(stroke[0], stroke[-1])
        self.assertEqual({(p.x, p.y) for p in stroke}, {(0, 0), (4, 0), (4, 3), (0, 3)})

    def test_holes_preserved(self):
        result = boundaries([[True, True, True], [True, False, True], [True, True, True]])
        self.assertEqual(len(result), 2)
        areas = [sum(a.x * b.y - b.x * a.y for a, b in pairwise(s)) / 2 for s in result]
        self.assertEqual(sorted(areas), [-1, 9])

    def test_diagonal_pixels_remain_separate(self):
        self.assertEqual(len(boundaries([[True, False], [False, True]])), 2)

    def test_exhaustive_three_by_three_masks_preserve_area_and_edges(self):
        for bits in range(1, 512):
            mask = [[bool(bits & (1 << (y * 3 + x))) for x in range(3)] for y in range(3)]
            strokes = boundaries(mask)
            area = sum(a.x * b.y - b.x * a.y for s in strokes for a, b in pairwise(s)) / 2
            self.assertEqual(area, bits.bit_count(), bits)
            for stroke in strokes:
                self.assertEqual(stroke[0], stroke[-1])
                self.assertTrue(all(a.x == b.x or a.y == b.y for a, b in pairwise(stroke)))

    def test_empty_and_ragged_masks(self):
        for mask in ([], [[]], [[False]], [[True], [True, False]]):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                boundaries(mask)

    def test_aspect_ratio_centering_and_y_flip(self):
        strokes = ((Point(0, 0), Point(200, 100)),)
        result = fit_image(strokes, 200, 100, 120, 100, 10)
        self.assertEqual(result, ((Point(10, 75), Point(110, 25)),))


class GcodeTests(unittest.TestCase):
    def setUp(self):
        self.profile = simulation_profile()
        self.strokes = (
            (Point(10, 10), Point(20, 10)),
            (Point(80, 30), Point(80, 40), Point(90, 40), Point(80, 30)),
        )
        self.job = build_job(self.strokes, self.profile)

    def test_no_drawing_between_disjoint_strokes_and_final_lift(self):
        kinds = [i.kind for i in self.job.instructions]
        self.assertEqual(
            kinds,
            [
                "setup",
                "setup",
                "pen_up",
                "travel",
                "pen_down",
                "draw",
                "pen_up",
                "travel",
                "pen_down",
                "draw",
                "draw",
                "draw",
                "pen_up",
            ],
        )
        self.assertIsNone(self.job.instructions[3].start)
        self.assertEqual(self.job.instructions[7].start, Point(20, 10))
        self.assertIn("SIMULATION ONLY", self.job.gcode)

    def test_preview_equals_emitted_coordinates(self):
        for instruction in self.job.instructions:
            if instruction.end:
                match = re.search(r"X([\d.]+) Y([\d.]+)", instruction.text)
                self.assertIsNotNone(match)
                self.assertEqual(instruction.end, Point(*map(float, match.groups())))

    def test_sampled_curve(self):
        curve = tuple(
            Point(50 + 10 * math.cos(t / 10), 50 + 10 * math.sin(t / 10)) for t in range(32)
        )
        job = build_job((curve,), self.profile)
        self.assertEqual(sum(i.kind == "draw" for i in job.instructions), 31)
        validate_gcode(job, job.gcode)

    def test_coordinates_rejected(self):
        for point in (
            Point(-1, 1),
            Point(151, 1),
            Point(1, 101),
            Point(float("nan"), 1),
            Point(float("inf"), 1),
            Point(True, 1),
        ):
            with self.subTest(point=point), self.assertRaises(ValueError):
                build_job(((Point(1, 1), point),), self.profile)

    def test_empty_collapsed_and_short_strokes(self):
        for strokes in ((), ((Point(1, 1),),), ((Point(1, 1), Point(1.00001, 1)),)):
            with self.assertRaises(ValueError):
                build_job(strokes, self.profile)

    def test_invalid_profiles(self):
        variants = (
            {"width_mm": 0},
            {"draw_feed_mm_min": float("nan")},
            {"margin_mm": -1},
            {"margin_mm": 50},
            {"simulation": "false"},
            {"pen_up": ("G91",)},
            {"pen_down": ("G1 X10",)},
            {"pen_down": ("M3\nG1 X10",)},
            {"pen_up": self.profile.pen_down},
            {"simulation": False},
        )
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.profile, **changes).validate()

    def test_feed_must_remain_positive_after_serialization(self):
        with self.assertRaises(ValueError):
            build_job(self.strokes, replace(self.profile, draw_feed_mm_min=0.0001))

    def test_negative_dwell_and_pen_feed_rejected(self):
        for command in ("G4 P-1", "G1 Z0 F-100", "G0 Z5 F0"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                replace(self.profile, pen_up=(command,)).validate()

    def test_configurable_pen_commands(self):
        profile = replace(
            self.profile,
            simulation=False,
            pen_up=("G0 Z5", "G4 P0.2"),
            pen_down=("G1 Z0 F100", "G4 P0.2"),
        )
        job = build_job(self.strokes, profile)
        self.assertEqual(job.instructions[-1].text, "G4 P0.2")
        validate_gcode(job, job.gcode)

    def test_tampered_gcode_and_metadata_rejected(self):
        for text in (self.job.gcode + "G91\n", self.job.gcode.replace("X20.000", "X900.000")):
            with self.assertRaises(ValueError):
                validate_gcode(self.job, text)
        with self.assertRaises(ValueError):
            validate_gcode(replace(self.job, job_id="forged"), self.job.gcode)

    def test_roundtrip_and_tampering(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            save_job(self.job, path)
            self.assertEqual(load_job(path), self.job)
            self.assertEqual(path.with_suffix(".gcode").read_text(), self.job.gcode)
            data = json.loads(path.read_text())
            data["instructions"][5]["kind"] = "travel"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_job(path)

    def test_profile_unknown_fields(self):
        from dataclasses import asdict

        with self.assertRaises(ValueError):
            Profile.from_dict({**asdict(self.profile), "units": "inch"})

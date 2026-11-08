import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from plotter.__main__ import convert, simulation_profile
from plotter.gcode import load_job
from plotter.images import read_jpg


class JpgTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "input.jpg"

    def save(self, image):
        image.save(self.path, quality=100, subsampling=0)

    def read(self, **kwargs):
        return read_jpg(self.path, 150, 100, 5, **kwargs)

    def test_real_jpg_line_rectangle_curve_and_disjoint_strokes(self):
        image = Image.new("RGB", (120, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.line((5, 5, 35, 5), fill="black", width=2)
        draw.rectangle((5, 20, 35, 65), outline="black", width=2)
        draw.ellipse((60, 20, 110, 65), outline="black", width=2)
        self.save(image)
        strokes, source = self.read()
        self.assertEqual(len(strokes), 5)  # Line + inner/outer rectangle + inner/outer ellipse.
        self.assertEqual(source["format"], "JPEG")
        self.assertTrue(all(5 <= p.x <= 145 and 5 <= p.y <= 95 for s in strokes for p in s))
        job = convert(self.path, self.root / "job.json", simulation_profile())
        self.assertEqual(load_job(self.root / "job.json"), job)

    def test_white_image_is_not_a_valid_job(self):
        self.save(Image.new("RGB", (10, 10), "white"))
        with self.assertRaisesRegex(ValueError, "No dark boundaries"):
            self.read()

    def test_solid_image_has_outer_boundary(self):
        self.save(Image.new("RGB", (10, 10), "black"))
        strokes, _ = self.read()
        self.assertEqual(len(strokes), 1)
        self.assertEqual(len(strokes[0]), 5)

    def test_wrong_format_empty_corrupt_and_missing(self):
        for content in (b"", b"not a jpeg", b"\xff\xd8\xff\xdb\x00"):
            self.path.write_bytes(content)
            with self.assertRaises(ValueError):
                self.read()
        Image.new("RGB", (5, 5)).save(self.path, format="PNG")
        with self.assertRaisesRegex(ValueError, "JPEG content"):
            self.read()
        with self.assertRaises(FileNotFoundError):
            read_jpg(self.root / "missing.jpg", 150, 100, 5)

    def test_threshold_and_resolution_validation(self):
        for kwargs in (
            {"threshold": 0},
            {"threshold": True},
            {"threshold": 256},
            {"resolution": 1},
            {"resolution": 513},
        ):
            with self.assertRaises(ValueError):
                self.read(**kwargs)

    def test_resolution_limits_and_exif_orientation(self):
        image = Image.new("RGB", (160, 80), "white")
        ImageDraw.Draw(image).rectangle((10, 10, 40, 40), fill="black")
        exif = Image.Exif()
        exif[274] = 6
        image.save(self.path, exif=exif)
        _, source = self.read(resolution=32)
        self.assertEqual(source["original_size"], [80, 160])
        self.assertEqual(source["sampled_size"], [16, 32])

    def test_input_is_not_overwritten(self):
        self.save(Image.new("RGB", (10, 10), "black"))
        disguised = self.root / "input.gcode"
        disguised.write_bytes(self.path.read_bytes())
        with self.assertRaisesRegex(ValueError, "overwrite"):
            convert(disguised, disguised, simulation_profile())

    def test_cli_headless_demo_and_failure_exit(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "plotter",
                "demo",
                "--headless",
                "--output-dir",
                str(self.root / "demo"),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SIMULATION: completed", result.stdout)
        data = json.loads((self.root / "demo/sample.json").read_text())
        self.assertTrue(data["profile"]["simulation"])
        result = subprocess.run(
            [sys.executable, "-m", "plotter", "convert", str(self.root / "missing.jpg")],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Error:", result.stderr)

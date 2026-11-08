import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from plotter.__main__ import convert, simulation_profile
from plotter.gcode import load_job
from plotter.images import read_image


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "input.jpg"

    def save(self, image):
        image.save(self.path, quality=100, subsampling=0)

    def read(self, **kwargs):
        return read_image(self.path, 150, 100, 5, **kwargs)

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
        for format in ("GIF", "TIFF"):
            with self.subTest(format=format):
                Image.new("RGB", (5, 5)).save(self.path, format=format)
                with self.assertRaisesRegex(ValueError, "JPEG, PNG, and BMP"):
                    self.read()
        with self.assertRaises(FileNotFoundError):
            read_image(self.root / "missing.jpg", 150, 100, 5)

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
        for format in ("JPEG", "PNG"):
            with self.subTest(format=format):
                image.save(self.path, format=format, exif=exif)
                _, source = self.read(resolution=32)
                self.assertEqual(source["original_size"], [80, 160])
                self.assertEqual(source["sampled_size"], [16, 32])

    def test_png_and_bmp_share_geometry_and_convert_through_cli(self):
        image = Image.new("RGB", (40, 30), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, 18, 25), outline="black", width=2)
        draw.line((25, 5, 35, 5), fill="black", width=2)
        jobs = []
        for format in ("PNG", "BMP"):
            with self.subTest(format=format):
                # Decoding uses content, including when the extension is misleading.
                image.save(self.path, format=format)
                output = self.root / f"{format.lower()}.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "plotter",
                        "convert",
                        str(self.path),
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                job = load_job(output)
                self.assertEqual(job.source["format"], format)
                self.assertEqual(output.with_suffix(".gcode").read_text(), job.gcode)
                jobs.append(job)
        self.assertEqual(jobs[0].strokes, jobs[1].strokes)
        self.assertEqual(jobs[0].instructions, jobs[1].instructions)
        self.assertNotEqual(jobs[0].job_id, jobs[1].job_id)
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            {"input.jpg", "png.json", "png.gcode", "bmp.json", "bmp.gcode"},
        )

    def test_alpha_png_uses_white_background_including_partial_alpha(self):
        image = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, 10, 15), fill=(0, 0, 0, 255))
        draw.rectangle((14, 3, 18, 15), fill=(0, 0, 0, 64))
        draw.rectangle((22, 3, 26, 15), fill=(0, 0, 0, 192))
        reference = Image.new("RGB", image.size, "white")
        expected = ImageDraw.Draw(reference)
        expected.rectangle((3, 3, 10, 15), fill="black")
        expected.rectangle((22, 3, 26, 15), fill="black")
        reference.save(self.path, format="PNG")
        strokes, _ = self.read()
        for mode in ("RGBA", "LA"):
            with self.subTest(mode=mode):
                image.convert(mode).save(self.path, format="PNG")
                actual, _ = self.read()
                self.assertEqual(actual, strokes)

    def test_palette_and_rgb_transparency_use_white_background(self):
        reference = Image.new("RGB", (20, 20), "white")
        ImageDraw.Draw(reference).rectangle((4, 4, 15, 15), fill="black")
        reference.save(self.path, format="PNG")
        strokes, _ = self.read()
        for mode in ("P", "RGB", "L"):
            with self.subTest(mode=mode):
                image = Image.new(mode, reference.size, 0)
                if mode == "P":
                    image.putpalette([0, 0, 0, 1, 1, 1] + [0] * 762)
                ImageDraw.Draw(image).rectangle(
                    (4, 4, 15, 15), fill=(1, 1, 1) if mode == "RGB" else 1
                )
                transparency = (0, 0, 0) if mode == "RGB" else 0
                image.save(self.path, format="PNG", transparency=transparency)
                actual, _ = self.read()
                self.assertEqual(actual, strokes)

    def test_fully_transparent_png_is_empty(self):
        Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(self.path, format="PNG")
        with self.assertRaisesRegex(ValueError, "No dark boundaries"):
            self.read()

    def test_animated_png_is_rejected(self):
        frames = [Image.new("RGB", (20, 20), color) for color in ("black", "white")]
        frames[0].save(self.path, format="PNG", save_all=True, append_images=frames[1:])
        with self.assertRaisesRegex(ValueError, "Multiple frames or pages"):
            self.read()

    def test_input_limits_apply_to_all_supported_formats(self):
        for format in ("JPEG", "PNG", "BMP"):
            with self.subTest(format=format):
                Image.new("RGB", (20, 20), "black").save(self.path, format=format)
                with patch("plotter.images.MAX_FILE_BYTES", 10):
                    with self.assertRaisesRegex(ValueError, "20 MiB"):
                        self.read()
                with patch("plotter.images.MAX_IMAGE_PIXELS", 100):
                    with self.assertRaisesRegex(ValueError, "24-megapixel"):
                        self.read()

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

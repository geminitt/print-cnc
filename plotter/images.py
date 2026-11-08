"""Decode supported raster formats into one in-memory grayscale pipeline."""

from __future__ import annotations

import hashlib
import io
import warnings
from pathlib import Path

from .geometry import Stroke, boundaries, fit_image

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000


def read_image(
    path: Path,
    width: float,
    height: float,
    margin: float,
    threshold: int = 128,
    resolution: int = 256,
) -> tuple[tuple[Stroke, ...], dict]:
    """Extract the boundaries of pixels darker than threshold, including holes."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError("Threshold must be an integer from 1 to 255")
    if type(resolution) is not int or not 16 <= resolution <= 512:
        raise ValueError("Resolution must be an integer from 16 to 512")
    with path.open("rb") as stream:
        content = stream.read(MAX_FILE_BYTES + 1)
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Image must be nonempty and at most 20 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as original:
                image_format = original.format
                if image_format not in ("JPEG", "PNG", "BMP"):
                    raise ValueError("Supported image formats are JPEG, PNG, and BMP")
                if original.width * original.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds the 24-megapixel input limit")
                if getattr(original, "n_frames", 1) != 1:
                    raise ValueError("Multiple frames or pages are not supported")
                image = ImageOps.exif_transpose(original)
                if "A" in image.getbands() or "transparency" in image.info:
                    image = image.convert("RGBA")
                    image = Image.alpha_composite(Image.new("RGBA", image.size, "white"), image)
                image = image.convert("L")
                original_size = image.size
                image.thumbnail((resolution, resolution), Image.Resampling.LANCZOS)
                pixels = image.tobytes()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(f"Cannot decode image: {exc}") from exc
    mask = [
        [pixels[y * image.width + x] < threshold for x in range(image.width)]
        for y in range(image.height)
    ]
    strokes = fit_image(boundaries(mask), image.width, image.height, width, height, margin)
    return strokes, {
        "format": image_format,
        "sha256": hashlib.sha256(content).hexdigest(),
        "original_size": list(original_size),
        "sampled_size": list(image.size),
        "threshold": threshold,
        "resolution": resolution,
        "method": "dark-pixel boundaries; no centerline or grayscale fill",
    }

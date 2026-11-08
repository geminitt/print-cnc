"""Pixel boundaries and machine-space polylines."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float


Stroke = tuple[Point, ...]


def boundaries(mask: list[list[bool]]) -> tuple[Stroke, ...]:
    """Trace directed pixel edges. Preserve holes and separate diagonal pixels.

    Coordinates are pixel corners, with Y increasing downward. At a shared
    diagonal corner, the rightmost turn keeps the same foreground component.
    Only exactly collinear vertices are removed; no topology-changing smoothing.
    """
    if not mask or not mask[0] or any(len(row) != len(mask[0]) for row in mask):
        raise ValueError("Expected a nonempty rectangular pixel mask")
    height, width = len(mask), len(mask[0])
    outgoing: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)

    def dark(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and mask[y][x]

    for y, row in enumerate(mask):
        for x, pixel in enumerate(row):
            if not pixel:
                continue
            if not dark(x, y - 1):
                outgoing[x, y].add((x + 1, y))
            if not dark(x + 1, y):
                outgoing[x + 1, y].add((x + 1, y + 1))
            if not dark(x, y + 1):
                outgoing[x + 1, y + 1].add((x, y + 1))
            if not dark(x - 1, y):
                outgoing[x, y + 1].add((x, y))

    directions = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
    strokes = []
    # Snapshot keys avoids rescanning all vertices for each disconnected speck.
    for start in sorted(outgoing):
        while outgoing.get(start):
            current = start
            vertices = [start]
            direction = None
            while True:
                candidates = outgoing[current]
                if direction is None:
                    end = min(candidates)
                else:

                    def rank(p: tuple[int, int], vertex=current, incoming=direction) -> int:
                        turn = (directions[p[0] - vertex[0], p[1] - vertex[1]] - incoming) % 4
                        return {1: 0, 0: 1, 3: 2, 2: 3}[turn]

                    end = min(candidates, key=rank)
                candidates.remove(end)
                direction = directions[end[0] - current[0], end[1] - current[1]]
                vertices.append(end)
                current = end
                if current == start:
                    break
            reduced = []
            for index, vertex in enumerate(vertices[:-1]):
                previous = vertices[index - 1] if index else vertices[-2]
                following = vertices[index + 1]
                if (vertex[0] - previous[0]) * (following[1] - vertex[1]) != (
                    vertex[1] - previous[1]
                ) * (following[0] - vertex[0]):
                    reduced.append(Point(*vertex))
            strokes.append(tuple(reduced + [reduced[0]]))
    if not strokes:
        raise ValueError("No dark boundaries found; adjust the threshold or use another image")
    return tuple(strokes)


def fit_image(
    strokes: tuple[Stroke, ...],
    width: int,
    height: int,
    work_width: float,
    work_height: float,
    margin: float,
) -> tuple[Stroke, ...]:
    """Fit the full image, preserve its aspect ratio, and flip Y to bottom-left."""
    if (
        width <= 0
        or height <= 0
        or not all(math.isfinite(v) for v in (work_width, work_height, margin))
    ):
        raise ValueError("Invalid image or work-area dimensions")
    if margin < 0 or 2 * margin >= min(work_width, work_height):
        raise ValueError("Margin must leave a positive drawing area")
    scale = min((work_width - 2 * margin) / width, (work_height - 2 * margin) / height)
    left, bottom = (work_width - width * scale) / 2, (work_height - height * scale) / 2
    return tuple(
        tuple(
            Point(round(left + p.x * scale, 3), round(bottom + (height - p.y) * scale, 3))
            for p in stroke
        )
        for stroke in strokes
    )

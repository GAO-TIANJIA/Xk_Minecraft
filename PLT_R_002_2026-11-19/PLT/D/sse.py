"""RGB SSE reference and summed-area-table implementation."""

from __future__ import annotations

from array import array
from typing import Mapping, Optional, Sequence

from PLT.model import Candidate, PaletteEntry as PltPaletteEntry, RGBImage
from PLT.models import PaletteEntry as LegacyPaletteEntry, RgbImage, Segment


class SSEError(ValueError):
    """Raised for incompatible images, rectangles, or palette references."""


class RgbIntegral:
    """Six 64-bit summed-area tables for RGB sums and squared RGB sums."""

    def __init__(self, image: RGBImage) -> None:
        self.width = image.width
        self.height = image.height
        self.stride = image.width + 1
        table_size = self.stride * (image.height + 1)
        self._sums = [array("Q", [0]) * table_size for _ in range(3)]
        self._squares = [array("Q", [0]) * table_size for _ in range(3)]

        for y in range(image.height):
            row_running = [0, 0, 0]
            square_running = [0, 0, 0]
            previous_row = y * self.stride
            current_row = (y + 1) * self.stride
            pixel_base = y * image.width * 3
            for x in range(image.width):
                pixel = pixel_base + x * 3
                table_index = current_row + x + 1
                previous_index = previous_row + x + 1
                for channel in range(3):
                    value = image.pixels[pixel + channel]
                    row_running[channel] += value
                    square_running[channel] += value * value
                    self._sums[channel][table_index] = (
                        self._sums[channel][previous_index] + row_running[channel]
                    )
                    self._squares[channel][table_index] = (
                        self._squares[channel][previous_index] + square_running[channel]
                    )

    def _query(self, table: array, x: int, y: int, width: int, height: int) -> int:
        if (
            width <= 0
            or height <= 0
            or x < 0
            or y < 0
            or x + width > self.width
            or y + height > self.height
        ):
            raise SSEError("rectangle is empty or outside the source image")
        x2 = x + width
        y2 = y + height
        return (
            table[y2 * self.stride + x2]
            - table[y * self.stride + x2]
            - table[y2 * self.stride + x]
            + table[y * self.stride + x]
        )

    def region_sse(self, rect, rgb: Sequence[int]) -> int:
        return self.sse_for_color(rect.x, rect.y, rect.width, rect.height, rgb)

    def sse_for_color(self, x: int, y: int, width: int, height: int, rgb: Sequence[int]) -> int:
        if len(rgb) != 3 or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 255
            for value in rgb
        ):
            raise SSEError("palette RGB must contain three 8-bit integers")
        count = width * height
        distortion = 0
        for channel, color in enumerate(rgb):
            total = self._query(self._sums[channel], x, y, width, height)
            square_total = self._query(self._squares[channel], x, y, width, height)
            distortion += square_total - 2 * color * total + count * color * color
        return distortion


IntegralImage = RgbIntegral


def sse_candidate(
    candidate: Candidate,
    palette: Mapping[str, PltPaletteEntry],
    integral: IntegralImage,
) -> int:
    total = 0
    for rect in candidate.rects:
        try:
            entry = palette[rect.block_id]
        except KeyError as exc:
            raise SSEError("candidate references unknown block {!r}".format(rect.block_id)) from exc
        total += integral.sse_for_color(rect.x, rect.y, rect.width, rect.height, entry.rgb)
    return total


def reconstruct_candidate(
    candidate: Candidate,
    width: int,
    height: int,
    palette: Mapping[str, PltPaletteEntry],
) -> bytes:
    """Materialize a candidate RGB raster and reject overlap or incomplete cover."""
    if width <= 0 or height <= 0:
        raise SSEError("reconstruction dimensions must be positive")
    output = bytearray(width * height * 3)
    covered = bytearray(width * height)
    for rect in candidate.rects:
        if (
            rect.x < 0
            or rect.y < 0
            or rect.width <= 0
            or rect.height <= 0
            or rect.x + rect.width > width
            or rect.y + rect.height > height
        ):
            raise SSEError("candidate rectangle is empty or outside the image")
        try:
            rgb = palette[rect.block_id].rgb
        except KeyError as exc:
            raise SSEError("candidate references unknown block {!r}".format(rect.block_id)) from exc
        row = bytes(rgb) * rect.width
        for y in range(rect.y, rect.y + rect.height):
            pixel_start = y * width + rect.x
            pixel_end = pixel_start + rect.width
            if any(covered[pixel_start:pixel_end]):
                raise SSEError("candidate rectangles overlap")
            covered[pixel_start:pixel_end] = b"\x01" * rect.width
            byte_start = pixel_start * 3
            output[byte_start : byte_start + len(row)] = row
    if not all(covered):
        raise SSEError("candidate rectangles do not cover the complete image")
    return bytes(output)


def sse_reconstruction(source: RGBImage, reconstruction: RGBImage) -> int:
    """Compute the specified per-channel RGB SSE between two decoded rasters."""
    if (source.width, source.height) != (reconstruction.width, reconstruction.height):
        raise SSEError("source and reconstruction dimensions do not match")
    return sum((a - b) * (a - b) for a, b in zip(source.pixels, reconstruction.pixels))


def sse_from_segments(
    source: RgbImage,
    segments: Sequence[Segment],
    palette: Sequence[LegacyPaletteEntry],
    integral: Optional[RgbIntegral] = None,
) -> int:
    """Compute exact RGB SSE directly from rectangles without raster expansion."""
    if integral is None:
        integral = RgbIntegral(source)
    if (integral.width, integral.height) != (source.width, source.height):
        raise SSEError("integral table dimensions do not match source image")
    palette_by_id = {entry.block_id: entry for entry in palette}
    if len(palette_by_id) != len(palette):
        raise SSEError("palette block IDs must be unique")
    total = 0
    for segment in segments:
        try:
            entry = palette_by_id[segment.block_id]
        except KeyError as exc:
            raise SSEError("segment references unknown block {!r}".format(segment.block_id)) from exc
        total += integral.region_sse(segment.rect, entry.rgb)
    return total


def reconstruct(
    width: int,
    height: int,
    segments: Sequence[Segment],
    palette: Sequence[LegacyPaletteEntry],
) -> RgbImage:
    """Decode a rectangular segmentation into a validated RGB8 raster."""
    if width <= 0 or height <= 0:
        raise SSEError("reconstruction dimensions must be positive")
    palette_by_id = {entry.block_id: entry for entry in palette}
    if not palette_by_id or len(palette_by_id) != len(palette):
        raise SSEError("palette must be nonempty with unique block IDs")
    pixels = bytearray(width * height * 3)
    covered = bytearray(width * height)
    for segment in segments:
        rect = segment.rect
        if (
            rect.x < 0
            or rect.y < 0
            or rect.width <= 0
            or rect.height <= 0
            or rect.x2 > width
            or rect.y2 > height
        ):
            raise SSEError("segment rectangle is empty or outside the image")
        try:
            rgb = palette_by_id[segment.block_id].rgb
        except KeyError as exc:
            raise SSEError("segment references unknown block {!r}".format(segment.block_id)) from exc
        row = bytes(rgb) * rect.width
        for y in range(rect.y, rect.y2):
            pixel_start = y * width + rect.x
            pixel_end = pixel_start + rect.width
            if any(covered[pixel_start:pixel_end]):
                raise SSEError("segmentation rectangles overlap")
            covered[pixel_start:pixel_end] = b"\x01" * rect.width
            byte_start = pixel_start * 3
            pixels[byte_start : byte_start + len(row)] = row
    if not all(covered):
        raise SSEError("segmentation rectangles do not cover the complete image")
    return RgbImage(width, height, bytes(pixels))

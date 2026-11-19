"""Shared immutable data structures used by the PLT pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class RGBImage:
    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image width and height must be positive")
        if len(self.pixels) != self.width * self.height * 3:
            raise ValueError("RGB byte count does not match image dimensions")

    def get_pixel(self, x: int, y: int) -> RGB:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("pixel coordinate is outside the image")
        offset = (y * self.width + x) * 3
        return self.pixels[offset], self.pixels[offset + 1], self.pixels[offset + 2]

    def get_row(self, y: int) -> bytes:
        if not 0 <= y < self.height:
            raise IndexError("row coordinate is outside the image")
        start = y * self.width * 3
        return self.pixels[start : start + self.width * 3]


@dataclass(frozen=True)
class PaletteEntry:
    block_id: str
    rgb: RGB


@dataclass(frozen=True)
class Rect:
    """A zero-origin, half-open rectangle with its selected palette block."""

    x: int
    y: int
    width: int
    height: int
    block_id: str

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class Candidate:
    rects: Tuple[Rect, ...]
    distortion: int


@dataclass(frozen=True)
class DrawOp:
    """An internal-coordinate operation; SETB has width=height=1."""

    kind: str
    x: int
    y: int
    width: int
    height: int
    block_id: str


@dataclass(frozen=True)
class DrawPlan:
    name: str
    operations: Tuple[DrawOp, ...]
    n_fill: int
    n_setb: int
    cost: float

    @property
    def n_total(self) -> int:
        return self.n_fill + self.n_setb

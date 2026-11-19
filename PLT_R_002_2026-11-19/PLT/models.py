"""Compatibility geometry used by D.sse's direct segmentation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from PLT.model import PaletteEntry, RGBImage as RgbImage


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class Segment:
    rect: Rect
    block_id: str


__all__ = ["PaletteEntry", "Rect", "RgbImage", "Segment"]

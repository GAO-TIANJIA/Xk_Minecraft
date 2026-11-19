"""Configured public interface to the strict 24-bit BMP reader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from PLT.model import RGBImage
from PLT.READ_SOURCE.bmp import BMPReadError, read_bmp as _read_bmp


@dataclass(frozen=True)
class BMPReadConfig:
    """Input allocation limit. ``None`` explicitly disables the pixel cap."""

    max_pixels: Optional[int] = 16_777_216

    def __post_init__(self) -> None:
        if self.max_pixels is not None and (
            isinstance(self.max_pixels, bool)
            or not isinstance(self.max_pixels, int)
            or self.max_pixels <= 0
        ):
            raise ValueError("max_pixels must be None or a positive integer")


def estimate_peak_rgb_buffer_bytes(width: int, height: int) -> int:
    """Estimate the two packed RGB buffers used while returning an immutable image."""
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValueError("width must be a positive integer")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValueError("height must be a positive integer")
    return width * height * 3 * 2


def read_bmp(path: Union[str, Path], config: Optional[BMPReadConfig] = None) -> RGBImage:
    """Read a BMP using a configured pixel limit and return top-left RGB8 bytes."""
    if config is None:
        config = BMPReadConfig()
    if not isinstance(config, BMPReadConfig):
        raise TypeError("config must be a BMPReadConfig")
    return _read_bmp(path, config.max_pixels)


__all__ = [
    "BMPReadConfig",
    "BMPReadError",
    "RGBImage",
    "estimate_peak_rgb_buffer_bytes",
    "read_bmp",
]

"""Unified image input for supported BMP and PNG formats."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from PLT.model import RGBImage
from PLT.READ_SOURCE.bmp import BMPReadError
from PLT.READ_SOURCE.bmp_reader import BMPReadConfig
from PLT.READ_SOURCE.png import PNGReadError, PNG_SIGNATURE, read_png


class ImageReadError(ValueError):
    """Raised when an image is unreadable or has an unsupported format."""


ImageReadConfig = BMPReadConfig


def read_image(
    path: Union[str, Path], config: Optional[ImageReadConfig] = None
) -> RGBImage:
    """Dispatch by file signature and return the canonical RGB8 image."""
    source = Path(path)
    if config is None:
        config = ImageReadConfig()
    if not isinstance(config, ImageReadConfig):
        raise TypeError("config must be an ImageReadConfig")
    try:
        with source.open("rb") as stream:
            signature = stream.read(8)
    except OSError as exc:
        raise ImageReadError("cannot read image {}: {}".format(source, exc)) from exc
    try:
        if signature.startswith(b"BM"):
            from PLT.READ_SOURCE.bmp_reader import read_bmp

            return read_bmp(source, config)
        if signature == PNG_SIGNATURE:
            return read_png(source, config.max_pixels)
    except (BMPReadError, PNGReadError) as exc:
        message = str(exc)
        path_prefix = "{}:".format(source)
        if not message.startswith(path_prefix):
            message = "{}: {}".format(source, message)
        raise ImageReadError(message) from exc
    raise ImageReadError("{}: unsupported image signature; expected BMP or PNG".format(source))


__all__ = ["ImageReadConfig", "ImageReadError", "read_image"]

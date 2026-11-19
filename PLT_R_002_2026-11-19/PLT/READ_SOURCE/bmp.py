"""Reader for uncompressed 24-bit Windows BMP files."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional, Union

from PLT.model import RGBImage


class BMPReadError(ValueError):
    """Raised when a BMP is outside the supported subset or is malformed."""


def read_bmp(path: Union[str, Path], max_pixels: Optional[int] = 16_777_216) -> RGBImage:
    """Read BI_RGB 24-bit BMP and return top-left-origin packed RGB bytes."""
    source = Path(path)
    if max_pixels is not None and (
        isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0
    ):
        raise BMPReadError("max_pixels must be None or a positive integer")
    try:
        file_size_on_disk = source.stat().st_size
        with source.open("rb") as stream:
            file_header = stream.read(14)
            if len(file_header) != 14:
                raise BMPReadError("truncated BMP file header")
            signature, declared_size, _reserved1, _reserved2, pixel_offset = struct.unpack(
                "<2sIHHI", file_header
            )
            if signature != b"BM":
                raise BMPReadError("file signature is not BM")

            dib_size_bytes = stream.read(4)
            if len(dib_size_bytes) != 4:
                raise BMPReadError("truncated DIB header size")
            dib_size = struct.unpack("<I", dib_size_bytes)[0]
            if dib_size < 40:
                raise BMPReadError("only BITMAPINFOHEADER or larger DIB headers are supported")
            if dib_size > 1_048_576:
                raise BMPReadError("DIB header is unreasonably large")
            dib_rest = stream.read(dib_size - 4)
            if len(dib_rest) != dib_size - 4:
                raise BMPReadError("truncated DIB header")
            dib = dib_size_bytes + dib_rest
            (
                width,
                signed_height,
                planes,
                bits_per_pixel,
                compression,
                image_size,
                _x_pixels_per_meter,
                _y_pixels_per_meter,
                _colors_used,
                _important_colors,
            ) = struct.unpack_from("<iiHHIIiiII", dib, 4)

            if width <= 0 or signed_height == 0:
                raise BMPReadError("width must be positive and height must be nonzero")
            height = abs(signed_height)
            if max_pixels is not None and width * height > max_pixels:
                raise BMPReadError(
                    f"image has {width * height:,} pixels, above configured max_pixels "
                    f"of {max_pixels:,}"
                )
            if planes != 1:
                raise BMPReadError("BMP planes field must equal 1")
            if bits_per_pixel != 24:
                raise BMPReadError(
                    f"unsupported BMP bit depth {bits_per_pixel}; only uncompressed 24-bit is supported"
                )
            if compression != 0:
                raise BMPReadError("compressed BMP is unsupported; BI_RGB is required")

            header_end = 14 + dib_size
            if pixel_offset < header_end:
                raise BMPReadError("pixel data offset overlaps the BMP/DIB headers")
            if pixel_offset > file_size_on_disk:
                raise BMPReadError("pixel data offset is beyond end of file")
            row_stride = ((width * 3 + 3) // 4) * 4
            pixel_bytes = row_stride * height
            required_size = pixel_offset + pixel_bytes
            if required_size > file_size_on_disk:
                raise BMPReadError("pixel data is truncated")
            if declared_size and declared_size < required_size:
                raise BMPReadError("BMP file size field is smaller than the required pixel data")
            if declared_size and declared_size > file_size_on_disk:
                raise BMPReadError("BMP file size field exceeds the actual file size")
            if image_size and image_size < pixel_bytes:
                raise BMPReadError("DIB image size field is smaller than the required pixel data")

            stream.seek(pixel_offset)
            output = bytearray(width * height * 3)
            for stored_y in range(height):
                row = stream.read(row_stride)
                if len(row) != row_stride:
                    raise BMPReadError(f"truncated pixel row {stored_y}")
                target_y = stored_y if signed_height < 0 else height - 1 - stored_y
                target_base = target_y * width * 3
                for x in range(width):
                    source_base = x * 3
                    target = target_base + x * 3
                    blue, green, red = row[source_base : source_base + 3]
                    output[target : target + 3] = bytes((red, green, blue))
    except BMPReadError as exc:
        raise BMPReadError(f"{source}: {exc}") from exc
    except OSError as exc:
        raise BMPReadError(f"cannot read BMP {source}: {exc}") from exc

    try:
        return RGBImage(width=width, height=height, pixels=bytes(output))
    except ValueError as exc:
        raise BMPReadError(f"{source}: {exc}") from exc


def write_bmp(path: Union[str, Path], image: RGBImage) -> None:
    """Write an RGBImage as a 24-bit BI_RGB BMP with bottom-up rows."""
    destination = Path(path)
    row_stride = ((image.width * 3 + 3) // 4) * 4
    pixel_size = row_stride * image.height
    file_size = 54 + pixel_size
    if file_size > 0xFFFFFFFF:
        raise BMPReadError("image is too large for a classic BMP file")
    header = bytearray(54)
    header[:2] = b"BM"
    struct.pack_into("<I", header, 2, file_size)
    struct.pack_into("<I", header, 10, 54)
    struct.pack_into(
        "<IiiHHIIiiII", header, 14, 40, image.width, image.height,
        1, 24, 0, pixel_size, 2835, 2835, 0, 0,
    )
    output = bytearray(file_size)
    output[:54] = header
    padding = b"\0" * (row_stride - image.width * 3)
    for stored_y in range(image.height):
        y = image.height - 1 - stored_y
        source_offset = y * image.width * 3
        target_offset = 54 + stored_y * row_stride
        for x in range(image.width):
            red, green, blue = image.pixels[source_offset + x * 3 : source_offset + x * 3 + 3]
            output[target_offset + x * 3 : target_offset + x * 3 + 3] = bytes((blue, green, red))
        output[target_offset + image.width * 3 : target_offset + row_stride] = padding
    try:
        destination.write_bytes(output)
    except OSError as exc:
        raise BMPReadError("cannot write BMP {}: {}".format(destination, exc)) from exc

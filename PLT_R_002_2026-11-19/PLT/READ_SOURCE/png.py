"""Strict, dependency-free PNG reader returning the shared RGB8 image type."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Optional, Union

from PLT.model import RGBImage


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_FILE_BYTES = 512 * 1024 * 1024


class PNGReadError(ValueError):
    """Raised for malformed or unsupported PNG files."""


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    dl = abs(estimate - left)
    da = abs(estimate - above)
    dul = abs(estimate - upper_left)
    if dl <= da and dl <= dul:
        return left
    if da <= dul:
        return above
    return upper_left


def _unfilter(data: bytes, width: int, height: int, row_bytes: int, bpp: int) -> list[bytes]:
    expected = height * (row_bytes + 1)
    if len(data) != expected:
        raise PNGReadError("decompressed image data has an unexpected length")
    rows: list[bytes] = []
    previous = bytearray(row_bytes)
    offset = 0
    for _y in range(height):
        filter_type = data[offset]
        offset += 1
        scan = data[offset : offset + row_bytes]
        offset += row_bytes
        row = bytearray(row_bytes)
        if filter_type == 0:
            row[:] = scan
        elif filter_type in (1, 2, 3, 4):
            for x, value in enumerate(scan):
                left = row[x - bpp] if x >= bpp else 0
                above = previous[x]
                upper_left = previous[x - bpp] if x >= bpp else 0
                if filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = above
                elif filter_type == 3:
                    predictor = (left + above) // 2
                else:
                    predictor = _paeth(left, above, upper_left)
                row[x] = (value + predictor) & 0xFF
        else:
            raise PNGReadError("unknown PNG scanline filter {}".format(filter_type))
        rows.append(bytes(row))
        previous = row
    return rows


def _sample(row: bytes, pixel: int, channel: int, channels: int, bit_depth: int) -> int:
    sample_index = pixel * channels + channel
    if bit_depth == 8:
        return row[sample_index]
    if bit_depth == 16:
        return row[sample_index * 2]
    bit_offset = sample_index * bit_depth
    shift = 8 - bit_depth - (bit_offset & 7)
    return (row[bit_offset >> 3] >> shift) & ((1 << bit_depth) - 1)


def _sample_raw(row: bytes, pixel: int, channel: int, channels: int, bit_depth: int) -> int:
    sample_index = pixel * channels + channel
    if bit_depth == 16:
        offset = sample_index * 2
        return (row[offset] << 8) | row[offset + 1]
    if bit_depth == 8:
        return row[sample_index]
    bit_offset = sample_index * bit_depth
    shift = 8 - bit_depth - (bit_offset & 7)
    return (row[bit_offset >> 3] >> shift) & ((1 << bit_depth) - 1)


def _to_u8(value: int, bit_depth: int) -> int:
    if bit_depth == 16:
        return (value + 128) // 257
    if bit_depth < 8:
        return (value * 255) // ((1 << bit_depth) - 1)
    return value


def _composite_white(rgb: tuple[int, int, int], alpha: int) -> tuple[int, int, int]:
    return tuple((channel * alpha + 255 * (255 - alpha) + 127) // 255 for channel in rgb)


def read_png(
    path: Union[str, Path], max_pixels: Optional[int] = 16_777_216
) -> RGBImage:
    """Read non-interlaced PNG into top-left-origin packed RGB8 bytes.

    Grayscale, RGB, indexed-color, grayscale-alpha and RGBA images are
    supported. Transparency is composited over white before returning RGB8.
    """
    source = Path(path)
    if max_pixels is not None and (
        isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0
    ):
        raise PNGReadError("max_pixels must be None or a positive integer")
    try:
        file_size = source.stat().st_size
        if file_size > MAX_PNG_FILE_BYTES:
            raise PNGReadError("PNG file exceeds the 512 MiB input limit")
        raw = source.read_bytes()
    except PNGReadError:
        raise
    except OSError as exc:
        raise PNGReadError("cannot read PNG {}: {}".format(source, exc)) from exc

    try:
        if not raw.startswith(PNG_SIGNATURE):
            raise PNGReadError("file signature is not PNG")
        offset = len(PNG_SIGNATURE)
        width = height = bit_depth = color_type = interlace = None
        palette = None
        idat_parts: list[bytes] = []
        saw_ihdr = saw_idat = saw_iend = False
        ended_idat = False
        transparency: Optional[bytes] = None
        while offset < len(raw):
            if offset + 12 > len(raw):
                raise PNGReadError("truncated PNG chunk header")
            length = struct.unpack_from(">I", raw, offset)[0]
            chunk_type = raw[offset + 4 : offset + 8]
            offset += 8
            end = offset + length
            if end + 4 > len(raw):
                raise PNGReadError("truncated PNG {} chunk".format(chunk_type.decode("ascii", "replace")))
            chunk = raw[offset:end]
            expected_crc = struct.unpack_from(">I", raw, end)[0]
            if zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
                raise PNGReadError("CRC mismatch in PNG {} chunk".format(chunk_type.decode("ascii", "replace")))
            offset = end + 4

            if not saw_ihdr and chunk_type != b"IHDR":
                raise PNGReadError("IHDR must be the first PNG chunk")
            if chunk_type == b"IHDR":
                if saw_ihdr or length != 13:
                    raise PNGReadError("PNG must contain one 13-byte IHDR chunk")
                width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                    ">IIBBBBB", chunk
                )
                if width == 0 or height == 0:
                    raise PNGReadError("PNG width and height must be positive")
                if max_pixels is not None and width * height > max_pixels:
                    raise PNGReadError(
                        "image has {:,} pixels, above configured max_pixels of {:,}".format(
                            width * height, max_pixels
                        )
                    )
                if compression != 0 or filtering != 0:
                    raise PNGReadError("unsupported PNG compression or filter method")
                if interlace != 0:
                    raise PNGReadError("interlaced PNG is unsupported")
                valid_depths = {
                    0: (1, 2, 4, 8, 16),
                    2: (8, 16),
                    3: (1, 2, 4, 8),
                    4: (8, 16),
                    6: (8, 16),
                }
                if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
                    raise PNGReadError("unsupported PNG color type/bit depth combination")
                saw_ihdr = True
            elif chunk_type == b"PLTE":
                if (
                    saw_idat
                    or color_type == 0
                    or palette is not None
                    or length == 0
                    or length > 768
                    or length % 3
                ):
                    raise PNGReadError("invalid PNG palette chunk")
                palette = [tuple(chunk[i : i + 3]) for i in range(0, length, 3)]
            elif chunk_type == b"tRNS":
                if saw_idat or transparency is not None or color_type in (4, 6):
                    raise PNGReadError("invalid PNG tRNS transparency chunk")
                if color_type == 0 and length != 2:
                    raise PNGReadError("grayscale PNG tRNS chunk must contain 2 bytes")
                if color_type == 2 and length != 6:
                    raise PNGReadError("RGB PNG tRNS chunk must contain 6 bytes")
                if color_type == 3 and (palette is None or length > len(palette)):
                    raise PNGReadError("indexed PNG tRNS chunk must follow PLTE and fit its palette")
                if color_type not in (0, 2, 3):
                    raise PNGReadError("PNG tRNS is not valid for this color type")
                transparency = chunk
            elif chunk_type == b"IDAT":
                if ended_idat:
                    raise PNGReadError("PNG IDAT chunks must be consecutive")
                saw_idat = True
                idat_parts.append(chunk)
            elif chunk_type == b"IEND":
                if length != 0 or not saw_idat:
                    raise PNGReadError("invalid PNG IEND chunk")
                saw_iend = True
                if offset != len(raw):
                    raise PNGReadError("unexpected bytes after PNG IEND")
                break
            else:
                if saw_idat:
                    ended_idat = True
                if chunk_type[0] & 0x20 == 0:
                    raise PNGReadError("unknown critical PNG chunk {}".format(chunk_type.decode("ascii", "replace")))
            if saw_idat and chunk_type != b"IDAT":
                ended_idat = True

        if not saw_ihdr or not saw_iend or not idat_parts:
            raise PNGReadError("PNG is missing required IHDR, IDAT, or IEND chunks")
        if color_type == 3:
            if palette is None:
                raise PNGReadError("indexed-color PNG is missing PLTE")
            if len(palette) > (1 << bit_depth):
                raise PNGReadError("PNG palette has more entries than its bit depth allows")

        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        row_bytes = (width * channels * bit_depth + 7) // 8
        expected_size = height * (row_bytes + 1)
        inflater = zlib.decompressobj()
        compressed = b"".join(idat_parts)
        decoded = inflater.decompress(compressed, expected_size + 1)
        if len(decoded) <= expected_size:
            decoded += inflater.flush(expected_size + 1 - len(decoded))
        if len(decoded) != expected_size or not inflater.eof or inflater.unused_data:
            raise PNGReadError("PNG compressed image data is truncated or has excess data")

        bpp = max(1, (channels * bit_depth + 7) // 8)
        rows = _unfilter(decoded, width, height, row_bytes, bpp)
        output = bytearray(width * height * 3)
        for y, row in enumerate(rows):
            target_row = y * width * 3
            for x in range(width):
                if color_type == 3:
                    index = _sample(row, x, 0, 1, bit_depth)
                    if index >= len(palette):
                        raise PNGReadError("PNG pixel references a missing palette entry")
                    rgb = palette[index]
                    alpha = transparency[index] if transparency is not None and index < len(transparency) else 255
                elif color_type == 0:
                    raw_gray = _sample_raw(row, x, 0, 1, bit_depth)
                    gray = _to_u8(raw_gray, bit_depth)
                    rgb = (gray, gray, gray)
                    transparent_sample = (
                        struct.unpack(">H", transparency)[0] if transparency is not None else None
                    )
                    alpha = 0 if raw_gray == transparent_sample else 255
                elif color_type == 2:
                    raw_rgb = tuple(_sample_raw(row, x, channel, 3, bit_depth) for channel in range(3))
                    rgb = tuple(_to_u8(channel, bit_depth) for channel in raw_rgb)
                    transparent_rgb = (
                        struct.unpack(">HHH", transparency) if transparency is not None else None
                    )
                    alpha = 0 if raw_rgb == transparent_rgb else 255
                elif color_type == 4:
                    gray = _to_u8(_sample_raw(row, x, 0, 2, bit_depth), bit_depth)
                    alpha = _to_u8(_sample_raw(row, x, 1, 2, bit_depth), bit_depth)
                    rgb = (gray, gray, gray)
                else:
                    rgb = tuple(_to_u8(_sample_raw(row, x, channel, 4, bit_depth), bit_depth) for channel in range(3))
                    alpha = _to_u8(_sample_raw(row, x, 3, 4, bit_depth), bit_depth)
                if transparency is not None and color_type == 3:
                    if alpha != 255:
                        rgb = _composite_white(rgb, alpha)
                elif color_type in (4, 6) or transparency is not None:
                    rgb = _composite_white(rgb, alpha)
                pos = target_row + x * 3
                output[pos : pos + 3] = bytes(rgb)
        return RGBImage(width=width, height=height, pixels=bytes(output))
    except PNGReadError as exc:
        raise PNGReadError("{}: {}".format(source, exc)) from exc
    except (OverflowError, ValueError, zlib.error, struct.error) as exc:
        raise PNGReadError("{}: malformed PNG: {}".format(source, exc)) from exc

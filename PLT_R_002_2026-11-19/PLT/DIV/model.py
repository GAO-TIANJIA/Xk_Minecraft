"""Data models shared by the PLT division module and downstream RDO code."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from numbers import Integral
from types import MappingProxyType
from typing import Iterable, Iterator, Literal, Mapping

RGB = tuple[int, int, int]
RGBColorMethod = Literal["mean", "mode"]


def _integer(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _rgb(value: Iterable[int], name: str = "rgb") -> RGB:
    try:
        channels = tuple(value)
    except TypeError as exc:
        raise TypeError(f"{name} must be an iterable of three integers") from exc
    if len(channels) != 3:
        raise ValueError(f"{name} must contain exactly three channels")
    result: list[int] = []
    for channel in channels:
        number = _integer(channel, f"{name} channel", minimum=0)
        if number > 255:
            raise ValueError(f"{name} channels must be in the range 0..255")
        result.append(number)
    return result[0], result[1], result[2]


def _block_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("block_id must be a string")
    if not value or value != value.strip():
        raise ValueError("block_id must be non-empty and have no surrounding whitespace")
    return value


def representative_rgb(
    main_view_pixels: Iterable[Iterable[int]],
    method: RGBColorMethod = "mean",
) -> RGB:
    """Return the main-view average or modal RGB color.

    ``main_view_pixels`` must contain only samples from the block's chosen main
    view. The average is rounded to the nearest integer with half values rounded
    upward. For tied modes, the lexicographically lowest RGB triplet is chosen.
    """

    if method not in ("mean", "mode"):
        raise ValueError("method must be 'mean' or 'mode'")
    count = 0
    sums = [0, 0, 0]
    frequencies: Counter[RGB] = Counter()
    for sample in main_view_pixels:
        color = _rgb(sample, "main-view pixel")
        count += 1
        if method == "mean":
            sums[0] += color[0]
            sums[1] += color[1]
            sums[2] += color[2]
        else:
            frequencies[color] += 1
    if count == 0:
        raise ValueError("main_view_pixels must contain at least one RGB sample")
    if method == "mean":
        return (
            (sums[0] + count // 2) // count,
            (sums[1] + count // 2) // count,
            (sums[2] + count // 2) // count,
        )
    highest_frequency = max(frequencies.values())
    return min(color for color, frequency in frequencies.items() if frequency == highest_frequency)


@dataclass(frozen=True, slots=True)
class PaletteEntry:
    """One drawable block in the closed palette used by DIV.

    ``rgb`` is the representative main-view color used by SSE. Use
    :meth:`from_main_view` to derive it from the selected block-face samples.
    ``block_id`` is the stable key used by rectangles; state may be retained for
    later command serialization.
    """

    block_id: str
    rgb: RGB
    rgb_method: RGBColorMethod
    state: str | None = None
    stable_index: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "block_id", _block_id(self.block_id))
        object.__setattr__(self, "rgb", _rgb(self.rgb, "palette rgb"))
        if self.state is not None:
            if not isinstance(self.state, str):
                raise TypeError("state must be a string or None")
            if not self.state.strip():
                raise ValueError("state must be non-empty when provided")
        if self.stable_index is not None:
            object.__setattr__(self, "stable_index", _integer(self.stable_index, "stable_index", minimum=0))
        if self.rgb_method not in ("mean", "mode"):
            raise ValueError("rgb_method must be 'mean' or 'mode'")

    @classmethod
    def from_main_view(
        cls,
        block_id: str,
        main_view_pixels: Iterable[Iterable[int]],
        *,
        method: RGBColorMethod = "mean",
        state: str | None = None,
        stable_index: int | None = None,
    ) -> PaletteEntry:
        """Create an entry using the average or modal color of main-view pixels."""

        return cls(
            block_id=block_id,
            rgb=representative_rgb(main_view_pixels, method),
            state=state,
            stable_index=stable_index,
            rgb_method=method,
        )


@dataclass(frozen=True, slots=True, init=False)
class Palette:
    """Immutable closed set of drawable blocks available to candidate search.

    DIV never invents a block or selects a color outside this collection. The
    caller supplies the blocks supported by the target Minecraft environment.
    Missing stable indices default to input order; IDs and indices must be
    unique.
    """

    _entries: tuple[PaletteEntry, ...]
    _by_id: Mapping[str, PaletteEntry] = field(compare=False, hash=False, repr=False)

    def __init__(self, entries: Iterable[PaletteEntry]):
        source = tuple(entries)
        if not source:
            raise ValueError("palette must contain at least one drawable block")
        normalized: list[PaletteEntry] = []
        seen_ids: set[str] = set()
        seen_indices: set[int] = set()
        for position, entry in enumerate(source):
            if not isinstance(entry, PaletteEntry):
                raise TypeError("palette entries must be PaletteEntry instances")
            index = position if entry.stable_index is None else entry.stable_index
            if entry.block_id in seen_ids:
                raise ValueError(f"duplicate palette block_id: {entry.block_id!r}")
            if index in seen_indices:
                raise ValueError(f"duplicate palette stable_index: {index}")
            seen_ids.add(entry.block_id)
            seen_indices.add(index)
            normalized.append(replace(entry, stable_index=index))
        object.__setattr__(self, "_entries", tuple(normalized))
        object.__setattr__(
            self,
            "_by_id",
            MappingProxyType({entry.block_id: entry for entry in normalized}),
        )

    @property
    def entries(self) -> tuple[PaletteEntry, ...]:
        return self._entries

    @property
    def block_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    def get(self, block_id: str) -> PaletteEntry:
        try:
            return self._by_id[block_id]
        except KeyError as exc:
            raise KeyError(f"block_id is not in the drawable palette: {block_id!r}") from exc

    def __contains__(self, block_id: object) -> bool:
        return block_id in self._by_id

    def __iter__(self) -> Iterator[PaletteEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True, slots=True, init=False)
class RGBRaster:
    """Top-to-bottom, row-major RGB8 image stored as packed bytes.

    Pass packed RGB bytes to the constructor, or use :meth:`from_rows` with a
    sequence of RGB triplets. No alpha channel is accepted or interpreted here.
    """

    width: int
    height: int
    data: bytes

    def __init__(self, width: int, height: int, data: bytes | bytearray | memoryview):
        image_width = _integer(width, "width", minimum=1)
        image_height = _integer(height, "height", minimum=1)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be packed RGB bytes; use RGBRaster.from_rows for RGB triplets")
        packed = bytes(data)
        expected_length = image_width * image_height * 3
        if len(packed) != expected_length:
            raise ValueError(f"packed RGB data has {len(packed)} bytes; expected {expected_length}")
        object.__setattr__(self, "width", image_width)
        object.__setattr__(self, "height", image_height)
        object.__setattr__(self, "data", packed)

    @classmethod
    def from_rows(cls, rows: Iterable[Iterable[Iterable[int]]]) -> RGBRaster:
        """Build a raster from top-to-bottom rows of RGB triplets."""

        packed = bytearray()
        width: int | None = None
        height = 0
        for row_number, row in enumerate(rows):
            row_width = 0
            for pixel in row:
                packed.extend(_rgb(pixel, f"pixel at row {row_number}"))
                row_width += 1
            if row_width == 0:
                raise ValueError(f"row {row_number} must contain at least one pixel")
            if width is None:
                width = row_width
            elif width != row_width:
                raise ValueError("RGB rows must all have the same width")
            height += 1
        if width is None or height == 0:
            raise ValueError("RGB raster must contain at least one row")
        return cls(width, height, packed)

    def pixel(self, x: int, y: int) -> RGB:
        px = _integer(x, "x", minimum=0)
        py = _integer(y, "y", minimum=0)
        if px >= self.width or py >= self.height:
            raise IndexError("pixel coordinate is outside the raster")
        offset = (py * self.width + px) * 3
        return self.data[offset], self.data[offset + 1], self.data[offset + 2]

    def iter_pixels(self) -> Iterator[RGB]:
        for offset in range(0, len(self.data), 3):
            yield self.data[offset], self.data[offset + 1], self.data[offset + 2]


@dataclass(frozen=True, slots=True)
class Rect:
    """Zero-origin, half-open rectangular region assigned to one palette block."""

    x: int
    y: int
    width: int
    height: int
    block_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _integer(self.x, "x", minimum=0))
        object.__setattr__(self, "y", _integer(self.y, "y", minimum=0))
        object.__setattr__(self, "width", _integer(self.width, "width", minimum=1))
        object.__setattr__(self, "height", _integer(self.height, "height", minimum=1))
        object.__setattr__(self, "block_id", _block_id(self.block_id))

    def to_dict(self) -> dict[str, int | str]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "block_id": self.block_id,
        }


@dataclass(frozen=True, slots=True)
class CandidateSummary:
    region_count: int
    block_id_counts: tuple[tuple[str, int], ...]
    total_sse: int

    def to_dict(self) -> dict[str, object]:
        return {
            "region_count": self.region_count,
            "block_id_counts": dict(self.block_id_counts),
            "total_sse": self.total_sse,
        }


@dataclass(frozen=True, slots=True)
class SegmentationCandidate:
    width: int
    height: int
    rectangles: tuple[Rect, ...]
    total_sse: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", _integer(self.width, "width", minimum=1))
        object.__setattr__(self, "height", _integer(self.height, "height", minimum=1))
        rectangles = tuple(self.rectangles)
        if any(not isinstance(rect, Rect) for rect in rectangles):
            raise TypeError("rectangles must contain Rect instances")
        object.__setattr__(self, "rectangles", rectangles)
        object.__setattr__(self, "total_sse", _integer(self.total_sse, "total_sse", minimum=0))

    @property
    def summary(self) -> CandidateSummary:
        counts = Counter(rect.block_id for rect in self.rectangles)
        return CandidateSummary(
            region_count=len(self.rectangles),
            block_id_counts=tuple(sorted(counts.items())),
            total_sse=self.total_sse,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "rectangles": [rect.to_dict() for rect in self.rectangles],
            "summary": self.summary.to_dict(),
        }

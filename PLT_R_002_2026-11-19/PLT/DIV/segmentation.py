"""Deterministic rectangle candidate generation for PLT."""

from __future__ import annotations

import heapq
from array import array
from bisect import bisect_left
from dataclasses import dataclass
from numbers import Integral
from typing import Callable, Iterator

from .model import Palette, PaletteEntry, RGBRaster, Rect, SegmentationCandidate

_U32_MAX = (1 << 32) - 1
_U64_MAX = (1 << 64) - 1
_MAX_RGB_SQUARE_SUM_PER_PIXEL = 3 * 255 * 255


def _config_int(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


@dataclass(frozen=True, slots=True)
class SegmentationConfig:
    """Complexity limits for the deterministic greedy split search.

    Candidate zero is always the one-rectangle baseline. Every later candidate
    adds exactly one guillotine split. Limits are configurable by RDO; they do
    not encode or assume any RDO weight.
    """

    max_candidates: int = 32
    max_depth: int = 8
    max_regions: int = 256
    min_region_width: int = 1
    min_region_height: int = 1
    max_integral_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_candidates", _config_int(self.max_candidates, "max_candidates", minimum=1))
        object.__setattr__(self, "max_depth", _config_int(self.max_depth, "max_depth", minimum=0))
        object.__setattr__(self, "max_regions", _config_int(self.max_regions, "max_regions", minimum=1))
        object.__setattr__(
            self,
            "min_region_width",
            _config_int(self.min_region_width, "min_region_width", minimum=1),
        )
        object.__setattr__(
            self,
            "min_region_height",
            _config_int(self.min_region_height, "min_region_height", minimum=1),
        )
        object.__setattr__(
            self,
            "max_integral_bytes",
            _config_int(self.max_integral_bytes, "max_integral_bytes", minimum=0),
        )


_Stats = tuple[int, int, int, int]


def _subtract_stats(left: _Stats, right: _Stats) -> _Stats:
    return left[0] - right[0], left[1] - right[1], left[2] - right[2], left[3] - right[3]


class _RGBStats:
    """Exact rectangle sums, using a compact summed-area table when it fits."""

    __slots__ = ("raster", "_prefix", "total")

    def __init__(self, raster: RGBRaster, memory_limit: int):
        self.raster = raster
        self._prefix: tuple[array, array, array, array] | None = None
        pixel_count = raster.width * raster.height
        if pixel_count * _MAX_RGB_SQUARE_SUM_PER_PIXEL > _U64_MAX:
            raise OverflowError("image is too large for the 64-bit RGB squared-sum accumulator")

        sum_code = "I" if pixel_count * 255 <= _U32_MAX and array("I").itemsize == 4 else "Q"
        if array("Q").itemsize == 8:
            stride = raster.width + 1
            cell_count = stride * (raster.height + 1)
            estimated_bytes = cell_count * (3 * array(sum_code).itemsize + 8)
            if memory_limit and estimated_bytes <= memory_limit:
                try:
                    self._prefix = self._build_prefix(sum_code, cell_count, stride)
                except MemoryError:
                    self._prefix = None
        self.total = self._prefix_stats(0, 0, raster.width, raster.height) if self._prefix else self._scan(
            0, 0, raster.width, raster.height
        )

    def _build_prefix(self, sum_code: str, cell_count: int, stride: int) -> tuple[array, array, array, array]:
        red = array(sum_code, [0]) * cell_count
        green = array(sum_code, [0]) * cell_count
        blue = array(sum_code, [0]) * cell_count
        squares = array("Q", [0]) * cell_count
        data = self.raster.data
        width = self.raster.width
        for y in range(self.raster.height):
            row_r = row_g = row_b = row_sq = 0
            above = y * stride
            current = (y + 1) * stride
            source = y * width * 3
            for x in range(width):
                offset = source + x * 3
                r, g, b = data[offset], data[offset + 1], data[offset + 2]
                row_r += r
                row_g += g
                row_b += b
                row_sq += r * r + g * g + b * b
                destination = current + x + 1
                previous_row = above + x + 1
                red[destination] = red[previous_row] + row_r
                green[destination] = green[previous_row] + row_g
                blue[destination] = blue[previous_row] + row_b
                squares[destination] = squares[previous_row] + row_sq
        return red, green, blue, squares

    def _prefix_stats(self, x: int, y: int, width: int, height: int) -> _Stats:
        assert self._prefix is not None
        stride = self.raster.width + 1
        top_left = y * stride + x
        top_right = y * stride + x + width
        bottom_left = (y + height) * stride + x
        bottom_right = (y + height) * stride + x + width
        result = []
        for plane in self._prefix:
            result.append(
                int(plane[bottom_right])
                - int(plane[top_right])
                - int(plane[bottom_left])
                + int(plane[top_left])
            )
        return result[0], result[1], result[2], result[3]

    def _scan(self, x: int, y: int, width: int, height: int) -> _Stats:
        data = self.raster.data
        image_width = self.raster.width
        sum_r = sum_g = sum_b = sum_sq = 0
        for row in range(y, y + height):
            offset = (row * image_width + x) * 3
            end = offset + width * 3
            while offset < end:
                r, g, b = data[offset], data[offset + 1], data[offset + 2]
                sum_r += r
                sum_g += g
                sum_b += b
                sum_sq += r * r + g * g + b * b
                offset += 3
        return sum_r, sum_g, sum_b, sum_sq

    def rect(self, x: int, y: int, width: int, height: int) -> _Stats:
        if self._prefix is not None:
            return self._prefix_stats(x, y, width, height)
        return self._scan(x, y, width, height)

    def line_stats(self, x: int, y: int, width: int, height: int) -> tuple[list[_Stats], list[_Stats]]:
        """Return per-row and per-column sums in one pixel pass (low-memory path)."""

        rows = [[0, 0, 0, 0] for _ in range(height)]
        columns = [[0, 0, 0, 0] for _ in range(width)]
        data = self.raster.data
        image_width = self.raster.width
        for dy in range(height):
            row_sums = rows[dy]
            offset = ((y + dy) * image_width + x) * 3
            for dx in range(width):
                r, g, b = data[offset], data[offset + 1], data[offset + 2]
                square_sum = r * r + g * g + b * b
                row_sums[0] += r
                row_sums[1] += g
                row_sums[2] += b
                row_sums[3] += square_sum
                column_sums = columns[dx]
                column_sums[0] += r
                column_sums[1] += g
                column_sums[2] += b
                column_sums[3] += square_sum
                offset += 3
        return (
            [tuple(values) for values in rows],  # type: ignore[list-item]
            [tuple(values) for values in columns],  # type: ignore[list-item]
        )


def _palette_error(stats: _Stats, area: int, entry: PaletteEntry) -> int:
    r, g, b = entry.rgb
    error = stats[3] - 2 * (r * stats[0] + g * stats[1] + b * stats[2]) + area * (r * r + g * g + b * b)
    if error < 0:
        raise ArithmeticError("computed palette SSE is negative")
    return error


def _best_palette(stats: _Stats, area: int, palette: Palette) -> tuple[PaletteEntry, int]:
    best_entry: PaletteEntry | None = None
    best_error: int | None = None
    for entry in palette:
        error = _palette_error(stats, area, entry)
        if best_error is None or error < best_error:
            best_entry, best_error = entry, error
        elif error == best_error:
            assert best_entry is not None
            assert entry.stable_index is not None and best_entry.stable_index is not None
            if entry.stable_index < best_entry.stable_index:
                best_entry = entry
    assert best_entry is not None and best_error is not None
    return best_entry, best_error


@dataclass(frozen=True, slots=True)
class _Region:
    serial: int
    x: int
    y: int
    width: int
    height: int
    depth: int
    entry: PaletteEntry
    sse: int
    stats: _Stats


@dataclass(frozen=True, slots=True)
class _Child:
    x: int
    y: int
    width: int
    height: int
    depth: int
    entry: PaletteEntry
    sse: int
    stats: _Stats


@dataclass(frozen=True, slots=True)
class _SplitProposal:
    region_serial: int
    gain: int
    axis_rank: int
    offset: int
    first: _Child
    second: _Child


def _best_split(
    region: _Region,
    stats_backend: _RGBStats,
    palette: Palette,
    config: SegmentationConfig,
) -> _SplitProposal | None:
    if region.depth >= config.max_depth:
        return None
    can_split_x = region.width >= 2 * config.min_region_width
    can_split_y = region.height >= 2 * config.min_region_height
    if not can_split_x and not can_split_y:
        return None

    rows: list[_Stats] | None = None
    columns: list[_Stats] | None = None
    if stats_backend._prefix is None:
        rows, columns = stats_backend.line_stats(region.x, region.y, region.width, region.height)

    best: _SplitProposal | None = None
    best_key: tuple[int, int, int, int, int] | None = None

    def consider(
        axis_rank: int,
        offset: int,
        first: _Child,
        second: _Child,
    ) -> None:
        nonlocal best, best_key
        gain = region.sse - first.sse - second.sse
        if gain < 0:
            raise ArithmeticError("a split increased minimum palette SSE")
        first_index = first.entry.stable_index
        second_index = second.entry.stable_index
        assert first_index is not None and second_index is not None
        key = (-gain, axis_rank, offset, first_index, second_index)
        if best_key is None or key < best_key:
            best_key = key
            best = _SplitProposal(region.serial, gain, axis_rank, offset, first, second)

    if can_split_x:
        left_stats = [0, 0, 0, 0]
        for offset in range(1, region.width + 1):
            if columns is not None:
                column = columns[offset - 1]
                for channel in range(4):
                    left_stats[channel] += column[channel]
            if offset < config.min_region_width or region.width - offset < config.min_region_width:
                continue
            first_stats = (
                tuple(left_stats) if columns is not None else stats_backend.rect(region.x, region.y, offset, region.height)
            )
            second_stats = _subtract_stats(region.stats, first_stats)
            first_entry, first_error = _best_palette(first_stats, offset * region.height, palette)
            second_entry, second_error = _best_palette(
                second_stats, (region.width - offset) * region.height, palette
            )
            first = _Child(
                region.x,
                region.y,
                offset,
                region.height,
                region.depth + 1,
                first_entry,
                first_error,
                first_stats,
            )
            second = _Child(
                region.x + offset,
                region.y,
                region.width - offset,
                region.height,
                region.depth + 1,
                second_entry,
                second_error,
                second_stats,
            )
            consider(0, offset, first, second)

    if can_split_y:
        top_stats = [0, 0, 0, 0]
        for offset in range(1, region.height + 1):
            if rows is not None:
                row = rows[offset - 1]
                for channel in range(4):
                    top_stats[channel] += row[channel]
            if offset < config.min_region_height or region.height - offset < config.min_region_height:
                continue
            first_stats = (
                tuple(top_stats) if rows is not None else stats_backend.rect(region.x, region.y, region.width, offset)
            )
            second_stats = _subtract_stats(region.stats, first_stats)
            first_entry, first_error = _best_palette(first_stats, region.width * offset, palette)
            second_entry, second_error = _best_palette(
                second_stats, region.width * (region.height - offset), palette
            )
            first = _Child(
                region.x,
                region.y,
                region.width,
                offset,
                region.depth + 1,
                first_entry,
                first_error,
                first_stats,
            )
            second = _Child(
                region.x,
                region.y + offset,
                region.width,
                region.height - offset,
                region.depth + 1,
                second_entry,
                second_error,
                second_stats,
            )
            consider(1, offset, first, second)
    return best


def _heap_item(region: _Region, proposal: _SplitProposal) -> tuple[object, ...]:
    first_index = proposal.first.entry.stable_index
    second_index = proposal.second.entry.stable_index
    assert first_index is not None and second_index is not None
    return (
        -proposal.gain,
        region.y,
        region.x,
        region.height,
        region.width,
        proposal.axis_rank,
        proposal.offset,
        first_index,
        second_index,
        region.serial,
        proposal,
    )


def baseline_candidate(raster: RGBRaster, palette: Palette) -> SegmentationCandidate:
    """Map the full image to the single palette block with lowest SSE."""

    if not isinstance(raster, RGBRaster):
        raise TypeError("raster must be an RGBRaster")
    if not isinstance(palette, Palette):
        raise TypeError("palette must be a Palette")
    stats = _RGBStats(raster, 0).total
    entry, error = _best_palette(stats, raster.width * raster.height, palette)
    candidate = SegmentationCandidate(
        raster.width,
        raster.height,
        (Rect(0, 0, raster.width, raster.height, entry.block_id),),
        error,
    )
    validate_candidate(candidate, palette=palette)
    return candidate


def iter_candidates(
    raster: RGBRaster,
    palette: Palette,
    config: SegmentationConfig | None = None,
    *,
    stop_when: Callable[[SegmentationCandidate], bool] | None = None,
) -> Iterator[SegmentationCandidate]:
    """Yield a baseline and deterministic greedy recursive-split candidates.

    Each step selects the currently legal split with the greatest reduction in
    minimum palette SSE. Equal-gain splits are ordered by region position,
    vertical before horizontal, cut offset, then palette stable index. The
    optional stop predicate is evaluated after each yielded candidate, allowing
    RDO to stop its request early. Raising ``max_candidates`` requests more.
    """

    if not isinstance(raster, RGBRaster):
        raise TypeError("raster must be an RGBRaster")
    if not isinstance(palette, Palette):
        raise TypeError("palette must be a Palette")
    if config is None:
        config = SegmentationConfig()
    if not isinstance(config, SegmentationConfig):
        raise TypeError("config must be a SegmentationConfig")
    if stop_when is not None and not callable(stop_when):
        raise TypeError("stop_when must be callable or None")

    need_splits = (
        config.max_candidates > 1
        and config.max_regions > 1
        and config.max_depth > 0
        and (
            raster.width >= 2 * config.min_region_width
            or raster.height >= 2 * config.min_region_height
        )
    )
    stats_backend = _RGBStats(raster, config.max_integral_bytes if need_splits else 0)
    root_entry, root_error = _best_palette(stats_backend.total, raster.width * raster.height, palette)
    root = _Region(
        0,
        0,
        0,
        raster.width,
        raster.height,
        0,
        root_entry,
        root_error,
        stats_backend.total,
    )
    active: dict[int, _Region] = {root.serial: root}
    heap: list[tuple[object, ...]] = []
    next_serial = 1

    def make_candidate(total_sse: int) -> SegmentationCandidate:
        rectangles = tuple(
            Rect(region.x, region.y, region.width, region.height, region.entry.block_id)
            for region in sorted(
                active.values(),
                key=lambda item: (item.y, item.x, item.height, item.width, item.entry.stable_index),
            )
        )
        candidate = SegmentationCandidate(raster.width, raster.height, rectangles, total_sse)
        validate_candidate(candidate, expected_width=raster.width, expected_height=raster.height, palette=palette)
        return candidate

    initial = make_candidate(root_error)
    yield initial
    if stop_when is not None and stop_when(initial):
        return
    if not need_splits:
        return

    root_split = _best_split(root, stats_backend, palette, config)
    if root_split is not None:
        heapq.heappush(heap, _heap_item(root, root_split))

    candidate_count = 1
    current_sse = root_error
    while heap and candidate_count < config.max_candidates and len(active) < config.max_regions:
        *_, proposal = heapq.heappop(heap)
        assert isinstance(proposal, _SplitProposal)
        region = active.pop(proposal.region_serial, None)
        if region is None:
            continue

        first = _Region(
            next_serial,
            proposal.first.x,
            proposal.first.y,
            proposal.first.width,
            proposal.first.height,
            proposal.first.depth,
            proposal.first.entry,
            proposal.first.sse,
            proposal.first.stats,
        )
        next_serial += 1
        second = _Region(
            next_serial,
            proposal.second.x,
            proposal.second.y,
            proposal.second.width,
            proposal.second.height,
            proposal.second.depth,
            proposal.second.entry,
            proposal.second.sse,
            proposal.second.stats,
        )
        next_serial += 1
        active[first.serial] = first
        active[second.serial] = second
        current_sse += first.sse + second.sse - region.sse
        candidate_count += 1

        for child in (first, second):
            child_split = _best_split(child, stats_backend, palette, config)
            if child_split is not None:
                heapq.heappush(heap, _heap_item(child, child_split))

        candidate = make_candidate(current_sse)
        yield candidate
        if stop_when is not None and stop_when(candidate):
            return


def generate_candidates(
    raster: RGBRaster,
    palette: Palette,
    config: SegmentationConfig | None = None,
    *,
    stop_when: Callable[[SegmentationCandidate], bool] | None = None,
) -> tuple[SegmentationCandidate, ...]:
    """Return all candidates allowed by configuration and the stop predicate."""

    return tuple(iter_candidates(raster, palette, config, stop_when=stop_when))


def validate_candidate(
    candidate: SegmentationCandidate,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
    palette: Palette | None = None,
) -> None:
    """Raise ``ValueError`` unless rectangles form a legal, complete tiling."""

    if not isinstance(candidate, SegmentationCandidate):
        raise TypeError("candidate must be a SegmentationCandidate")
    width = candidate.width
    height = candidate.height
    if expected_width is not None and _config_int(expected_width, "expected_width", minimum=1) != width:
        raise ValueError("candidate width does not match expected width")
    if expected_height is not None and _config_int(expected_height, "expected_height", minimum=1) != height:
        raise ValueError("candidate height does not match expected height")
    if palette is not None and not isinstance(palette, Palette):
        raise TypeError("palette must be a Palette or None")

    area_sum = 0
    events: list[tuple[int, int, int, int, Rect]] = []
    for rect in candidate.rectangles:
        if rect.x + rect.width > width or rect.y + rect.height > height:
            raise ValueError(f"rectangle is outside candidate bounds: {rect}")
        if palette is not None and rect.block_id not in palette:
            raise ValueError(f"rectangle block_id is not in the drawable palette: {rect.block_id!r}")
        area_sum += rect.width * rect.height
        events.append((rect.x + rect.width, 0, rect.y, rect.height, rect))
        events.append((rect.x, 1, rect.y, rect.height, rect))

    active_y: list[int] = []
    active_end: dict[int, int] = {}
    for _, phase, y, rect_height, rect in sorted(events, key=lambda event: event[:4]):
        if phase == 0:
            end_y = active_end.get(y)
            if end_y != y + rect_height:
                raise ValueError("rectangle overlap state is inconsistent")
            del active_end[y]
            active_y.pop(bisect_left(active_y, y))
            continue

        index = bisect_left(active_y, y)
        if index > 0 and active_end[active_y[index - 1]] > y:
            raise ValueError("rectangles overlap")
        if index < len(active_y) and active_y[index] < y + rect_height:
            raise ValueError("rectangles overlap")
        active_y.insert(index, y)
        active_end[y] = y + rect_height

    if active_y:
        raise ValueError("rectangle set has unclosed sweep intervals")
    if area_sum != width * height:
        raise ValueError(
            f"rectangles do not completely cover the image: covered area {area_sum}, expected {width * height}"
        )

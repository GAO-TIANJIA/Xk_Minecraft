"""Generate ordered FILL/SETB plans and account for every issued command."""

from __future__ import annotations

import math
import re
from decimal import Decimal, localcontext
from math import fsum
from typing import List, Optional, Sequence, Tuple

from PLT.model import Candidate, DrawOp, DrawPlan, Rect


_BLOCK_STATE = re.compile(
    r"^(?:[a-z0-9_.-]+:)?[a-z0-9_./-]+(?:\[[a-z0-9_.,=:+/\-]+\])?$"
)


class DrawPlanError(ValueError):
    """Raised when a segmentation, cost, or drawing limit is invalid."""


def _floor_power_of_two(value: int) -> int:
    return 1 << (value.bit_length() - 1)


def _fill_tile_size(width: int, height: int, max_fill_blocks: int) -> Tuple[int, int]:
    tile_width = _floor_power_of_two(min(width, max_fill_blocks))
    tile_height_limit = max(1, max_fill_blocks // tile_width)
    tile_height = _floor_power_of_two(min(height, tile_height_limit))
    return tile_width, tile_height


def _power2_spans(length: int) -> Tuple[Tuple[int, int], ...]:
    spans = []
    offset = 0
    remaining = length
    while remaining:
        size = 1 << (remaining.bit_length() - 1)
        spans.append((offset, size))
        offset += size
        remaining -= size
    return tuple(spans)


def _check_cost(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DrawPlanError(f"{name} cost must be a finite nonnegative number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DrawPlanError(f"{name} cost must be a finite nonnegative number") from exc
    if not math.isfinite(result) or result < 0:
        raise DrawPlanError(f"{name} cost must be a finite nonnegative number")
    return result


def _check_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DrawPlanError(f"{name} must be a nonnegative integer; zero means unlimited")
    return value


def _validate_candidate(
    candidate: Candidate,
    canvas_width: Optional[int] = None,
    canvas_height: Optional[int] = None,
) -> Tuple[Tuple[Rect, ...], int, int]:
    if not isinstance(candidate, Candidate):
        raise DrawPlanError("candidate must be a PLT.model.Candidate")
    try:
        rects = tuple(candidate.rects)
    except (AttributeError, TypeError) as exc:
        raise DrawPlanError("candidate must contain a sequence of rectangles") from exc
    if not rects:
        raise DrawPlanError("candidate must contain at least one rectangle")

    for index, rect in enumerate(rects):
        if not isinstance(rect, Rect):
            raise DrawPlanError(f"candidate rectangle {index} must be a PLT.model.Rect")
        for label, value in (
            ("x", rect.x),
            ("y", rect.y),
            ("width", rect.width),
            ("height", rect.height),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise DrawPlanError(f"candidate rectangle {index} {label} must be an integer")
        if rect.x < 0 or rect.y < 0 or rect.width <= 0 or rect.height <= 0:
            raise DrawPlanError(f"candidate rectangle {index} is empty or has negative coordinates")
        if (rect.width & (rect.width - 1)) or (rect.height & (rect.height - 1)):
            raise DrawPlanError(
                f"candidate rectangle {index} width and height must be powers of two"
            )
        if not isinstance(rect.block_id, str) or not _BLOCK_STATE.fullmatch(rect.block_id):
            raise DrawPlanError(
                f"candidate rectangle {index} has an invalid Java block name/state: "
                f"{rect.block_id!r}"
            )

    if (canvas_width is None) != (canvas_height is None):
        raise DrawPlanError("canvas_width and canvas_height must be supplied together")
    if canvas_width is None:
        width = max(rect.x + rect.width for rect in rects)
        height = max(rect.y + rect.height for rect in rects)
    else:
        if (
            isinstance(canvas_width, bool)
            or not isinstance(canvas_width, int)
            or canvas_width <= 0
            or isinstance(canvas_height, bool)
            or not isinstance(canvas_height, int)
            or canvas_height <= 0
        ):
            raise DrawPlanError("canvas dimensions must be positive integers")
        width = canvas_width
        height = canvas_height
        if any(rect.x + rect.width > width or rect.y + rect.height > height for rect in rects):
            raise DrawPlanError("candidate rectangle exceeds the supplied image dimensions")
    _validate_cover(rects, width, height)
    return rects, width, height


def _validate_cover(rects: Sequence[Rect], width: int, height: int) -> None:
    """Check exact coverage of the candidate's zero-origin bounding canvas."""

    events = {0: [], height: []}
    for index, rect in enumerate(rects):
        events.setdefault(rect.y, []).append((True, index))
        events.setdefault(rect.y + rect.height, []).append((False, index))

    active = {}
    previous_y = 0
    for y in sorted(events):
        if y > previous_y:
            intervals = sorted(
                (rects[index].x, rects[index].x + rects[index].width)
                for index in active
            )
            cursor = 0
            for start, end in intervals:
                if start < cursor:
                    raise DrawPlanError(
                        f"candidate rectangles overlap in rows {previous_y}:{y}"
                    )
                if start > cursor:
                    raise DrawPlanError(
                        f"candidate leaves a gap at x={cursor} in rows {previous_y}:{y}"
                    )
                cursor = end
            if cursor != width:
                raise DrawPlanError(
                    f"candidate leaves a gap at x={cursor} in rows {previous_y}:{y}"
                )

        for is_start, index in events[y]:
            if not is_start:
                active.pop(index, None)
        for is_start, index in events[y]:
            if is_start:
                active[index] = True
        previous_y = y


def _fill_geometry(rect: Rect, max_fill_blocks: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """Tile a rectangle into deterministic row-major, half-open subrectangles."""

    if rect.area == 1 or max_fill_blocks == 0 or rect.area <= max_fill_blocks:
        return ((rect.x, rect.y, rect.width, rect.height),)
    tile_width, tile_height = _fill_tile_size(
        rect.width, rect.height, max_fill_blocks
    )
    tiles = []
    y = rect.y
    while y < rect.y + rect.height:
        height = min(tile_height, rect.y + rect.height - y)
        x = rect.x
        while x < rect.x + rect.width:
            width = min(tile_width, rect.x + rect.width - x)
            tiles.append((x, y, width, height))
            x += width
        y += height
    return tuple(tiles)


def _fill_counts(rect: Rect, max_fill_blocks: int) -> Tuple[int, int, int]:
    """Return (operation count, FILL count, SETB count) without expanding tiles."""

    if rect.area == 1:
        return 1, 0, 1
    if max_fill_blocks == 0 or rect.area <= max_fill_blocks:
        return 1, 1, 0

    tile_width, tile_height = _fill_tile_size(
        rect.width, rect.height, max_fill_blocks
    )
    columns = (rect.width + tile_width - 1) // tile_width
    rows = (rect.height + tile_height - 1) // tile_height
    last_width = rect.width - (columns - 1) * tile_width
    last_height = rect.height - (rows - 1) * tile_height
    width_one_tiles = columns if tile_width == 1 else int(last_width == 1)
    height_one_tiles = rows if tile_height == 1 else int(last_height == 1)
    setb_count = width_one_tiles * height_one_tiles
    operation_count = columns * rows
    return operation_count, operation_count - setb_count, setb_count


def _fill_ops(rect: Rect, max_fill_blocks: int) -> Tuple[DrawOp, ...]:
    result = []
    for x, y, width, height in _fill_geometry(rect, max_fill_blocks):
        kind = "SETB" if width * height == 1 else "FILL"
        result.append(DrawOp(kind, x, y, width, height, rect.block_id))
    return tuple(result)


def _setb_ops(rect: Rect) -> Tuple[DrawOp, ...]:
    return tuple(
        DrawOp("SETB", x, y, 1, 1, rect.block_id)
        for y in range(rect.y, rect.y + rect.height)
        for x in range(rect.x, rect.x + rect.width)
    )


def _decimal_cost(n_fill: int, n_setb: int, c_fill: float, c_setb: float) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return Decimal(n_fill) * Decimal(str(c_fill)) + Decimal(n_setb) * Decimal(str(c_setb))


def _mode_ops(
    rects: Sequence[Rect],
    mode: str,
    c_fill: float,
    c_setb: float,
    max_fill_blocks: int,
    max_commands: int,
    prefix: Sequence[DrawOp] = (),
) -> Optional[Tuple[DrawOp, ...]]:
    operations = list(prefix)
    if max_commands and len(operations) > max_commands:
        return None

    for rect in rects:
        fill_total, fill_count, fill_setb = _fill_counts(rect, max_fill_blocks)
        setb_total = rect.area
        remaining = max_commands - len(operations) if max_commands else None

        if mode == "fill":
            selected = "fill"
        elif mode == "setb":
            selected = "setb"
        elif mode == "mixed":
            choices = []
            if remaining is None or fill_total <= remaining:
                choices.append(
                    (
                        _decimal_cost(fill_count, fill_setb, c_fill, c_setb),
                        fill_total,
                        0,
                        "fill",
                    )
                )
            if remaining is None or setb_total <= remaining:
                choices.append(
                    (_decimal_cost(0, setb_total, c_fill, c_setb), setb_total, 1, "setb")
                )
            if not choices:
                return None
            selected = min(choices)[3]
        else:
            raise DrawPlanError(f"unknown drawing mode: {mode!r}")

        operation_count = fill_total if selected == "fill" else setb_total
        if max_commands and len(operations) + operation_count > max_commands:
            return None
        if selected == "fill":
            part = _fill_ops(rect, max_fill_blocks)
        else:
            part = _setb_ops(rect)
        operations.extend(part)

    return tuple(operations)


def _make_plan(name: str, operations: Sequence[DrawOp], c_fill: float, c_setb: float) -> DrawPlan:
    ops = tuple(operations)
    n_fill = sum(1 for op in ops if op.kind == "FILL")
    n_setb = sum(1 for op in ops if op.kind == "SETB")
    try:
        fill_cost = n_fill * c_fill
        setb_cost = n_setb * c_setb
    except OverflowError as exc:
        raise DrawPlanError(
            "drawing plan cost is outside the supported finite numeric range"
        ) from exc
    if not math.isfinite(fill_cost) or not math.isfinite(setb_cost):
        raise DrawPlanError("drawing plan cost is outside the supported finite numeric range")
    try:
        cost = fsum((fill_cost, setb_cost))
    except OverflowError as exc:
        raise DrawPlanError("drawing plan cost is outside the supported finite numeric range") from exc
    if not math.isfinite(cost):
        raise DrawPlanError("drawing plan cost is outside the supported finite numeric range")
    return DrawPlan(name, ops, n_fill, n_setb, cost)


def _signature(plan: DrawPlan) -> Tuple[Tuple[str, int, int, int, int, str], ...]:
    return tuple(
        (op.kind, op.x, op.y, op.width, op.height, op.block_id)
        for op in plan.operations
    )


def generate_plans(
    candidate: Candidate,
    c_fill: float,
    c_setb: float,
    max_fill_blocks: int,
    max_commands: int,
    initial_background_block: Optional[str] = None,
    canvas_width: Optional[int] = None,
    canvas_height: Optional[int] = None,
) -> Tuple[DrawPlan, ...]:
    """Generate equivalent FILL, SETB, mixed, and optional prefill plans.

    Candidate rectangle order is preserved. Within a rectangle, SETB and tiled
    FILL operations are emitted in row-major order. ``max_fill_blocks`` and
    ``max_commands`` use zero to mean unlimited, matching PLOT_INTERFACE.
    ``initial_background_block`` explicitly requests a full-canvas first pass;
    all later overrides remain in the plan and are included in its cost.
    """

    rects, width, height = _validate_candidate(candidate, canvas_width, canvas_height)
    c_fill = _check_cost("C_fill", c_fill)
    c_setb = _check_cost("C_setb", c_setb)
    max_fill_blocks = _check_limit("max_fill_blocks", max_fill_blocks)
    max_commands = _check_limit("max_commands", max_commands)
    if initial_background_block is not None and (
        not isinstance(initial_background_block, str)
        or not _BLOCK_STATE.fullmatch(initial_background_block)
    ):
        raise DrawPlanError(
            "initial_background_block must be a Java block name with an optional state"
        )

    plans = []
    for name, mode in (("all_fill", "fill"), ("all_setb", "setb"), ("hybrid", "mixed")):
        operations = _mode_ops(
            rects, mode, c_fill, c_setb, max_fill_blocks, max_commands
        )
        if operations is not None:
            plans.append(_make_plan(name, operations, c_fill, c_setb))

    if initial_background_block is not None:
        background_rects = tuple(
            Rect(x, y, rect_width, rect_height, initial_background_block)
            for y, rect_height in _power2_spans(height)
            for x, rect_width in _power2_spans(width)
        )
        base_count = sum(
            _fill_counts(rect, max_fill_blocks)[0] for rect in background_rects
        )
        if not max_commands or base_count <= max_commands:
            base_ops = tuple(
                operation
                for rect in background_rects
                for operation in _fill_ops(rect, max_fill_blocks)
            )
            patches = tuple(rect for rect in rects if rect.block_id != initial_background_block)
            for name, mode in (
                ("overlay_all_fill", "fill"),
                ("overlay_all_setb", "setb"),
                ("overlay_hybrid", "mixed"),
            ):
                operations = _mode_ops(
                    patches,
                    mode,
                    c_fill,
                    c_setb,
                    max_fill_blocks,
                    max_commands,
                    prefix=base_ops,
                )
                if operations is not None:
                    plans.append(_make_plan(name, operations, c_fill, c_setb))

    unique = []
    seen = set()
    for plan in plans:
        signature = _signature(plan)
        if signature not in seen:
            seen.add(signature)
            unique.append(plan)
    if not unique:
        raise DrawPlanError(
            "no drawing plan satisfies the configured command limit; raise max_commands "
            "or max_fill_blocks"
        )
    return tuple(unique)


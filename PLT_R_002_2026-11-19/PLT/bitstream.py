"""Versioned JSON PLT representation and decoder-side consistency checks."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from PLT.model import Candidate, DrawPlan, PaletteEntry, RGBImage, Rect


FORMAT_NAME = "plt-block-codec"
FORMAT_VERSION = 1
_BLOCK_STATE = re.compile(
    r"^(?:[a-z0-9_.-]+:)?[a-z0-9_./-]+(?:\[[a-z0-9_.,=:+/\-]+\])?$"
)


class BitstreamError(ValueError):
    """Raised for malformed or inconsistent PLT stream data."""


@dataclass(frozen=True)
class WorldMapping:
    origin: Tuple[int, int, int]
    x_step: Tuple[int, int, int]
    y_step: Tuple[int, int, int]


@dataclass(frozen=True)
class DecodedStream:
    image: RGBImage
    operations: Tuple[dict, ...]
    palette: Tuple[PaletteEntry, ...]
    mapping: WorldMapping
    max_fill_blocks: int
    max_commands: int
    max_world_coord: int
    initial_background_block: str | None
    score: Dict[str, Any]


def create_stream(image: RGBImage, candidate: Candidate, plan: DrawPlan,
                  palette: Sequence[PaletteEntry], mapping: Any,
                  score: Mapping[str, Any], limits: Any,
                  initial_background_block: str | None = None) -> Dict[str, Any]:
    """Create the canonical, self-contained version 1 PLT JSON object."""
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "image": {
            "width": image.width,
            "height": image.height,
            "pixel_format": "RGB8",
        },
        "palette": [
            {"block_id": entry.block_id, "rgb": list(entry.rgb)} for entry in palette
        ],
        "partition": [
            {"x": rect.x, "y": rect.y, "width": rect.width,
             "height": rect.height, "block_id": rect.block_id}
            for rect in candidate.rects
        ],
        "draw_plan": {
            "name": plan.name,
            "prefill_block_id": initial_background_block,
            "operations": [
                {"order": index, "type": op.kind, "x": op.x, "y": op.y,
                 "width": op.width, "height": op.height, "block_id": op.block_id}
                for index, op in enumerate(plan.operations)
            ],
        },
        "world_mapping": {
            "origin": list(mapping.origin),
            "x_step": list(mapping.x_step),
            "y_step": list(mapping.y_step),
        },
        "limits": {
            "max_fill_blocks": limits.max_fill_blocks,
            "max_commands": limits.max_commands,
            "max_world_coord": limits.max_world_coord,
        },
        "score": dict(score),
    }


def dump_stream(stream: Mapping[str, Any]) -> str:
    return json.dumps(stream, ensure_ascii=False, indent=2, sort_keys=True,
                      allow_nan=False) + "\n"


def _integer(value: Any, label: str, minimum: int = 0,
             maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BitstreamError("{} must be an integer".format(label))
    if value < minimum or (maximum is not None and value > maximum):
        raise BitstreamError("{} is outside the supported range".format(label))
    return value


def _vector(value: Any, label: str, unit_axis: bool = False) -> Tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise BitstreamError("{} must contain three integers".format(label))
    items = tuple(_integer(item, label, -30_000_000, 30_000_000) for item in value)
    if unit_axis and (sum(item != 0 for item in items) != 1 or
                      any(item not in (-1, 0, 1) for item in items)):
        raise BitstreamError("{} must be a signed unit axis".format(label))
    return items


def _rectangle(item: Mapping[str, Any], label: str,
               width: int, height: int) -> Tuple[int, int, int, int]:
    x = _integer(item.get("x"), label + ".x")
    y = _integer(item.get("y"), label + ".y")
    rect_width = _integer(item.get("width"), label + ".width", 1)
    rect_height = _integer(item.get("height"), label + ".height", 1)
    if x + rect_width > width or y + rect_height > height:
        raise BitstreamError("{} lies outside the image".format(label))
    return x, y, rect_width, rect_height


def decode_stream(path: Path, max_pixels: int) -> DecodedStream:
    if isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0:
        raise BitstreamError("max_pixels must be a positive integer")
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BitstreamError("cannot read PLT stream {}: {}".format(path, exc)) from exc
    if not isinstance(raw, dict) or raw.get("format") != FORMAT_NAME:
        raise BitstreamError("input is not a PLT block codec stream")
    if type(raw.get("version")) is not int or raw["version"] != FORMAT_VERSION:
        raise BitstreamError("unsupported PLT stream version")

    image_info = raw.get("image")
    if not isinstance(image_info, dict):
        raise BitstreamError("image metadata is missing")
    width = _integer(image_info.get("width"), "image.width", 1)
    height = _integer(image_info.get("height"), "image.height", 1)
    if width * height > max_pixels:
        raise BitstreamError("PLT image exceeds configured max_pixels")
    if image_info.get("pixel_format") != "RGB8":
        raise BitstreamError("unsupported PLT pixel format")

    raw_palette = raw.get("palette")
    if not isinstance(raw_palette, list) or not raw_palette:
        raise BitstreamError("palette must be a nonempty array")
    palette = []
    palette_by_id = {}
    for index, item in enumerate(raw_palette):
        if not isinstance(item, dict):
            raise BitstreamError("palette[{}] must be an object".format(index))
        block_id = item.get("block_id")
        rgb = item.get("rgb")
        if not isinstance(block_id, str) or not _BLOCK_STATE.fullmatch(block_id):
            raise BitstreamError("palette[{}] has an invalid block name/state".format(index))
        if block_id in palette_by_id:
            raise BitstreamError("palette contains duplicate block IDs")
        if not isinstance(rgb, list) or len(rgb) != 3:
            raise BitstreamError("palette[{}].rgb must contain three bytes".format(index))
        color = tuple(_integer(value, "palette RGB", 0, 255) for value in rgb)
        entry = PaletteEntry(block_id, color)
        palette.append(entry)
        palette_by_id[block_id] = entry

    partition = raw.get("partition")
    if not isinstance(partition, list) or not partition:
        raise BitstreamError("partition must contain at least one rectangle")
    target = [None] * (width * height)
    for index, item in enumerate(partition):
        if not isinstance(item, dict):
            raise BitstreamError("partition[{}] must be an object".format(index))
        x, y, rect_width, rect_height = _rectangle(item, "partition[{}]".format(index), width, height)
        block_id = item.get("block_id")
        if not isinstance(block_id, str) or block_id not in palette_by_id:
            raise BitstreamError("partition[{}] references an unknown block".format(index))
        for row in range(y, y + rect_height):
            start = row * width + x
            end = start + rect_width
            if any(value is not None for value in target[start:end]):
                raise BitstreamError("partition rectangles overlap")
            target[start:end] = [block_id] * rect_width
    if any(value is None for value in target):
        raise BitstreamError("partition does not cover the complete image")

    raw_mapping = raw.get("world_mapping")
    if not isinstance(raw_mapping, dict):
        raise BitstreamError("world_mapping is missing")
    mapping = WorldMapping(
        _vector(raw_mapping.get("origin"), "world_mapping.origin"),
        _vector(raw_mapping.get("x_step"), "world_mapping.x_step", unit_axis=True),
        _vector(raw_mapping.get("y_step"), "world_mapping.y_step", unit_axis=True),
    )
    if sum(a * b for a, b in zip(mapping.x_step, mapping.y_step)) != 0:
        raise BitstreamError("world mapping steps must use perpendicular axes")
    limits = raw.get("limits")
    if not isinstance(limits, dict):
        raise BitstreamError("limits are missing")
    max_fill_blocks = _integer(limits.get("max_fill_blocks"), "limits.max_fill_blocks")
    max_commands = _integer(limits.get("max_commands"), "limits.max_commands")
    max_world_coord = _integer(limits.get("max_world_coord"), "limits.max_world_coord", 1, 30_000_000)
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        point = _map_point(mapping, x, y)
        if any(abs(value) > max_world_coord for value in point):
            raise BitstreamError("mapped image bounds exceed configured max_world_coord")

    draw_plan = raw.get("draw_plan")
    if not isinstance(draw_plan, dict) or not isinstance(draw_plan.get("operations"), list):
        raise BitstreamError("draw_plan.operations is missing")
    background = draw_plan.get("prefill_block_id")
    if background is not None and (not isinstance(background, str) or background not in palette_by_id):
        raise BitstreamError("initial_background_block is not in the palette")
    operations = []
    # The prefill is an ordinary first operation in overlay plans, not an
    # assumed world state. Replay always starts with unwritten pixels.
    replay = [None] * (width * height)
    for index, item in enumerate(draw_plan["operations"]):
        if not isinstance(item, dict):
            raise BitstreamError("draw_plan operation {} must be an object".format(index))
        order = item.get("order")
        if type(order) is not int or order != index:
            raise BitstreamError("draw operation order must be contiguous from zero")
        kind = item.get("type")
        if kind not in ("FILL", "SETB"):
            raise BitstreamError("draw operation {} has an unknown type".format(index))
        x, y, rect_width, rect_height = _rectangle(item, "draw operation {}".format(index), width, height)
        if kind == "SETB" and rect_width * rect_height != 1:
            raise BitstreamError("SETB must address exactly one image point")
        block_id = item.get("block_id")
        if not isinstance(block_id, str) or block_id not in palette_by_id:
            raise BitstreamError("draw operation {} references an unknown block".format(index))
        if kind == "FILL" and max_fill_blocks and rect_width * rect_height > max_fill_blocks:
            raise BitstreamError("draw operation exceeds configured FILL block limit")
        operation = {"type": kind, "x": x, "y": y, "width": rect_width,
                     "height": rect_height, "block_id": block_id, "order": index}
        operations.append(operation)
        for row in range(y, y + rect_height):
            start = row * width + x
            replay[start : start + rect_width] = [block_id] * rect_width
    if not operations:
        raise BitstreamError("draw plan contains no operations")
    if max_commands and len(operations) > max_commands:
        raise BitstreamError("draw plan exceeds configured command limit")
    if replay != target:
        raise BitstreamError("ordered draw operations do not reconstruct the partition")

    pixels = bytearray(width * height * 3)
    for index, block_id in enumerate(target):
        color = palette_by_id[block_id].rgb
        offset = index * 3
        pixels[offset : offset + 3] = bytes(color)
    image = RGBImage(width, height, bytes(pixels))
    score = raw.get("score")
    if not isinstance(score, dict):
        raise BitstreamError("score metadata is missing")
    for key in ("D", "R", "J"):
        value = score.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BitstreamError("score.{} must be finite and nonnegative".format(key))
    return DecodedStream(image, tuple(operations), tuple(palette), mapping,
                         max_fill_blocks, max_commands, max_world_coord,
                         background, score)


def _map_point(mapping: WorldMapping, x: int, y: int) -> Tuple[int, int, int]:
    return tuple(mapping.origin[i] + x * mapping.x_step[i] + y * mapping.y_step[i]
                 for i in range(3))


def commands_text(decoded: DecodedStream) -> str:
    lines = []
    for op in decoded.operations:
        x, y, width, height = op["x"], op["y"], op["width"], op["height"]
        block_id = op["block_id"]
        if op["type"] == "SETB":
            point = _map_point(decoded.mapping, x, y)
            if any(abs(value) > decoded.max_world_coord for value in point):
                raise BitstreamError("mapped SETB coordinate exceeds configured world limit")
            lines.append("SETB {} {} {} {}".format(
                point[0], point[1], point[2], block_id
            ))
        else:
            first = _map_point(decoded.mapping, x, y)
            last = _map_point(decoded.mapping, x + width - 1, y + height - 1)
            if any(abs(value) > decoded.max_world_coord for value in first + last):
                raise BitstreamError("mapped FILL coordinate exceeds configured world limit")
            low = tuple(min(a, b) for a, b in zip(first, last))
            high = tuple(max(a, b) for a, b in zip(first, last))
            lines.append("FILL {} {} {}, {} {} {} {}".format(
                low[0], low[1], low[2], high[0], high[1], high[2], block_id
            ))
    return "\n".join(lines) + "\n"

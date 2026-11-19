"""Strict JSON configuration parsing for the PLT TOP pipeline."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PLT.model import PaletteEntry


BLOCK_STATE = re.compile(
    r"^(?:[a-z0-9_.-]+:)?[a-z0-9_./-]+(?:\[[a-z0-9_.,=:+/\-]+\])?$"
)
BRIDGE_MAX_WORLD_COORD = 30_000_000


class ConfigurationError(ValueError):
    """Raised for missing, malformed, or inconsistent TOP settings."""


@dataclass(frozen=True)
class CoordinateMapping:
    origin: Tuple[int, int, int]
    x_step: Tuple[int, int, int]
    y_step: Tuple[int, int, int]


@dataclass(frozen=True)
class Limits:
    max_pixels: int
    max_fill_blocks: int
    max_commands: int
    max_world_coord: int


@dataclass(frozen=True)
class BrightnessSearch:
    min_scale: float
    max_scale: float
    steps: int


@dataclass(frozen=True)
class TopConfig:
    config_path: Path
    image_path: Path
    output_path: Path
    summary_path: Optional[Path]
    plt_path: Optional[Path]
    palette: Tuple[PaletteEntry, ...]
    brightness_scale: Optional[float]
    brightness_search: BrightnessSearch
    lambda_value: float
    c_fill: float
    c_setb: float
    mapping: CoordinateMapping
    limits: Limits
    initial_background_block: Optional[str] = None


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a JSON object")
    return value


def _check_keys(value: dict, required: set, optional: set, label: str) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise ConfigurationError(f"{label} is missing field(s): {', '.join(missing)}")
    if unknown:
        raise ConfigurationError(f"{label} has unknown field(s): {', '.join(unknown)}")


def _json_object_pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _integer(value: Any, label: str, minimum: int, maximum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise ConfigurationError(f"{label} must be at least {minimum}")
        raise ConfigurationError(f"{label} must be between {minimum} and {maximum}")
    return value


def _number(
    value: Any,
    label: str,
    minimum: float = 0.0,
    maximum: Optional[float] = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{label} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ConfigurationError(f"{label} must be a finite number") from exc
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        if maximum is None:
            raise ConfigurationError(f"{label} must be a finite number greater than or equal to {minimum}")
        raise ConfigurationError(f"{label} must be between {minimum} and {maximum}")
    return result


def _vector(value: Any, label: str) -> Tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ConfigurationError(f"{label} must contain exactly three integers")
    return tuple(_integer(component, f"{label}[{index}]", -BRIDGE_MAX_WORLD_COORD, BRIDGE_MAX_WORLD_COORD) for index, component in enumerate(value))


def _step(value: Any, label: str) -> Tuple[int, int, int]:
    vector = _vector(value, label)
    if sum(component != 0 for component in vector) != 1 or any(component not in (-1, 0, 1) for component in vector):
        raise ConfigurationError(f"{label} must be one signed unit axis, such as [1,0,0]")
    return vector


def _path(value: Any, label: str, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a nonempty path string")
    result = Path(value).expanduser()
    if not result.is_absolute():
        result = base / result
    return result.resolve()


def _normalized_block_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not BLOCK_STATE.fullmatch(value):
        raise ConfigurationError(
            f"{label} must be a Java block name/state accepted by PLOT_INTERFACE"
        )
    return value if ":" in value else f"minecraft:{value}"


def load_config(path: Path) -> TopConfig:
    config_path = path.expanduser().resolve()
    try:
        with config_path.open("r", encoding="utf-8-sig") as stream:
            raw = json.load(stream, object_pairs_hook=_json_object_pairs)
    except ConfigurationError:
        raise
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"cannot parse configuration {config_path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ConfigurationError(f"cannot read configuration {config_path}: {exc}") from exc

    root = _object(raw, "configuration")
    required = {"image", "output", "palette", "lambda", "costs", "mapping", "limits"}
    _check_keys(
        root,
        required,
        {
            "summary",
            "plt",
            "initial_background_block",
            "brightness_scale",
            "brightness_search",
            "search",
        },
        "configuration",
    )
    base = config_path.parent
    image_path = _path(root["image"], "image", base)
    output_path = _path(root["output"], "output", base)
    summary_path = None if root.get("summary") is None else _path(root["summary"], "summary", base)
    plt_path = None if root.get("plt") is None else _path(root["plt"], "plt", base)
    paths = [config_path, image_path, output_path]
    paths.extend([summary_path] if summary_path else [])
    paths.extend([plt_path] if plt_path else [])
    if len({str(item) for item in paths}) != len(paths):
        raise ConfigurationError("config, image, output, and summary paths must be different")

    palette_value = root["palette"]
    if not isinstance(palette_value, list) or not palette_value:
        raise ConfigurationError("palette must be a nonempty array")
    palette: List[PaletteEntry] = []
    seen_blocks = set()
    for index, raw_entry in enumerate(palette_value):
        label = f"palette[{index}]"
        entry = _object(raw_entry, label)
        _check_keys(entry, {"block_id", "rgb"}, set(), label)
        block_id = _normalized_block_id(entry["block_id"], f"{label}.block_id")
        if block_id in seen_blocks:
            raise ConfigurationError(f"palette contains duplicate block_id {block_id!r}")
        seen_blocks.add(block_id)
        rgb_value = entry["rgb"]
        if not isinstance(rgb_value, list) or len(rgb_value) != 3:
            raise ConfigurationError(f"{label}.rgb must contain exactly three 8-bit integers")
        rgb = tuple(_integer(channel, f"{label}.rgb[{channel_index}]", 0, 255) for channel_index, channel in enumerate(rgb_value))
        palette.append(PaletteEntry(block_id, rgb))

    initial_background_block = root.get("initial_background_block")
    if initial_background_block is not None:
        initial_background_block = _normalized_block_id(
            initial_background_block, "initial_background_block"
        )
        if initial_background_block not in {entry.block_id for entry in palette}:
            raise ConfigurationError("initial_background_block must be included in palette")

    lambda_value = _number(root["lambda"], "lambda")
    scale_value = root.get("brightness_scale", "auto")
    if scale_value == "auto":
        brightness_scale = None
    else:
        brightness_scale = _number(scale_value, "brightness_scale", 0.0, 4.0)
    brightness_obj = _object(
        root.get(
            "brightness_search",
            {"min_scale": 0.0, "max_scale": 4.0, "steps": 1025},
        ),
        "brightness_search",
    )
    _check_keys(
        brightness_obj,
        {"min_scale", "max_scale", "steps"},
        set(),
        "brightness_search",
    )
    brightness_search = BrightnessSearch(
        min_scale=_number(brightness_obj["min_scale"], "brightness_search.min_scale", 0.0, 4.0),
        max_scale=_number(brightness_obj["max_scale"], "brightness_search.max_scale", 0.0, 4.0),
        steps=_integer(brightness_obj["steps"], "brightness_search.steps", 2, 4097),
    )
    if brightness_search.min_scale >= brightness_search.max_scale:
        raise ConfigurationError("brightness_search.min_scale must be below max_scale")
    costs = _object(root["costs"], "costs")
    _check_keys(costs, {"fill", "setb"}, set(), "costs")
    c_fill = _number(costs["fill"], "costs.fill")
    c_setb = _number(costs["setb"], "costs.setb")

    mapping_obj = _object(root["mapping"], "mapping")
    _check_keys(mapping_obj, {"origin", "x_step", "y_step"}, set(), "mapping")
    origin = _vector(mapping_obj["origin"], "mapping.origin")
    x_step = _step(mapping_obj["x_step"], "mapping.x_step")
    y_step = _step(mapping_obj["y_step"], "mapping.y_step")
    if sum(a * b for a, b in zip(x_step, y_step)) != 0:
        raise ConfigurationError("mapping.x_step and mapping.y_step must use different world axes")

    limits_obj = _object(root["limits"], "limits")
    _check_keys(
        limits_obj,
        {"max_pixels", "max_fill_blocks", "max_commands", "max_world_coord"},
        set(),
        "limits",
    )
    limits = Limits(
        max_pixels=_integer(limits_obj["max_pixels"], "limits.max_pixels", 1),
        max_fill_blocks=_integer(limits_obj["max_fill_blocks"], "limits.max_fill_blocks", 0),
        max_commands=_integer(limits_obj["max_commands"], "limits.max_commands", 0),
        max_world_coord=_integer(
            limits_obj["max_world_coord"],
            "limits.max_world_coord",
            1,
            BRIDGE_MAX_WORLD_COORD,
        ),
    )

    return TopConfig(
        config_path=config_path,
        image_path=image_path,
        output_path=output_path,
        summary_path=summary_path,
        plt_path=plt_path,
        palette=tuple(palette),
        brightness_scale=brightness_scale,
        brightness_search=brightness_search,
        lambda_value=lambda_value,
        c_fill=c_fill,
        c_setb=c_setb,
        mapping=CoordinateMapping(origin, x_step, y_step),
        limits=limits,
        initial_background_block=initial_background_block,
    )

#!/usr/bin/env python3
"""Encode a BMP or PNG into an ordered SETB/FILL instruction file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from array import array
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

if __package__ in (None, ""):
    # Also support running this file with TOP itself as the current directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PLT.D import IntegralImage, SSEError, reconstruct_candidate, sse_candidate
from PLT.DIV import DivisionError, cluster_quantized_pixels
from PLT.R import DrawPlanError
from PLT.RDO import RDOError, SelectedResult, select_candidate
from PLT.READ_SOURCE import ImageReadConfig, ImageReadError, read_image
from PLT.TOP.configuration import (
    ConfigurationError,
    TopConfig,
    load_config,
)
from PLT.TOP.quantizer import QuantizationResult, quantize_to_palette
from PLT.model import Candidate, DrawOp, PaletteEntry, Rect, RGBImage
from PLT.bitstream import create_stream, dump_stream


class TOPError(ValueError):
    """Raised when the selected result cannot be safely serialized."""


def _is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def _point(mapping, x: int, y: int) -> Tuple[int, int, int]:
    return tuple(
        mapping.origin[axis] + x * mapping.x_step[axis] + y * mapping.y_step[axis]
        for axis in range(3)
    )


def _grid_from_candidate(candidate: Candidate, width: int, height: int, palette: Sequence[PaletteEntry]) -> array:
    block_indices = {entry.block_id: index for index, entry in enumerate(palette)}
    grid = array("i", [-1]) * (width * height)
    for rect in candidate.rects:
        if (
            rect.width <= 0
            or rect.height <= 0
            or rect.x < 0
            or rect.y < 0
            or rect.x + rect.width > width
            or rect.y + rect.height > height
        ):
            raise TOPError("candidate contains an empty or out-of-range rectangle")
        if rect.block_id not in block_indices:
            raise TOPError(f"candidate references unknown palette block {rect.block_id!r}")
        fill = array("i", [block_indices[rect.block_id]]) * rect.width
        for y in range(rect.y, rect.y + rect.height):
            start = y * width + rect.x
            end = start + rect.width
            if any(value != -1 for value in grid[start:end]):
                raise TOPError("candidate rectangles overlap")
            grid[start:end] = fill
    if any(value == -1 for value in grid):
        raise TOPError("candidate rectangles do not cover the complete image")
    return grid


def _grid_from_plan(
    operations: Sequence[DrawOp],
    width: int,
    height: int,
    palette: Sequence[PaletteEntry],
) -> array:
    block_indices = {entry.block_id: index for index, entry in enumerate(palette)}
    grid = array("i", [-1]) * (width * height)
    for op in operations:
        if op.block_id not in block_indices:
            raise TOPError(f"drawing operation references unknown block {op.block_id!r}")
        if op.kind == "SETB":
            if op.width != 1 or op.height != 1:
                raise TOPError("SETB operation must address exactly one pixel")
        elif op.kind != "FILL":
            raise TOPError(f"unsupported drawing operation {op.kind!r}")
        if (
            op.width <= 0
            or op.height <= 0
            or op.x < 0
            or op.y < 0
            or op.x + op.width > width
            or op.y + op.height > height
        ):
            raise TOPError("drawing operation is empty or outside the image")
        fill = array("i", [block_indices[op.block_id]]) * op.width
        for y in range(op.y, op.y + op.height):
            start = y * width + op.x
            grid[start : start + op.width] = fill
    if any(value == -1 for value in grid):
        raise TOPError("drawing plan leaves one or more pixels unpainted")
    return grid


def _world_coordinate_check(point: Tuple[int, int, int], config: TopConfig) -> None:
    limit = config.limits.max_world_coord
    for axis, value in zip("xyz", point):
        if abs(value) > limit:
            raise TOPError(
                f"mapped {axis} coordinate {value} exceeds configured limit {limit}"
            )


def _serialize_operations(operations: Sequence[DrawOp], image: RGBImage, config: TopConfig) -> List[str]:
    palette_ids = {entry.block_id for entry in config.palette}
    lines = []
    actual_fill = 0
    actual_setb = 0
    for index, op in enumerate(operations, start=1):
        if op.block_id not in palette_ids:
            raise TOPError(f"operation {index} references unknown block {op.block_id!r}")
        if op.kind == "SETB":
            if op.width != 1 or op.height != 1:
                raise TOPError(f"operation {index}: SETB must address one pixel")
            if not (0 <= op.x < image.width and 0 <= op.y < image.height):
                raise TOPError(f"operation {index}: SETB pixel is outside the image")
            point = _point(config.mapping, op.x, op.y)
            _world_coordinate_check(point, config)
            lines.append(f"SETB {point[0]} {point[1]} {point[2]} {op.block_id}")
            actual_setb += 1
        elif op.kind == "FILL":
            if (
                op.width <= 0
                or op.height <= 0
                or op.x < 0
                or op.y < 0
                or op.x + op.width > image.width
                or op.y + op.height > image.height
            ):
                raise TOPError(f"operation {index}: FILL rectangle is outside the image")
            if not _is_power_of_two(op.width) or not _is_power_of_two(op.height):
                raise TOPError(
                    f"operation {index}: FILL width and height must be powers of two"
                )
            area = op.width * op.height
            limit = config.limits.max_fill_blocks
            if limit and area > limit:
                raise TOPError(
                    f"operation {index}: FILL covers {area:,} blocks, above configured limit {limit:,}"
                )
            first = _point(config.mapping, op.x, op.y)
            last = _point(config.mapping, op.x + op.width - 1, op.y + op.height - 1)
            _world_coordinate_check(first, config)
            _world_coordinate_check(last, config)
            low = tuple(min(a, b) for a, b in zip(first, last))
            high = tuple(max(a, b) for a, b in zip(first, last))
            lines.append(
                f"FILL {low[0]} {low[1]} {low[2]}, {high[0]} {high[1]} {high[2]} {op.block_id}"
            )
            actual_fill += 1
        else:
            raise TOPError(f"operation {index}: unsupported operation type {op.kind!r}")

    if config.limits.max_commands and len(lines) > config.limits.max_commands:
        raise TOPError(
            f"plan has {len(lines):,} commands, above configured limit "
            f"{config.limits.max_commands:,}"
        )
    if not lines:
        raise TOPError("drawing plan contains no operations")
    if actual_fill + actual_setb != len(lines):
        raise TOPError("internal command count mismatch")
    return lines


def _raster_from_index_grid(grid: array, palette: Sequence[PaletteEntry]) -> bytes:
    output = bytearray(len(grid) * 3)
    for index, palette_index in enumerate(grid):
        rgb = palette[palette_index].rgb
        output[index * 3 : index * 3 + 3] = bytes(rgb)
    return bytes(output)


def _summary(
    config: TopConfig,
    image: RGBImage,
    quantization: QuantizationResult,
    candidates: Sequence[Candidate],
    selected: SelectedResult,
    command_lines: Sequence[str],
) -> dict:
    palette = {entry.block_id: list(entry.rgb) for entry in config.palette}
    return {
        "format": "PLT-TOP-summary-v3",
        "config": str(config.config_path),
        "input": str(config.image_path),
        "image": {"width": image.width, "height": image.height, "pixel_format": "RGB8"},
        "parameters": {
            "brightness_scale": quantization.brightness_scale,
            "brightness_rule": "scaled, rounded and clamped RGB selects wool labels; source RGB remains the fidelity reference",
            "brightness_objective": "minimum unscaled-source to selected-wool RGB SSE over inclusive uniform scale grid",
            "brightness_search": {
                "min_scale": config.brightness_search.min_scale,
                "max_scale": config.brightness_search.max_scale,
                "steps": config.brightness_search.steps,
                "evaluated_scales": quantization.searched_scales,
            },
            "quantization_backend": quantization.backend,
            "quantization_sse": quantization.distortion,
            "tree_clustering": "bottom-up binary/quadtree; merge equal wool labels only",
            "tree_canvas": {
                "width": 1 << (image.width - 1).bit_length(),
                "height": 1 << (image.height - 1).bit_length(),
                "pixel_count": (1 << (image.width - 1).bit_length())
                * (1 << (image.height - 1).bit_length()),
                "padding_is_output": False,
            },
            "lambda": config.lambda_value,
            "C_fill": config.c_fill,
            "C_setb": config.c_setb,
            "mapping": {
                "origin": list(config.mapping.origin),
                "x_step": list(config.mapping.x_step),
                "y_step": list(config.mapping.y_step),
            },
            "limits": {
                "max_pixels": config.limits.max_pixels,
                "max_fill_blocks": config.limits.max_fill_blocks,
                "max_commands": config.limits.max_commands,
                "max_world_coord": config.limits.max_world_coord,
            },
            "palette": palette,
            "initial_background_block": config.initial_background_block,
        },
        "bridge": {
            "profile": "PLOT_INTERFACE Java 26.3 single-player data-pack bridge",
            "recommended_options": {
                "--max-blocks": config.limits.max_fill_blocks,
                "--max-commands": config.limits.max_commands,
            },
            "zero_means_unlimited": True,
        },
        "result": {
            "D": selected.distortion,
            "R": selected.rate,
            "J": selected.score,
            "N_fill": selected.plan.n_fill,
            "N_setb": selected.plan.n_setb,
            "N_total": selected.plan.n_total,
            "plan": selected.plan.name,
            "candidate_count": len(candidates),
            "evaluated_plan_count": selected.evaluated_plan_count,
            "partition": [
                {
                    "x": rect.x,
                    "y": rect.y,
                    "width": rect.width,
                    "height": rect.height,
                    "block_id": rect.block_id,
                    "rgb": palette[rect.block_id],
                }
                for rect in selected.candidate.rects
            ],
            "commands": list(command_lines),
        },
    }


def _stage_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return temporary


def _write_outputs(config: TopConfig, command_text: str, summary: Optional[dict],
                   plt_text: Optional[str]) -> None:
    staged: List[Tuple[Path, Path]] = []
    try:
        if summary is not None and config.summary_path is not None:
            summary_text = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            staged.append((config.summary_path, _stage_text(config.summary_path, summary_text)))
        staged.append((config.output_path, _stage_text(config.output_path, command_text)))
        if plt_text is not None and config.plt_path is not None:
            staged.append((config.plt_path, _stage_text(config.plt_path, plt_text)))
        for target, temporary in staged:
            os.replace(temporary, target)
    finally:
        for _target, temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def run(config: TopConfig) -> SelectedResult:
    source = read_image(config.image_path, ImageReadConfig(config.limits.max_pixels))
    quantization = quantize_to_palette(
        source,
        config.palette,
        config.brightness_search.min_scale,
        config.brightness_search.max_scale,
        config.brightness_search.steps,
        fixed_scale=config.brightness_scale,
    )
    print(
        "Wool quantization: brightness_scale={:.6f}, backend={}, evaluated_scales={}".format(
            quantization.brightness_scale,
            quantization.backend,
            quantization.searched_scales,
        )
    )
    image = quantization.image
    integral = IntegralImage(image)
    candidates = cluster_quantized_pixels(
        width=image.width,
        height=image.height,
        palette=config.palette,
        pixel_indices=quantization.indices,
        integral=integral,
    )
    palette_map: Dict[str, PaletteEntry] = {entry.block_id: entry for entry in config.palette}
    selected = select_candidate(
        candidates=candidates,
        palette=palette_map,
        integral=integral,
        lambda_value=config.lambda_value,
        c_fill=config.c_fill,
        c_setb=config.c_setb,
        max_fill_blocks=config.limits.max_fill_blocks,
        max_commands=config.limits.max_commands,
        initial_background_block=config.initial_background_block,
    )

    target_grid = _grid_from_candidate(
        selected.candidate, image.width, image.height, config.palette
    )
    plan_grid = _grid_from_plan(
        selected.plan.operations, image.width, image.height, config.palette
    )
    if target_grid != plan_grid:
        raise TOPError("selected drawing plan does not reproduce the selected partition")
    reconstructed = reconstruct_candidate(
        selected.candidate, image.width, image.height, palette_map
    )
    if _raster_from_index_grid(plan_grid, config.palette) != reconstructed:
        raise TOPError("drawing plan, partition decode, and reconstructed RGB raster differ")
    if selected.distortion != sse_candidate(selected.candidate, palette_map, integral):
        raise TOPError("selected D does not match the decoded partition")
    if selected.distortion != quantization.distortion:
        raise TOPError("quadtree partition does not preserve the wool quantization SSE")

    command_lines = _serialize_operations(selected.plan.operations, image, config)
    if len(command_lines) != selected.plan.n_total:
        raise TOPError("serialized command count does not match the drawing plan")
    summary = _summary(
        config, image, quantization, candidates, selected, command_lines
    )
    command_text = "\n".join(command_lines) + "\n"
    plt_text = None
    if config.plt_path is not None:
        stream_score = {
            "D": selected.distortion,
            "R": selected.rate,
            "J": selected.score,
            "N_fill": selected.plan.n_fill,
            "N_setb": selected.plan.n_setb,
            "N_total": selected.plan.n_total,
            "plan": selected.plan.name,
            "lambda": config.lambda_value,
            "C_fill": config.c_fill,
            "C_setb": config.c_setb,
            "brightness_scale": quantization.brightness_scale,
            "quantization_backend": quantization.backend,
            "searched_scales": quantization.searched_scales,
            "quantization_sse": quantization.distortion,
        }
        plt_text = dump_stream(create_stream(
            image, selected.candidate, selected.plan, config.palette, config.mapping,
            stream_score, config.limits, config.initial_background_block,
        ))
    print(
        "PLOT_INTERFACE bridge options: --max-blocks {} --max-commands {} (0 means unlimited)".format(
            config.limits.max_fill_blocks, config.limits.max_commands
        )
    )
    _write_outputs(
        config, command_text, summary if config.summary_path else None, plt_text
    )
    return selected


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a BMP or PNG into ordered Minecraft Java SETB/FILL instructions."
    )
    parser.add_argument("config", type=Path, help="strict JSON configuration file")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        selected = run(config)
    except (
        ConfigurationError,
        ImageReadError,
        DivisionError,
        SSEError,
        DrawPlanError,
        RDOError,
        TOPError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Wrote {selected.plan.n_total} commands "
        f"(FILL={selected.plan.n_fill}, SETB={selected.plan.n_setb}); "
        f"D={selected.distortion}, R={selected.rate:g}, J={selected.score:g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

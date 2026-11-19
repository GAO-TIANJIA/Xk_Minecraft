#!/usr/bin/env python3
"""Compile SETB/FILL instructions into a vanilla Java 26.3 data-pack function."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


DATAPACK_FORMAT = 121
DEFAULT_MAX_BLOCKS = 32768
DEFAULT_MAX_COMMANDS = 65536
MAX_WORLD_COORD = 30_000_000
INTEGER = re.compile(r"^-?\d+$")
BLOCK_STATE = re.compile(
    r"^(?:[a-z0-9_.-]+:)?[a-z0-9_./-]+(?:\[[a-z0-9_.,=:+/\-]+\])?$"
)
MARKER_NAME = ".plot_interface_generated"


@dataclass(frozen=True)
class Instruction:
    line_number: int
    kind: str
    command: str
    block_count: int


class InputError(ValueError):
    pass


def _integer(value: str, label: str, line_number: int) -> int:
    if not INTEGER.fullmatch(value):
        raise InputError(f"line {line_number}: {label} must be an absolute integer, got {value!r}")
    result = int(value)
    if abs(result) > MAX_WORLD_COORD:
        raise InputError(f"line {line_number}: {label} exceeds the world coordinate range")
    return result


def _block(value: str, line_number: int) -> str:
    if not BLOCK_STATE.fullmatch(value):
        raise InputError(
            f"line {line_number}: expected a Java 26.3 block name/state, got {value!r}"
        )
    if ":" not in value:
        value = "minecraft:" + value
    return value


def _split_tokens(content: str) -> List[str]:
    """Split fields on whitespace/commas, preserving commas in block states."""
    tokens: List[str] = []
    current: List[str] = []
    bracket_depth = 0
    for char in content:
        if char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth:
            bracket_depth -= 1
        if (char.isspace() or char == ",") and bracket_depth == 0:
            if current:
                tokens.append("".join(current))
                current.clear()
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _parse_instruction(raw_line: str, line_number: int, max_blocks: int) -> Optional[Instruction]:
    content = raw_line.split("#", 1)[0].split("//", 1)[0].strip()
    if not content:
        return None
    tokens = _split_tokens(content)
    kind = tokens[0].upper()

    if kind == "SETB":
        if len(tokens) != 5:
            raise InputError(f"line {line_number}: expected SETB x y z block")
        x, y, z = (
            _integer(tokens[1], "x", line_number),
            _integer(tokens[2], "y", line_number),
            _integer(tokens[3], "z", line_number),
        )
        block = _block(tokens[4], line_number)
        return Instruction(line_number, kind, f"setblock {x} {y} {z} {block}", 1)

    if kind == "FILL":
        if len(tokens) != 8:
            raise InputError(f"line {line_number}: expected FILL x1 y1 z1, x2 y2 z2 block")
        coords = [_integer(tokens[i], f"coordinate {i}", line_number) for i in range(1, 7)]
        block = _block(tokens[7], line_number)
        volume = (
            (abs(coords[3] - coords[0]) + 1)
            * (abs(coords[4] - coords[1]) + 1)
            * (abs(coords[5] - coords[2]) + 1)
        )
        if max_blocks and volume > max_blocks:
            raise InputError(
                f"line {line_number}: FILL covers {volume:,} blocks, above the configured limit "
                f"of {max_blocks:,}; raise --max-blocks to allow it"
            )
        command = "fill " + " ".join(str(value) for value in coords) + f" {block}"
        return Instruction(line_number, kind, command, volume)

    if kind == "PLOT":
        raise InputError(f"line {line_number}: use SETB or FILL instead of PLOT")
    raise InputError(f"line {line_number}: unknown instruction {tokens[0]!r}; expected SETB or FILL")


def read_instructions(path: Path, max_blocks: int, max_commands: int) -> List[Instruction]:
    try:
        with path.open("r", encoding="utf-8-sig") as instruction_file:
            instructions: List[Instruction] = []
            for line_number, raw_line in enumerate(instruction_file, start=1):
                instruction = _parse_instruction(raw_line, line_number, max_blocks)
                if instruction is not None:
                    instructions.append(instruction)
                    if max_commands and len(instructions) > max_commands:
                        raise InputError(
                            f"instruction file exceeds the configured {max_commands:,} command limit"
                        )
    except OSError as exc:
        raise InputError(f"cannot read instruction file {path}: {exc}") from exc
    if not instructions:
        raise InputError(f"instruction file {path} contains no SETB/FILL records")
    return instructions


def _write_atomic(path: Path, content: str) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temp_path, path)


def install_datapack(world_dir: Path, instructions: List[Instruction]) -> Path:
    world_dir = world_dir.expanduser().resolve()
    if not world_dir.is_dir() or not (world_dir / "level.dat").is_file():
        raise InputError(f"world directory must contain level.dat: {world_dir}")

    pack_dir = world_dir / "datapacks" / "plot_interface"
    marker = pack_dir / MARKER_NAME
    if pack_dir.exists() and not marker.is_file():
        raise InputError(
            f"refusing to overwrite an existing non-generated data pack: {pack_dir}"
        )

    function_dir = pack_dir / "data" / "plot_interface" / "function"
    function_dir.mkdir(parents=True, exist_ok=True)

    pack_meta = {
        "pack": {
            "description": "Plot Interface command batch",
            "min_format": [DATAPACK_FORMAT, 0],
            "max_format": DATAPACK_FORMAT,
        }
    }
    function_text = "# Generated by plot_batch.py; edit the source instruction file instead.\n"
    function_text += "\n".join(item.command for item in instructions) + "\n"

    _write_atomic(pack_dir / "pack.mcmeta", json.dumps(pack_meta, ensure_ascii=False, indent=2) + "\n")
    _write_atomic(function_dir / "run.mcfunction", function_text)
    marker.write_text("Generated by plot_batch.py. Safe to remove this data pack folder.\n", encoding="utf-8")
    return pack_dir


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile SETB/FILL records into a vanilla Minecraft Java 26.3 data pack."
    )
    parser.add_argument("file", type=Path, help="instruction file, read from first line through EOF")
    parser.add_argument("--world-dir", type=Path, required=True, help="single-player save folder containing level.dat")
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=DEFAULT_MAX_BLOCKS,
        help=f"maximum blocks in one FILL (default: {DEFAULT_MAX_BLOCKS}; 0 disables this client-side cap)",
    )
    parser.add_argument(
        "--max-commands",
        type=int,
        default=DEFAULT_MAX_COMMANDS,
        help=f"maximum commands in one function (default: {DEFAULT_MAX_COMMANDS}; 0 disables this cap)",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and print generated commands without writing the world")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.max_blocks < 0 or args.max_commands < 0:
        print("error: command limits must be zero or greater", file=sys.stderr)
        return 2
    try:
        instructions = read_instructions(args.file, args.max_blocks, args.max_commands)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    total_blocks = sum(item.block_count for item in instructions)
    print(f"Loaded {len(instructions)} instructions ({total_blocks:,} affected blocks) from {args.file}.")
    if args.dry_run:
        for item in instructions:
            print(f"line {item.line_number}: {item.command}")
        return 0

    try:
        pack_dir = install_datapack(args.world_dir, instructions)
    except (InputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Installed/updated data pack: {pack_dir}")
    print("In the open single-player world, run: /reload")
    print("Then run: /function plot_interface:run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

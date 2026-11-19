"""Encoder/decoder CLI for the versioned PLT JSON stream."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from PLT.READ_SOURCE import BMPReadError, write_bmp
from PLT.TOP.configuration import ConfigurationError, load_config
from PLT.TOP.plt_top import run
from PLT.bitstream import BitstreamError, commands_text, decode_stream


def _stage_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return Path(temp_name)


def _stage_bmp(path: Path, image) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        write_bmp(temp_name, image)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return Path(temp_name)


def _commit(staged: Sequence[tuple[Path, Path]]) -> None:
    try:
        for destination, temporary in staged:
            os.replace(temporary, destination)
    finally:
        for _destination, temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _decode(stream_path: Path, max_pixels: int, output_bmp: Optional[Path],
            command_path: Optional[Path]) -> None:
    if output_bmp is None and command_path is None:
        raise BitstreamError("choose --output-bmp, --commands, or both")
    source = stream_path.expanduser().resolve()
    bmp_path = output_bmp.expanduser().resolve() if output_bmp else None
    commands_path = command_path.expanduser().resolve() if command_path else None
    targets = [path for path in (bmp_path, commands_path) if path is not None]
    if len(set(targets)) != len(targets) or source in targets:
        raise BitstreamError("decode output paths must be distinct from each other and the input stream")

    decoded = decode_stream(source, max_pixels)
    staged = []
    try:
        if bmp_path is not None:
            staged.append((bmp_path, _stage_bmp(bmp_path, decoded.image)))
        if commands_path is not None:
            staged.append((commands_path, _stage_text(commands_path, commands_text(decoded))))
        _commit(staged)
    except Exception:
        for _destination, temporary in staged:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PLT block codec encoder and decoder")
    commands = parser.add_subparsers(dest="action", required=True)
    encoder = commands.add_parser("encode", help="encode a BMP or PNG using TOP configuration")
    encoder.add_argument("config", type=Path, help="TOP JSON configuration (set optional plt output path)")
    decoder = commands.add_parser("decode", help="decode a .plt.json file")
    decoder.add_argument("stream", type=Path, help="versioned PLT JSON stream")
    decoder.add_argument("--max-pixels", type=int, required=True,
                         help="required decoded image allocation limit")
    decoder.add_argument("--output-bmp", type=Path, help="write reconstructed 24-bit RGB BMP")
    decoder.add_argument("--commands", type=Path, help="write ordered SETB/FILL instructions")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "encode":
            config = load_config(args.config)
            if config.plt_path is None:
                raise ConfigurationError("set optional 'plt' output path to write a decodable PLT stream")
            selected = run(config)
            print("PLT stream: {}".format(config.plt_path))
            print("Draw instructions: {}".format(config.output_path))
            if config.summary_path:
                print("RDO summary: {}".format(config.summary_path))
            print("D={}, R={}, J={}".format(selected.distortion, selected.rate, selected.score))
            return 0
        if args.max_pixels <= 0:
            raise BitstreamError("--max-pixels must be positive")
        _decode(args.stream, args.max_pixels, args.output_bmp, args.commands)
        if args.output_bmp:
            print("Reconstructed BMP: {}".format(args.output_bmp.resolve()))
        if args.commands:
            print("Draw instructions: {}".format(args.commands.resolve()))
        return 0
    except (ConfigurationError, BMPReadError, BitstreamError, OSError, ValueError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

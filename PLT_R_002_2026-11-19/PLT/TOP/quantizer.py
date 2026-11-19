"""GPU-accelerated wool palette quantization and global brightness search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

from PLT.model import PaletteEntry, RGBImage


@dataclass(frozen=True)
class QuantizationResult:
    image: RGBImage
    indices: np.ndarray
    brightness_scale: float
    distortion: int
    backend: str
    searched_scales: int


def _cupy_backend():
    """Return CuPy when its CUDA runtime can see at least one GPU."""
    try:
        import cupy as cp
        return cp if cp.cuda.runtime.getDeviceCount() > 0 else None
    except Exception:
        return None


def _score_scales(xp, pixels, palette, scales: np.ndarray) -> np.ndarray:
    totals = np.zeros(len(scales), dtype=np.int64)
    scale_batch_size = 8
    pixel_batch_size = 4096
    for scale_start in range(0, len(scales), scale_batch_size):
        scale_batch = xp.asarray(
            scales[scale_start : scale_start + scale_batch_size], dtype=xp.float64
        )
        batch_totals = xp.zeros(len(scale_batch), dtype=xp.int64)
        for pixel_start in range(0, pixels.shape[0], pixel_batch_size):
            pixel_batch = pixels[pixel_start : pixel_start + pixel_batch_size]
            adjusted = xp.floor(
                pixel_batch[None, :, :] * scale_batch[:, None, None] + 0.5
            )
            adjusted = xp.clip(adjusted, 0, 255).astype(xp.int32)
            delta = adjusted[:, :, None, :] - palette[None, None, :, :]
            distances = xp.sum(delta * delta, axis=3)
            labels = xp.argmin(distances, axis=2)
            wool_rgb = palette[labels]
            # Brightness chooses a palette label; fidelity is always measured
            # against the unscaled source so dimming cannot win by itself.
            original = pixel_batch.astype(xp.int32, copy=False)
            output_delta = original[None, :, :] - wool_rgb
            output_error = xp.sum(output_delta * output_delta, axis=2)
            batch_totals += xp.sum(output_error, axis=1, dtype=xp.int64)
        totals[scale_start : scale_start + len(scale_batch)] = _to_numpy(xp, batch_totals)
    return totals


def _assign_indices(xp, pixels, palette, scale: float) -> np.ndarray:
    labels = np.empty(pixels.shape[0], dtype=np.uint16)
    scale_value = xp.asarray(scale, dtype=xp.float64)
    pixel_batch_size = 8192
    for start in range(0, pixels.shape[0], pixel_batch_size):
        pixel_batch = pixels[start : start + pixel_batch_size]
        adjusted = xp.floor(pixel_batch * scale_value + 0.5)
        adjusted = xp.clip(adjusted, 0, 255).astype(xp.int32)
        delta = adjusted[:, None, :] - palette[None, :, :]
        distances = xp.sum(delta * delta, axis=2)
        closest = xp.argmin(distances, axis=1)
        labels[start : start + len(pixel_batch)] = _to_numpy(xp, closest).astype(np.uint16)
    return labels


def _to_numpy(xp, values) -> np.ndarray:
    return xp.asnumpy(values) if xp is not np else np.asarray(values)


def quantize_to_palette(
    image: RGBImage,
    palette_entries: Sequence[PaletteEntry],
    min_scale: float,
    max_scale: float,
    steps: int,
    fixed_scale: Optional[float] = None,
) -> QuantizationResult:
    """Choose a globally best brightness on a grid, then assign each pixel.

    The scale-adjusted source chooses each pixel's nearest wool label. The
    objective is then measured from the unscaled source RGB to those selected
    wool colors. Automatic mode checks every point in the inclusive, uniform
    scale grid. Ties prefer a scale closest to 1.0, then the lower scale.
    """
    if not palette_entries:
        raise ValueError("palette must contain at least one entry")
    if len(palette_entries) > np.iinfo(np.uint16).max + 1:
        raise ValueError("palette has too many entries for the quantized index format")
    if steps < 2 or min_scale < 0 or max_scale <= min_scale:
        raise ValueError("invalid brightness search range")
    if fixed_scale is not None and (
        not np.isfinite(fixed_scale) or fixed_scale < 0 or fixed_scale > 4
    ):
        raise ValueError("fixed brightness scale must be between 0 and 4")
    palette_rgb = np.asarray([entry.rgb for entry in palette_entries], dtype=np.int32)
    raw_pixels = np.frombuffer(image.pixels, dtype=np.uint8).reshape(-1, 3)
    def run_backend(xp):
        pixels = xp.asarray(raw_pixels, dtype=xp.float64)
        palette = xp.asarray(palette_rgb, dtype=xp.int32)
        if fixed_scale is None:
            scales = np.linspace(min_scale, max_scale, steps, dtype=np.float64)
            scores = _score_scales(xp, pixels, palette, scales)
            best_score = int(scores.min())
            tied = np.flatnonzero(scores == best_score)
            best_index = min(
                tied,
                key=lambda index: (abs(float(scales[index]) - 1.0), float(scales[index])),
            )
            selected_scale = float(scales[best_index])
            searched_scales = len(scales)
            distortion = best_score
        else:
            selected_scale = float(fixed_scale)
            searched_scales = 1
            one_score = _score_scales(
                xp, pixels, palette, np.asarray([selected_scale], dtype=np.float64)
            )
            distortion = int(one_score[0])
        indices = _assign_indices(xp, pixels, palette, selected_scale)
        return indices, selected_scale, searched_scales, distortion

    cp = _cupy_backend()
    if cp is not None:
        # If a GPU is visible, keep the computation on CuPy. Runtime failures
        # must surface instead of silently moving this workload to the CPU.
        indices, selected_scale, searched_scales, distortion = run_backend(cp)
        backend = "cupy"
    else:
        indices, selected_scale, searched_scales, distortion = run_backend(np)
        backend = "numpy"
    return QuantizationResult(
        image=image,
        indices=indices.reshape(image.height, image.width),
        brightness_scale=selected_scale,
        distortion=distortion,
        backend=backend,
        searched_scales=searched_scales,
    )

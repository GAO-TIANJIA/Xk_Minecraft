"""Bottom-up quadtree clustering of an already wool-quantized image."""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from PLT.D import IntegralImage
from PLT.model import Candidate, PaletteEntry, Rect


class DivisionError(ValueError):
    """Raised when quantized pixel labels cannot form a valid partition."""


def cluster_quantized_pixels(
    width: int,
    height: int,
    palette: Sequence[PaletteEntry],
    pixel_indices: np.ndarray,
    integral: IntegralImage,
) -> Tuple[Candidate, ...]:
    """Cluster equal wool labels from unit pixels upward through a quadtree.

    The label plane is placed at the top-left of a power-of-two rectangle.
    Pixels outside the image are sentinel nodes and are never emitted or
    merged. Each level merges two children along a remaining single axis, or
    four children when both axes remain; the tree ends at unit pixels. Maximal
    uniform nodes become the exact, nonoverlapping partition.
    """
    if width != integral.width or height != integral.height:
        raise DivisionError("integral image dimensions do not match requested dimensions")
    if not palette:
        raise DivisionError("palette must contain at least one entry")
    if any(not isinstance(entry, PaletteEntry) for entry in palette):
        raise DivisionError("palette must contain PLT.model.PaletteEntry values")
    block_ids = [entry.block_id for entry in palette]
    if len(set(block_ids)) != len(block_ids):
        raise DivisionError("palette block IDs must be unique")

    labels = np.asarray(pixel_indices)
    if labels.shape != (height, width) or not np.issubdtype(labels.dtype, np.integer):
        raise DivisionError("pixel_indices must be an integer array with image shape")
    if labels.size == 0 or int(labels.min()) < 0 or int(labels.max()) >= len(palette):
        raise DivisionError("pixel_indices contains an unknown palette index")

    tree_width = 1 << (width - 1).bit_length()
    tree_height = 1 << (height - 1).bit_length()
    root_labels = np.full((tree_height, tree_width), -1, dtype=np.int32)
    root_labels[:height, :width] = labels.astype(np.int32, copy=False)
    uniform = root_labels >= 0
    levels = [(root_labels, uniform, 1, 1)]
    current_labels = root_labels
    current_uniform = uniform

    while current_labels.shape[1] > 1 or current_labels.shape[0] > 1:
        split_x = current_labels.shape[1] > 1
        split_y = current_labels.shape[0] > 1
        if split_x and split_y:
            child_labels = (
                current_labels[0::2, 0::2],
                current_labels[0::2, 1::2],
                current_labels[1::2, 0::2],
                current_labels[1::2, 1::2],
            )
            child_uniform = (
                current_uniform[0::2, 0::2],
                current_uniform[0::2, 1::2],
                current_uniform[1::2, 0::2],
                current_uniform[1::2, 1::2],
            )
        elif split_x:
            child_labels = (current_labels[:, 0::2], current_labels[:, 1::2])
            child_uniform = (current_uniform[:, 0::2], current_uniform[:, 1::2])
        else:
            child_labels = (current_labels[0::2, :], current_labels[1::2, :])
            child_uniform = (current_uniform[0::2, :], current_uniform[1::2, :])

        base = child_labels[0]
        merged = child_uniform[0].copy()
        for child_label, child_mask in zip(child_labels[1:], child_uniform[1:]):
            merged &= child_mask & (base == child_label)
        current_labels = np.where(merged, base, -1).astype(np.int32, copy=False)
        current_uniform = merged
        previous_node_width = levels[-1][2]
        previous_node_height = levels[-1][3]
        levels.append(
            (
                current_labels,
                current_uniform,
                previous_node_width * (2 if split_x else 1),
                previous_node_height * (2 if split_y else 1),
            )
        )

    rects = []
    for level, (node_labels, node_uniform, node_width, node_height) in enumerate(levels):
        if level == len(levels) - 1:
            emit = node_uniform
        else:
            parent_uniform = levels[level + 1][1]
            factor_x = node_labels.shape[1] // parent_uniform.shape[1]
            factor_y = node_labels.shape[0] // parent_uniform.shape[0]
            covered_by_parent = np.repeat(
                np.repeat(parent_uniform, factor_y, axis=0), factor_x, axis=1
            )
            emit = node_uniform & ~covered_by_parent
        ys, xs = np.nonzero(emit)
        for y, x in zip(ys.tolist(), xs.tolist()):
            palette_index = int(node_labels[y, x])
            rects.append(
                Rect(
                    x=x * node_width,
                    y=y * node_height,
                    width=node_width,
                    height=node_height,
                    block_id=palette[palette_index].block_id,
                )
            )

    if not rects:
        raise DivisionError("quadtree produced an empty image partition")
    rects.sort(key=lambda r: (r.y, r.x, r.height, r.width, r.block_id))
    palette_by_id = {entry.block_id: entry for entry in palette}
    distortion = sum(
        integral.sse_for_color(
            rect.x,
            rect.y,
            rect.width,
            rect.height,
            palette_by_id[rect.block_id].rgb,
        )
        for rect in rects
    )
    return (Candidate(tuple(rects), distortion),)

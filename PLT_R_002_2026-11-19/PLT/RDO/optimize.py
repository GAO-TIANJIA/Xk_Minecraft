"""Deterministic J = D + lambda * R candidate and plan selection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple
from typing import Optional

from PLT.D import IntegralImage, SSEError, sse_candidate
from PLT.R import DrawPlanError, generate_plans
from PLT.model import Candidate, DrawPlan, PaletteEntry


class RDOError(ValueError):
    """Raised when the RDO inputs cannot produce a scored plan."""


@dataclass(frozen=True)
class SelectedResult:
    candidate: Candidate
    plan: DrawPlan
    distortion: int
    rate: float
    score: float
    candidate_count: int
    evaluated_plan_count: int


def _candidate_signature(candidate: Candidate) -> tuple:
    return tuple(
        (rect.y, rect.x, rect.height, rect.width, rect.block_id)
        for rect in sorted(
            candidate.rects,
            key=lambda item: (item.y, item.x, item.height, item.width, item.block_id),
        )
    )


def select_candidate(
    candidates: Sequence[Candidate],
    palette: Mapping[str, PaletteEntry],
    integral: IntegralImage,
    lambda_value: float,
    c_fill: float,
    c_setb: float,
    max_fill_blocks: int,
    max_commands: int,
    initial_background_block: Optional[str] = None,
) -> SelectedResult:
    """Choose the lowest-scoring valid candidate/plan pair.

    Equal scores are resolved by D, R, command count, geometry, and plan name,
    in that order, so runs with identical inputs are reproducible.
    """
    if isinstance(lambda_value, bool) or not isinstance(lambda_value, (int, float)):
        raise RDOError("lambda must be a finite nonnegative number")
    try:
        lambda_value = float(lambda_value)
    except OverflowError as exc:
        raise RDOError("lambda must be a finite nonnegative number") from exc
    if not math.isfinite(lambda_value) or lambda_value < 0:
        raise RDOError("lambda must be a finite nonnegative number")
    if not candidates:
        raise RDOError("DIV returned no partition candidates")

    evaluated = []
    plan_count = 0
    plan_errors = []
    for candidate in candidates:
        try:
            distortion = sse_candidate(candidate, palette, integral)
            plans = generate_plans(
                candidate, c_fill, c_setb, max_fill_blocks, max_commands,
                initial_background_block=initial_background_block,
                canvas_width=integral.width,
                canvas_height=integral.height,
            )
        except (SSEError, DrawPlanError) as exc:
            plan_errors.append(str(exc))
            continue
        for plan in plans:
            plan_count += 1
            rate = plan.cost
            score = distortion + lambda_value * rate
            if not math.isfinite(rate) or not math.isfinite(score):
                raise RDOError("R or J overflowed the supported numeric range")
            evaluated.append((
                score,
                distortion,
                rate,
                plan.n_total,
                _candidate_signature(candidate),
                plan.name,
                candidate,
                plan,
            ))

    if not evaluated:
        detail = plan_errors[-1] if plan_errors else "no candidate/plan pair was available"
        raise RDOError(f"no valid drawing plan was produced: {detail}")
    best = min(evaluated, key=lambda item: item[:6])
    return SelectedResult(
        candidate=best[6],
        plan=best[7],
        distortion=best[1],
        rate=best[2],
        score=best[0],
        candidate_count=len(candidates),
        evaluated_plan_count=plan_count,
    )

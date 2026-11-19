"""CPU reference RDO scheduler for the PLT block codec.

DIV, D, and R are deliberately injected through small protocols.  This module
owns candidate orchestration, validation, J = D + lambda * R ranking, and the
stable tie break; it does not implement segmentation, RGB SSE, or draw-cost
generation itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from enum import Enum
from itertools import islice
from typing import Dict, Iterable, Iterator, Mapping, Optional, Protocol, Sequence, Tuple, Union


Number = Union[int, float, Decimal]
RGB = Tuple[int, int, int]


class RdoError(ValueError):
    """Base class for invalid RDO inputs or module results."""


class RdoConfigurationError(RdoError):
    """A required RDO setting is missing or invalid."""


class RdoInputError(RdoError):
    """An image, palette, candidate, or draw plan is invalid."""


class RdoModuleError(RdoError):
    """A DIV, D, or R adapter failed or returned an invalid result."""


class NoCandidatesError(RdoError):
    """DIV produced no candidates within the configured limit."""


class NoPlansError(RdoError):
    """R produced no usable draw plan for any candidate."""


def _decimal(value: Number, name: str, *, nonnegative: bool = True) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise RdoConfigurationError("{} must be a finite numeric value".format(name))
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RdoConfigurationError("{} must be a finite numeric value".format(name))
    if not result.is_finite():
        raise RdoConfigurationError("{} must be finite".format(name))
    if nonnegative and result < 0:
        raise RdoConfigurationError("{} must be non-negative".format(name))
    return result


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RdoInputError("{} must be an integer >= {}".format(name, minimum))
    return value


def _config_integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RdoConfigurationError("{} must be an integer >= {}".format(name, minimum))
    return value


def _rgb(value: Sequence[int], name: str) -> RGB:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise RdoInputError("{} must contain exactly three 8-bit channels".format(name))
    channels = tuple(value)
    if any(isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255
           for channel in channels):
        raise RdoInputError("{} channels must be integers in [0, 255]".format(name))
    return channels  # type: ignore[return-value]


@dataclass(frozen=True)
class Raster:
    """Canonical top-left, row-major RGB raster used at the RDO boundary."""

    width: int
    height: int
    pixels: Tuple[RGB, ...]

    def __post_init__(self) -> None:
        _integer(self.width, "image width", minimum=1)
        _integer(self.height, "image height", minimum=1)
        normalized = tuple(_rgb(pixel, "image pixel") for pixel in self.pixels)
        if len(normalized) != self.width * self.height:
            raise RdoInputError("pixel count does not match image width * height")
        object.__setattr__(self, "pixels", normalized)


@dataclass(frozen=True)
class PaletteEntry:
    block_id: str
    rgb: RGB

    def __post_init__(self) -> None:
        if not isinstance(self.block_id, str) or not self.block_id.strip():
            raise RdoInputError("palette block_id must be a non-empty string")
        object.__setattr__(self, "rgb", _rgb(self.rgb, "palette RGB"))


@dataclass(frozen=True)
class Rect:
    """Zero-origin, half-open rectangle (x, y, width, height)."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        _integer(self.x, "rectangle x")
        _integer(self.y, "rectangle y")
        _integer(self.width, "rectangle width", minimum=1)
        _integer(self.height, "rectangle height", minimum=1)

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class Segment:
    rect: Rect
    block_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.rect, Rect):
            raise RdoInputError("segment rect must be a Rect")
        if not isinstance(self.block_id, str) or not self.block_id.strip():
            raise RdoInputError("segment block_id must be a non-empty string")


@dataclass(frozen=True)
class SegmentationCandidate:
    segments: Tuple[Segment, ...]
    candidate_id: Optional[Union[str, int]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "segments", tuple(self.segments))
        if self.candidate_id is not None and (
            isinstance(self.candidate_id, bool)
            or not isinstance(self.candidate_id, (str, int))
        ):
            raise RdoInputError("candidate_id must be a string, integer, or None")


class DrawOpKind(str, Enum):
    FILL = "FILL"
    SETB = "SETB"


@dataclass(frozen=True)
class DrawOp:
    """One ordered PLT draw operation in internal image coordinates."""

    kind: DrawOpKind
    block_id: str
    rect: Optional[Rect] = None
    x: Optional[int] = None
    y: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DrawOpKind):
            try:
                object.__setattr__(self, "kind", DrawOpKind(self.kind))
            except (TypeError, ValueError):
                raise RdoInputError("draw operation kind must be FILL or SETB")
        if not isinstance(self.block_id, str) or not self.block_id.strip():
            raise RdoInputError("draw operation block_id must be a non-empty string")
        if self.kind is DrawOpKind.FILL:
            if not isinstance(self.rect, Rect) or self.x is not None or self.y is not None:
                raise RdoInputError("FILL requires rect and must not contain point coordinates")
        else:
            if self.rect is not None or self.x is None or self.y is None:
                raise RdoInputError("SETB requires x/y and must not contain a rectangle")
            _integer(self.x, "SETB x")
            _integer(self.y, "SETB y")

    @classmethod
    def fill(cls, rect: Rect, block_id: str) -> "DrawOp":
        return cls(DrawOpKind.FILL, block_id, rect=rect)

    @classmethod
    def setb(cls, x: int, y: int, block_id: str) -> "DrawOp":
        return cls(DrawOpKind.SETB, block_id, x=x, y=y)


@dataclass(frozen=True)
class DrawPlan:
    """Ordered operations; order is preserved exactly as returned by R."""

    operations: Tuple[DrawOp, ...]
    plan_id: Optional[Union[str, int]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operations", tuple(self.operations))
        if self.plan_id is not None and (
            isinstance(self.plan_id, bool) or not isinstance(self.plan_id, (str, int))
        ):
            raise RdoInputError("plan_id must be a string, integer, or None")


@dataclass(frozen=True)
class RateBreakdown:
    """R module's cost and operation counts for one draw plan."""

    n_fill: int
    n_setb: int
    rate: Decimal

    def __post_init__(self) -> None:
        _integer(self.n_fill, "N_fill")
        _integer(self.n_setb, "N_setb")
        try:
            rate = _decimal(self.rate, "R")
        except RdoConfigurationError as error:
            raise RdoModuleError("R must be finite and non-negative: {}".format(error))
        object.__setattr__(self, "rate", rate)


class TieBreakRule(str, Enum):
    FIRST = "first"
    LOWER_RATE = "lower_rate"
    FEWER_OPERATIONS = "fewer_operations"
    LOWER_DISTORTION = "lower_distortion"


@dataclass(frozen=True)
class RdoConfig:
    """All scoring and search limits are explicit; costs and lambda have no defaults."""

    lambda_weight: Decimal
    c_fill: Decimal
    c_setb: Decimal
    max_depth: int
    max_candidates: int
    max_plans_per_candidate: int
    tie_break: TieBreakRule = TieBreakRule.FIRST

    def __post_init__(self) -> None:
        object.__setattr__(self, "lambda_weight", _decimal(self.lambda_weight, "lambda"))
        object.__setattr__(self, "c_fill", _decimal(self.c_fill, "C_fill"))
        object.__setattr__(self, "c_setb", _decimal(self.c_setb, "C_setb"))
        _config_integer(self.max_depth, "max_depth")
        _config_integer(self.max_candidates, "max_candidates", minimum=1)
        _config_integer(self.max_plans_per_candidate, "max_plans_per_candidate", minimum=1)
        if not isinstance(self.tie_break, TieBreakRule):
            try:
                object.__setattr__(self, "tie_break", TieBreakRule(self.tie_break))
            except (TypeError, ValueError):
                raise RdoConfigurationError(
                    "tie_break must be one of: {}".format(", ".join(rule.value for rule in TieBreakRule))
                )

    def summary(self) -> Dict[str, Union[str, int]]:
        return {
            "lambda": str(self.lambda_weight),
            "C_fill": str(self.c_fill),
            "C_setb": str(self.c_setb),
            "max_depth": self.max_depth,
            "max_candidates": self.max_candidates,
            "max_plans_per_candidate": self.max_plans_per_candidate,
            "tie_break": self.tie_break.value,
        }


class DivModule(Protocol):
    def generate_candidates(
        self,
        image: Raster,
        palette: Tuple[PaletteEntry, ...],
        *,
        max_depth: int,
        max_candidates: int,
    ) -> Iterable[SegmentationCandidate]: ...


class DModule(Protocol):
    def rgb_sse(
        self,
        image: Raster,
        candidate: SegmentationCandidate,
        palette: Tuple[PaletteEntry, ...],
    ) -> int: ...


class RModule(Protocol):
    def generate_plans(
        self, candidate: SegmentationCandidate, *, max_plans: int
    ) -> Iterable[DrawPlan]: ...

    def evaluate_cost(
        self,
        plan: DrawPlan,
        *,
        c_fill: Decimal,
        c_setb: Decimal,
    ) -> RateBreakdown: ...


@dataclass(frozen=True)
class CandidateScore:
    candidate_index: int
    plan_index: int
    candidate: SegmentationCandidate
    plan: DrawPlan
    distortion: int
    rate: Decimal
    objective: Decimal
    n_fill: int
    n_setb: int

    @property
    def n_operations(self) -> int:
        return self.n_fill + self.n_setb


@dataclass(frozen=True)
class Reconstruction:
    """Lazy reconstructed raster backed by a validated rectangular partition."""

    width: int
    height: int
    candidate: SegmentationCandidate
    palette: Tuple[PaletteEntry, ...]

    def _palette_map(self) -> Mapping[str, RGB]:
        return {entry.block_id: entry.rgb for entry in self.palette}

    def block_id_at(self, x: int, y: int) -> str:
        _integer(x, "pixel x")
        _integer(y, "pixel y")
        if x >= self.width or y >= self.height:
            raise IndexError("pixel coordinate is outside the reconstructed image")
        for segment in self.candidate.segments:
            rect = segment.rect
            if rect.x <= x < rect.x2 and rect.y <= y < rect.y2:
                return segment.block_id
        raise RdoInputError("validated candidate unexpectedly leaves an uncovered pixel")

    def rgb_at(self, x: int, y: int) -> RGB:
        block_id = self.block_id_at(x, y)
        return self._palette_map()[block_id]

    def iter_rgb_rows(self) -> Iterator[Tuple[RGB, ...]]:
        palette = self._palette_map()
        for y in range(self.height):
            row: list = [None] * self.width
            for segment in self.candidate.segments:
                rect = segment.rect
                if rect.y <= y < rect.y2:
                    row[rect.x:rect.x2] = [palette[segment.block_id]] * rect.width
            if any(pixel is None for pixel in row):
                raise RdoInputError("validated candidate unexpectedly leaves an uncovered pixel")
            yield tuple(row)


@dataclass(frozen=True)
class RdoResult:
    selected: CandidateScore
    scores: Tuple[CandidateScore, ...]
    reconstruction: Reconstruction
    config: RdoConfig

    def summary(self) -> Dict[str, Union[str, int]]:
        result: Dict[str, Union[str, int]] = self.config.summary()
        result.update(
            {
                "D": str(self.selected.distortion),
                "R": str(self.selected.rate),
                "J": str(self.selected.objective),
                "N_fill": self.selected.n_fill,
                "N_setb": self.selected.n_setb,
                "N_operations": self.selected.n_operations,
                "candidate_index": self.selected.candidate_index,
                "plan_index": self.selected.plan_index,
            }
        )
        if self.selected.candidate.candidate_id is not None:
            result["candidate_id"] = str(self.selected.candidate.candidate_id)
        if self.selected.plan.plan_id is not None:
            result["plan_id"] = str(self.selected.plan.plan_id)
        return result


class _CoverageTree:
    """Range-add/min/max tree for linear-time candidate partition validation."""

    def __init__(self, length: int) -> None:
        self.length = length
        size = max(4, 4 * length)
        self.minimum = [0] * size
        self.maximum = [0] * size
        self.lazy = [0] * size

    def _push(self, node: int) -> None:
        delta = self.lazy[node]
        if delta:
            for child in (node * 2, node * 2 + 1):
                self.minimum[child] += delta
                self.maximum[child] += delta
                self.lazy[child] += delta
            self.lazy[node] = 0

    def _add(self, node: int, left: int, right: int, ql: int, qr: int, delta: int) -> None:
        if ql <= left and right <= qr:
            self.minimum[node] += delta
            self.maximum[node] += delta
            self.lazy[node] += delta
            return
        self._push(node)
        mid = (left + right) // 2
        if ql < mid:
            self._add(node * 2, left, mid, ql, qr, delta)
        if qr > mid:
            self._add(node * 2 + 1, mid, right, ql, qr, delta)
        self.minimum[node] = min(self.minimum[node * 2], self.minimum[node * 2 + 1])
        self.maximum[node] = max(self.maximum[node * 2], self.maximum[node * 2 + 1])

    def add(self, ql: int, qr: int, delta: int) -> None:
        self._add(1, 0, self.length, ql, qr, delta)


def _validate_palette(palette: Sequence[PaletteEntry]) -> Tuple[PaletteEntry, ...]:
    try:
        entries = tuple(palette)
    except TypeError:
        raise RdoInputError("palette must be a sequence of PaletteEntry values")
    if not entries:
        raise RdoInputError("palette must not be empty")
    if any(not isinstance(entry, PaletteEntry) for entry in entries):
        raise RdoInputError("palette contains an item that is not a PaletteEntry")
    ids = [entry.block_id for entry in entries]
    if len(set(ids)) != len(ids):
        raise RdoInputError("palette contains duplicate block_id values")
    return entries


def _validate_candidate(
    candidate: SegmentationCandidate,
    image: Raster,
    palette_ids: set,
) -> None:
    if not isinstance(candidate, SegmentationCandidate):
        raise RdoModuleError("DIV returned an item that is not a SegmentationCandidate")
    if not candidate.segments:
        raise RdoInputError("candidate {} contains no rectangles".format(candidate.candidate_id))

    y_edges = {0, image.height}
    events: Dict[int, list] = {0: [], image.width: []}
    area = 0
    for segment in candidate.segments:
        if not isinstance(segment, Segment):
            raise RdoInputError("candidate contains an item that is not a Segment")
        rect = segment.rect
        if segment.block_id not in palette_ids:
            raise RdoInputError("candidate references unknown block_id {!r}".format(segment.block_id))
        if rect.x2 > image.width or rect.y2 > image.height:
            raise RdoInputError("candidate rectangle lies outside the image")
        area += rect.area
        y_edges.add(rect.y)
        y_edges.add(rect.y2)
        events.setdefault(rect.x, []).append((rect.y, rect.y2, 1))
        events.setdefault(rect.x2, []).append((rect.y, rect.y2, -1))

    if area != image.width * image.height:
        raise RdoInputError("candidate rectangles do not cover exactly the image area")

    sorted_y = sorted(y_edges)
    y_index = {coordinate: index for index, coordinate in enumerate(sorted_y)}
    tree = _CoverageTree(len(sorted_y) - 1)
    sorted_x = sorted(events)
    for index, x in enumerate(sorted_x[:-1]):
        for y0, y1, delta in events[x]:
            tree.add(y_index[y0], y_index[y1], delta)
        if sorted_x[index + 1] > x and (tree.minimum[1] != 1 or tree.maximum[1] != 1):
            raise RdoInputError("candidate rectangles overlap or leave an uncovered area")


def _validate_plan(plan: DrawPlan, image: Raster, palette_ids: set) -> Tuple[int, int]:
    if not isinstance(plan, DrawPlan):
        raise RdoModuleError("R returned an item that is not a DrawPlan")
    n_fill = 0
    n_setb = 0
    for operation in plan.operations:
        if not isinstance(operation, DrawOp):
            raise RdoInputError("draw plan contains an item that is not a DrawOp")
        if operation.block_id not in palette_ids:
            raise RdoInputError("draw plan references unknown block_id {!r}".format(operation.block_id))
        if operation.kind is DrawOpKind.FILL:
            rect = operation.rect
            if rect.x2 > image.width or rect.y2 > image.height:
                raise RdoInputError("FILL rectangle lies outside the image")
            n_fill += 1
        else:
            if operation.x >= image.width or operation.y >= image.height:
                raise RdoInputError("SETB point lies outside the image")
            n_setb += 1
    return n_fill, n_setb


def _mul_decimal(left: Decimal, right: Decimal) -> Decimal:
    precision = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
    with localcontext() as context:
        context.prec = precision
        return left * right


def _add_decimal(left: Decimal, right: Decimal) -> Decimal:
    values = [value for value in (left, right) if value]
    if not values:
        return Decimal(0)
    low = min(value.as_tuple().exponent for value in values)
    high = max(value.adjusted() for value in values)
    precision = max(28, high - low + 3)
    with localcontext() as context:
        context.prec = precision
        return left + right


def _objective(distortion: int, lambda_weight: Decimal, rate: Decimal) -> Decimal:
    weighted_rate = _mul_decimal(lambda_weight, rate)
    return _add_decimal(Decimal(distortion), weighted_rate)


def _linear_rate(n_fill: int, n_setb: int, c_fill: Decimal, c_setb: Decimal) -> Decimal:
    """Reference R contract for the current fixed per-command cost model."""
    fill_cost = _mul_decimal(Decimal(n_fill), c_fill)
    setb_cost = _mul_decimal(Decimal(n_setb), c_setb)
    return _add_decimal(fill_cost, setb_cost)


def _score_key(score: CandidateScore, rule: TieBreakRule) -> tuple:
    stable_order = (score.candidate_index, score.plan_index)
    if rule is TieBreakRule.LOWER_RATE:
        return (score.objective, score.rate, score.distortion, score.n_operations) + stable_order
    if rule is TieBreakRule.FEWER_OPERATIONS:
        return (score.objective, score.n_operations, score.rate, score.distortion) + stable_order
    if rule is TieBreakRule.LOWER_DISTORTION:
        return (score.objective, score.distortion, score.rate, score.n_operations) + stable_order
    return (score.objective,) + stable_order


def optimize(
    image: Raster,
    palette: Sequence[PaletteEntry],
    *,
    div: DivModule,
    d: DModule,
    r: RModule,
    config: RdoConfig,
) -> RdoResult:
    """Enumerate bounded DIV/R results, score them, and return the stable minimum.

    Adapter iteration order is significant only when scores remain tied and the
    configured tie break reaches its final stable-order fields.  DIV and R
    implementations should therefore produce deterministic order for identical
    inputs and settings.
    """

    if not isinstance(image, Raster):
        raise RdoInputError("image must be a Raster")
    if not isinstance(config, RdoConfig):
        raise RdoConfigurationError("config must be an RdoConfig")
    palette_entries = _validate_palette(palette)
    palette_ids = {entry.block_id for entry in palette_entries}

    try:
        candidate_stream = div.generate_candidates(
            image,
            palette_entries,
            max_depth=config.max_depth,
            max_candidates=config.max_candidates,
        )
        candidates = list(islice(iter(candidate_stream), config.max_candidates))
    except Exception as error:
        if isinstance(error, RdoError):
            raise
        raise RdoModuleError("DIV candidate generation failed: {}".format(error)) from error
    if not candidates:
        raise NoCandidatesError("DIV produced no candidates")

    scores = []
    usable_candidate_count = 0
    for candidate_index, candidate in enumerate(candidates):
        _validate_candidate(candidate, image, palette_ids)
        try:
            plan_stream = r.generate_plans(candidate, max_plans=config.max_plans_per_candidate)
            plans = list(islice(iter(plan_stream), config.max_plans_per_candidate))
        except Exception as error:
            if isinstance(error, RdoError):
                raise
            raise RdoModuleError(
                "R plan generation failed for candidate {}: {}".format(candidate_index, error)
            ) from error
        if not plans:
            continue
        usable_candidate_count += 1

        try:
            distortion = d.rgb_sse(image, candidate, palette_entries)
        except Exception as error:
            if isinstance(error, RdoError):
                raise
            raise RdoModuleError(
                "D evaluation failed for candidate {}: {}".format(candidate_index, error)
            ) from error
        if isinstance(distortion, bool) or not isinstance(distortion, int) or distortion < 0:
            raise RdoModuleError("D must be a non-negative integer RGB SSE value")

        for plan_index, plan in enumerate(plans):
            expected_fill, expected_setb = _validate_plan(plan, image, palette_ids)
            try:
                breakdown = r.evaluate_cost(
                    plan,
                    c_fill=config.c_fill,
                    c_setb=config.c_setb,
                )
            except Exception as error:
                if isinstance(error, RdoError):
                    raise
                raise RdoModuleError(
                    "R cost evaluation failed for candidate {}, plan {}: {}".format(
                        candidate_index, plan_index, error
                    )
                ) from error
            if not isinstance(breakdown, RateBreakdown):
                raise RdoModuleError("R.evaluate_cost must return a RateBreakdown")
            if (breakdown.n_fill, breakdown.n_setb) != (expected_fill, expected_setb):
                raise RdoModuleError(
                    "R operation counts do not match the returned draw plan"
                )
            expected_rate = _linear_rate(
                expected_fill, expected_setb, config.c_fill, config.c_setb
            )
            if breakdown.rate != expected_rate:
                raise RdoModuleError(
                    "R cost does not match N_fill*C_fill + N_setb*C_setb"
                )
            scores.append(
                CandidateScore(
                    candidate_index=candidate_index,
                    plan_index=plan_index,
                    candidate=candidate,
                    plan=plan,
                    distortion=distortion,
                    rate=breakdown.rate,
                    objective=_objective(distortion, config.lambda_weight, breakdown.rate),
                    n_fill=breakdown.n_fill,
                    n_setb=breakdown.n_setb,
                )
            )

    if not usable_candidate_count or not scores:
        raise NoPlansError("R produced no draw plans for the DIV candidates")

    selected = min(scores, key=lambda item: _score_key(item, config.tie_break))
    reconstruction = Reconstruction(
        width=image.width,
        height=image.height,
        candidate=selected.candidate,
        palette=palette_entries,
    )
    return RdoResult(
        selected=selected,
        scores=tuple(scores),
        reconstruction=reconstruction,
        config=config,
    )


__all__ = [
    "CandidateScore",
    "DModule",
    "DivModule",
    "DrawOp",
    "DrawOpKind",
    "DrawPlan",
    "NoCandidatesError",
    "NoPlansError",
    "PaletteEntry",
    "RateBreakdown",
    "Raster",
    "RdoConfig",
    "RdoError",
    "RdoInputError",
    "RdoModuleError",
    "RdoResult",
    "Reconstruction",
    "Rect",
    "RModule",
    "Segment",
    "SegmentationCandidate",
    "TieBreakRule",
    "optimize",
]

"""Public RDO APIs.

The TOP v1 entry point is :func:`select_candidate`.  The independent
Protocol-based implementation is explicitly named :func:`optimize_with_modules`.
"""

from .optimize import RDOError, SelectedResult, select_candidate
from .rdo import (
    CandidateScore,
    DModule,
    DivModule,
    DrawOp,
    DrawOpKind,
    DrawPlan,
    NoCandidatesError,
    NoPlansError,
    PaletteEntry,
    RateBreakdown,
    Raster,
    RdoConfig,
    RdoError,
    RdoInputError,
    RdoModuleError,
    RdoResult,
    Reconstruction,
    Rect,
    RModule,
    Segment,
    SegmentationCandidate,
    TieBreakRule,
    optimize as optimize_with_modules,
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
    "RDOError",
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
    "SelectedResult",
    "TieBreakRule",
    "optimize_with_modules",
    "select_candidate",
]

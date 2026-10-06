"""Pydantic schemas for the simplification API.

Validation is intentionally strict so that the problem statement is
enforced at the boundary:

* unknown fields are rejected;
* only genuine integers are accepted (floats, booleans and numeric
  strings are not silently coerced);
* the point count, coordinate ranges and time ordering are checked.

Both modes accept an optional directional error configuration
(``directed_error``) carrying two *positive* integer bounds:
``above`` limits samples lying above the interpolated chord and
``below`` samples lying below it.  The legacy threshold request must
use exactly one of the integer ``tolerance`` or ``directed_error``;
sending both is a 422.
"""

from __future__ import annotations

from math import gcd
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)

MIN_POINTS = 2
MAX_POINTS = 120
MIN_TIME = 0
MAX_TIME = 10**9
MAX_ABS_VALUE = 10**6
MAX_TOLERANCE = 10**6
MIN_BUDGET = 1
MAX_BUDGET = 10
MIN_DIRECTED_BOUND = 1
MAX_DIRECTED_BOUND = 10**6


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: StrictInt = Field(ge=MIN_TIME, le=MAX_TIME)
    value: StrictInt = Field(ge=-MAX_ABS_VALUE, le=MAX_ABS_VALUE)


class DirectedErrorConfig(BaseModel):
    """Optional directional bounds: deviations above / below the chord.

    Both limits are positive integers.  ``above`` adjudicates samples
    strictly above their interpolated chord, ``below`` samples strictly
    below it; points exactly on the chord consume no budget.
    """

    model_config = ConfigDict(extra="forbid")

    above: StrictInt = Field(ge=MIN_DIRECTED_BOUND, le=MAX_DIRECTED_BOUND)
    below: StrictInt = Field(ge=MIN_DIRECTED_BOUND, le=MAX_DIRECTED_BOUND)


class _StrictlyIncreasingTimesMixin:
    @model_validator(mode="after")
    def _check_strictly_increasing_times(self):
        previous = None
        for point in self.points:
            if previous is not None and point.time <= previous:
                raise ValueError(
                    "points.time must be strictly increasing"
                )
            previous = point.time
        return self


class SimplifyRequest(_StrictlyIncreasingTimesMixin, BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[Point] = Field(min_length=MIN_POINTS, max_length=MAX_POINTS)
    tolerance: StrictInt | None = Field(
        default=None, ge=0, le=MAX_TOLERANCE
    )
    directed_error: DirectedErrorConfig | None = None

    @model_validator(mode="after")
    def _check_exactly_one_error_mode(self) -> "SimplifyRequest":
        if self.tolerance is None and self.directed_error is None:
            raise ValueError(
                "exactly one of tolerance or directed_error is required"
            )
        if self.tolerance is not None and self.directed_error is not None:
            raise ValueError(
                "tolerance and directed_error must not be supplied together"
            )
        return self


class SimplifyResponse(BaseModel):
    """Only the retained indices, retained points and segment count."""

    indices: list[int]
    points: list[Point]
    segment_count: int


# ---------------------------------------------------------------------------
# Segment-budget mode
# ---------------------------------------------------------------------------


class BudgetRequest(_StrictlyIncreasingTimesMixin, BaseModel):
    """Request for the segment-budget solver (no integer tolerance)."""

    model_config = ConfigDict(extra="forbid")

    points: list[Point] = Field(min_length=MIN_POINTS, max_length=MAX_POINTS)
    budget: StrictInt = Field(ge=MIN_BUDGET, le=MAX_BUDGET)
    directed_error: DirectedErrorConfig | None = None

    @model_validator(mode="after")
    def _check_budget_below_point_count(self) -> "BudgetRequest":
        if self.budget >= len(self.points):
            raise ValueError("budget must be smaller than the number of points")
        return self


class FractionValue(BaseModel):
    """An exact reduced rational ``numerator / denominator``.

    The denominator is always positive and the pair is coprime, so the
    value can be compared on the client by integer cross multiplication
    without any floating point rounding.
    """

    model_config = ConfigDict(extra="forbid")

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_reduced(self) -> "FractionValue":
        if gcd(self.numerator, self.denominator) != 1:
            raise ValueError("fraction must be reduced (coprime numerator/denominator)")
        return self


class SegmentWitness(BaseModel):
    """Per-segment worst-deviation report in the budget response."""

    model_config = ConfigDict(extra="forbid")

    start: int
    end: int
    error: FractionValue
    #: Smallest original index attaining this segment's worst error;
    #: null for segments joining adjacent samples (no intermediate point).
    witness: int | None = None


class BudgetResponse(BaseModel):
    """Budget-mode result: one response feeds table, SVG and markers."""

    indices: list[int]
    points: list[Point]
    segment_count: int
    budget: int
    max_error: FractionValue
    segments: list[SegmentWitness]


# ---------------------------------------------------------------------------
# Directional error mode (shared response shape for both endpoints)
# ---------------------------------------------------------------------------


DirectionValue = Literal["above", "below", "on"]


class WitnessValue(BaseModel):
    """Original point attaining a worst deviation, with its direction.

    ``direction`` is ``"above"`` / ``"below"`` for a point strictly on
    that side of the interpolation line, or ``"on"`` for a collinear
    point attaining a zero worst ratio.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    direction: DirectionValue


class DirectedSegmentWitness(BaseModel):
    """Per-segment report in a directional-error response."""

    model_config = ConfigDict(extra="forbid")

    start: int
    end: int
    #: Segment bottleneck ratio ``deviation / side-bound`` (the common
    #: multiplier consumed by this segment); exact reduced rational.
    ratio: FractionValue
    #: Smallest intermediate index attaining ``ratio`` with its
    #: direction; null for segments joining adjacent samples.
    witness: WitnessValue | None = None


class DirectedResponse(BaseModel):
    """Directional threshold result: table and SVG share this response."""

    indices: list[int]
    points: list[Point]
    segment_count: int
    directed_error: DirectedErrorConfig
    #: Largest side-aware ratio over the retained path; always <= 1 for
    #: threshold adjudication (0 when the path is exactly collinear).
    worst_ratio: FractionValue
    #: Original point attaining the path-wide worst ratio (smallest
    #: index on a tie) with its deviation direction; null when no
    #: retained segment has an intermediate point.
    witness: WitnessValue | None
    segments: list[DirectedSegmentWitness]


class BudgetDirectedResponse(BaseModel):
    """Directional budget result: one response feeds table and SVG."""

    indices: list[int]
    points: list[Point]
    segment_count: int
    budget: int
    directed_error: DirectedErrorConfig
    #: Minimised common multiplier of the two side bounds; exact
    #: reduced rational (may be a non-integer).
    worst_ratio: FractionValue
    #: Original point attaining the worst multiplier (smallest index on
    #: an above/below tie, direction retained); null only when every
    #: retained segment joins adjacent samples.
    witness: WitnessValue | None
    segments: list[DirectedSegmentWitness]

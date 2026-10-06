"""Pydantic schemas for the simplification API.

Validation is intentionally strict so that the problem statement is
enforced at the boundary:

* unknown fields are rejected;
* only genuine integers are accepted (floats, booleans and numeric
  strings are not silently coerced);
* the point count, coordinate ranges and time ordering are checked.
"""

from __future__ import annotations

from math import gcd

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


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: StrictInt = Field(ge=MIN_TIME, le=MAX_TIME)
    value: StrictInt = Field(ge=-MAX_ABS_VALUE, le=MAX_ABS_VALUE)


class SimplifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[Point] = Field(min_length=MIN_POINTS, max_length=MAX_POINTS)
    tolerance: StrictInt = Field(ge=0, le=MAX_TOLERANCE)

    @model_validator(mode="after")
    def _check_strictly_increasing_times(self) -> "SimplifyRequest":
        previous = None
        for point in self.points:
            if previous is not None and point.time <= previous:
                raise ValueError(
                    "points.time must be strictly increasing"
                )
            previous = point.time
        return self


class SimplifyResponse(BaseModel):
    """Only the retained indices, retained points and segment count."""

    indices: list[int]
    points: list[Point]
    segment_count: int


# ---------------------------------------------------------------------------
# Segment-budget mode
# ---------------------------------------------------------------------------


class BudgetRequest(BaseModel):
    """Request for the segment-budget solver (no integer tolerance)."""

    model_config = ConfigDict(extra="forbid")

    points: list[Point] = Field(min_length=MIN_POINTS, max_length=MAX_POINTS)
    budget: StrictInt = Field(ge=MIN_BUDGET, le=MAX_BUDGET)

    @model_validator(mode="after")
    def _check_strictly_increasing_times(self) -> "BudgetRequest":
        previous = None
        for point in self.points:
            if previous is not None and point.time <= previous:
                raise ValueError(
                    "points.time must be strictly increasing"
                )
            previous = point.time
        return self

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

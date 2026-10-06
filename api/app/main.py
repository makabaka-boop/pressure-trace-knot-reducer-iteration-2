"""FastAPI application exposing the trajectory simplifiers."""

from __future__ import annotations

from typing import Union

from fastapi import FastAPI

from .schemas import (
    BudgetDirectedResponse,
    BudgetRequest,
    BudgetResponse,
    DirectedErrorConfig,
    DirectedResponse,
    DirectedSegmentWitness,
    FractionValue,
    SegmentWitness,
    SimplifyRequest,
    SimplifyResponse,
    WitnessValue,
)
from .simplifier import (
    simplify,
    simplify_directional,
    simplify_with_budget,
    simplify_with_budget_directional,
)

app = FastAPI(title="Pressure Trajectory Simplifier", version="1.2.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _fraction(value) -> FractionValue:
    return FractionValue(numerator=value.numerator, denominator=value.denominator)


@app.post(
    "/api/simplify",
    response_model=Union[SimplifyResponse, DirectedResponse],
)
def simplify_trajectory(
    request: SimplifyRequest,
) -> SimplifyResponse | DirectedResponse:
    times = [point.time for point in request.points]
    values = [point.value for point in request.points]

    if request.directed_error is not None:
        bounds = request.directed_error
        solution = simplify_directional(
            times, values, bounds.above, bounds.below
        )
        return DirectedResponse(
            indices=solution.indices,
            points=[request.points[i] for i in solution.indices],
            segment_count=solution.segment_count,
            directed_error=bounds,
            worst_ratio=_fraction(solution.worst_ratio),
            witness=(
                WitnessValue(
                    index=solution.witness.index,
                    direction=solution.witness.direction,
                )
                if solution.witness is not None
                else None
            ),
            segments=[
                DirectedSegmentWitness(
                    start=segment.start,
                    end=segment.end,
                    ratio=_fraction(segment.ratio),
                    witness=(
                        WitnessValue(
                            index=segment.witness.index,
                            direction=segment.witness.direction,
                        )
                        if segment.witness is not None
                        else None
                    ),
                )
                for segment in solution.segments
            ],
        )

    indices = simplify(times, values, request.tolerance)
    retained = [request.points[i] for i in indices]

    return SimplifyResponse(
        indices=indices,
        points=retained,
        segment_count=len(indices) - 1,
    )


@app.post(
    "/api/simplify-budget",
    response_model=Union[BudgetResponse, BudgetDirectedResponse],
)
def simplify_trajectory_with_budget(
    request: BudgetRequest,
) -> BudgetResponse | BudgetDirectedResponse:
    times = [point.time for point in request.points]
    values = [point.value for point in request.points]

    if request.directed_error is not None:
        bounds = request.directed_error
        solution = simplify_with_budget_directional(
            times, values, request.budget, bounds.above, bounds.below
        )
        return BudgetDirectedResponse(
            indices=solution.indices,
            points=[request.points[i] for i in solution.indices],
            segment_count=solution.segment_count,
            budget=request.budget,
            directed_error=DirectedErrorConfig(
                above=bounds.above, below=bounds.below
            ),
            worst_ratio=_fraction(solution.worst_ratio),
            witness=(
                WitnessValue(
                    index=solution.witness.index,
                    direction=solution.witness.direction,
                )
                if solution.witness is not None
                else None
            ),
            segments=[
                DirectedSegmentWitness(
                    start=segment.start,
                    end=segment.end,
                    ratio=_fraction(segment.ratio),
                    witness=(
                        WitnessValue(
                            index=segment.witness.index,
                            direction=segment.witness.direction,
                        )
                        if segment.witness is not None
                        else None
                    ),
                )
                for segment in solution.segments
            ],
        )

    solution = simplify_with_budget(times, values, request.budget)
    retained = [request.points[i] for i in solution.indices]

    return BudgetResponse(
        indices=solution.indices,
        points=retained,
        segment_count=solution.segment_count,
        budget=request.budget,
        max_error=FractionValue(
            numerator=solution.max_error.numerator,
            denominator=solution.max_error.denominator,
        ),
        segments=[
            SegmentWitness(
                start=segment.start,
                end=segment.end,
                error=FractionValue(
                    numerator=segment.error.numerator,
                    denominator=segment.error.denominator,
                ),
                witness=segment.witness,
            )
            for segment in solution.segments
        ],
    )

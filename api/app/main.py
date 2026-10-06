"""FastAPI application exposing the trajectory simplifiers."""

from __future__ import annotations

from fastapi import FastAPI

from .schemas import (
    BudgetRequest,
    BudgetResponse,
    FractionValue,
    SegmentWitness,
    SimplifyRequest,
    SimplifyResponse,
)
from .simplifier import simplify, simplify_with_budget

app = FastAPI(title="Pressure Trajectory Simplifier", version="1.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/simplify", response_model=SimplifyResponse)
def simplify_trajectory(request: SimplifyRequest) -> SimplifyResponse:
    times = [point.time for point in request.points]
    values = [point.value for point in request.points]

    indices = simplify(times, values, request.tolerance)
    retained = [request.points[i] for i in indices]

    return SimplifyResponse(
        indices=indices,
        points=retained,
        segment_count=len(indices) - 1,
    )


@app.post("/api/simplify-budget", response_model=BudgetResponse)
def simplify_trajectory_with_budget(
    request: BudgetRequest,
) -> BudgetResponse:
    times = [point.time for point in request.points]
    values = [point.value for point in request.points]

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

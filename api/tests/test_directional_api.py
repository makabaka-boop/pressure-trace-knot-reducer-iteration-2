"""HTTP-level tests for the optional directional error configuration.

Covers both endpoints: the response contracts, exact non-integer
multipliers, above/below witness direction, boundary equality, 422 on
illegal configuration (including supplying the legacy tolerance and the
new configuration together), and item-for-item compatibility of the
legacy responses when the configuration is absent.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


POINTS = [
    {"time": 0, "value": 0},
    {"time": 1, "value": 1},
    {"time": 2, "value": 0},
]


# ---------------------------------------------------------------------------
# Threshold endpoint + directed_error
# ---------------------------------------------------------------------------


def test_threshold_directed_happy_path_contract():
    response = client.post(
        "/api/simplify",
        json={
            "points": POINTS,
            "directed_error": {"above": 2, "below": 5},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "indices",
        "points",
        "segment_count",
        "directed_error",
        "worst_ratio",
        "witness",
        "segments",
    }
    assert data["directed_error"] == {"above": 2, "below": 5}
    # cross product 2 over dt 2 -> deviation 1; ratio 1/2 (bound 2)
    assert data["worst_ratio"] == {"numerator": 1, "denominator": 2}
    assert data["indices"] == [0, 2]
    assert data["witness"] == {"index": 1, "direction": "above"}
    (segment,) = data["segments"]
    assert set(segment) == {"start", "end", "ratio", "witness"}
    assert segment["start"] == 0 and segment["end"] == 2
    assert segment["ratio"] == {"numerator": 1, "denominator": 2}
    assert segment["witness"] == {"index": 1, "direction": "above"}


def test_threshold_directed_reports_below_direction():
    response = client.post(
        "/api/simplify",
        json={
            "points": [
                {"time": 0, "value": 0},
                {"time": 1, "value": -1},
                {"time": 2, "value": 0},
            ],
            "directed_error": {"above": 9, "below": 2},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["witness"]["direction"] == "below"


def test_threshold_directed_boundary_equality_is_accepted():
    # deviation exactly equal to the bound -> ratio 1, still admissible.
    response = client.post(
        "/api/simplify",
        json={
            "points": [
                {"time": 0, "value": 0},
                {"time": 1, "value": 2},
                {"time": 2, "value": -2},
                {"time": 3, "value": 0},
            ],
            "directed_error": {"above": 2, "below": 2},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["indices"] == [0, 3]
    assert data["worst_ratio"] == {"numerator": 1, "denominator": 1}
    # smallest attaining index is the above point
    assert data["witness"] == {"index": 1, "direction": "above"}


def test_threshold_directed_one_unit_beyond_boundary_forces_split():
    body = {
        "points": [
            {"time": 0, "value": 0},
            {"time": 1, "value": 3},
            {"time": 2, "value": 0},
        ],
        "directed_error": {"above": 2, "below": 2},
    }
    response = client.post("/api/simplify", json=body)
    assert response.status_code == 200
    assert response.json()["indices"] == [0, 1, 2]


def test_threshold_collinear_zero_ratio_witness_is_on():
    response = client.post(
        "/api/simplify",
        json={
            "points": [
                {"time": 0, "value": 0},
                {"time": 1, "value": 2},
                {"time": 2, "value": 4},
            ],
            "directed_error": {"above": 1, "below": 1},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["indices"] == [0, 2]
    assert data["worst_ratio"] == {"numerator": 0, "denominator": 1}
    assert data["witness"] == {"index": 1, "direction": "on"}
    assert data["segments"][0]["witness"] == {
        "index": 1,
        "direction": "on",
    }


def test_threshold_two_points_null_witness():
    response = client.post(
        "/api/simplify",
        json={
            "points": [{"time": 0, "value": 0}, {"time": 1, "value": 9}],
            "directed_error": {"above": 1, "below": 1},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["witness"] is None
    assert data["segments"][0]["witness"] is None
    assert data["worst_ratio"] == {"numerator": 0, "denominator": 1}


# ---------------------------------------------------------------------------
# Budget endpoint + directed_error
# ---------------------------------------------------------------------------


def test_budget_directed_happy_path_non_integer_multiplier():
    response = client.post(
        "/api/simplify-budget",
        json={
            "budget": 1,
            "points": POINTS,
            "directed_error": {"above": 3, "below": 7},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "indices",
        "points",
        "segment_count",
        "budget",
        "directed_error",
        "worst_ratio",
        "witness",
        "segments",
    }
    assert data["budget"] == 1
    assert data["directed_error"] == {"above": 3, "below": 7}
    # deviation 1 over bound 3 -> exact non-integer multiplier 1/3
    assert data["worst_ratio"] == {"numerator": 1, "denominator": 3}
    assert data["witness"] == {"index": 1, "direction": "above"}
    assert data["segments"][0]["ratio"] == {
        "numerator": 1,
        "denominator": 3,
    }


def test_budget_directed_multiplier_can_exceed_one():
    # bounds tighter than the unavoidable deviation -> multiplier > 1.
    response = client.post(
        "/api/simplify-budget",
        json={
            "budget": 1,
            "points": [
                {"time": 0, "value": 0},
                {"time": 1, "value": -3},
                {"time": 2, "value": 0},
            ],
            "directed_error": {"above": 1, "below": 2},
        },
    )
    assert response.status_code == 200
    data = response.json()
    # deviation 3/2 over below bound 2 -> multiplier 3/4 ... recompute:
    # cross product 3*2 = 6 over dt 2 -> deviation 3; ratio 3/2.
    num, den = data["worst_ratio"]["numerator"], data["worst_ratio"]["denominator"]
    assert (num, den) == (3, 2)
    assert data["witness"]["direction"] == "below"


def test_budget_directed_full_budget_null_global_witness():
    response = client.post(
        "/api/simplify-budget",
        json={
            "budget": 2,
            "points": POINTS,
            "directed_error": {"above": 1, "below": 1},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["indices"] == [0, 1, 2]
    assert data["worst_ratio"] == {"numerator": 0, "denominator": 1}
    assert data["witness"] is None
    assert [seg["witness"] for seg in data["segments"]] == [None, None]


def test_budget_directed_fewest_segments_then_lexicographic():
    # Peaks of height 5 at every odd index.  At the minimised
    # multiplier the optimum uses two segments (fewer than budget 5);
    # among two-segment optima the lexicographically smallest split is
    # [0, 3, 6] (the balanced half-chords share the same bottleneck).
    points = [
        {"time": i, "value": (5 if i % 2 else 0)} for i in range(7)
    ]
    response = client.post(
        "/api/simplify-budget",
        json={
            "budget": 5,
            "points": points,
            "directed_error": {"above": 4, "below": 4},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["indices"] == [0, 3, 6]
    assert data["segment_count"] == 2  # fewer than the budget of 5
    # shared bottleneck 5/6, first attaining witness sits on segment 1
    assert data["witness"] == {"index": 1, "direction": "above"}


def test_budget_directed_above_below_tie_keeps_smallest_index():
    response = client.post(
        "/api/simplify-budget",
        json={
            "budget": 1,
            "points": [
                {"time": 0, "value": 0},
                {"time": 1, "value": 2},
                {"time": 2, "value": -2},
                {"time": 3, "value": 0},
            ],
            "directed_error": {"above": 1, "below": 1},
        },
    )
    assert response.status_code == 200
    data = response.json()
    # both middle points attain ratio 2; smallest index (1, above) wins
    assert data["witness"] == {"index": 1, "direction": "above"}


def test_budget_directed_boundary_multiplier_feasibility():
    # multiplier exactly 1 must be feasible with inclusive boundaries.
    response = client.post(
        "/api/simplify-budget",
        json={
            "budget": 1,
            "points": [
                {"time": 0, "value": 0},
                {"time": 1, "value": 2},
                {"time": 2, "value": -2},
                {"time": 3, "value": 0},
            ],
            "directed_error": {"above": 2, "below": 2},
        },
    )
    data = response.json()
    assert response.status_code == 200
    assert data["worst_ratio"] == {"numerator": 1, "denominator": 1}


# ---------------------------------------------------------------------------
# 422: illegal configuration
# ---------------------------------------------------------------------------


def test_threshold_rejects_tolerance_and_directed_error_together():
    response = client.post(
        "/api/simplify",
        json={
            "points": POINTS,
            "tolerance": 1,
            "directed_error": {"above": 1, "below": 1},
        },
    )
    assert response.status_code == 422


def test_threshold_requires_some_error_mode():
    response = client.post("/api/simplify", json={"points": POINTS})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "config",
    [
        {"above": 0, "below": 1},
        {"above": 1, "below": 0},
        {"above": -1, "below": 1},
        {"above": 1, "below": 10**6 + 1},
        {"above": 1.5, "below": 1},
        {"above": 1, "below": True},
        {"above": 1},  # missing below
        {"below": 1},  # missing above
        {},  # empty config
        {"above": 1, "below": 1, "sideways": 1},  # unknown field
        5,
        "tight",
        [1, 1],
    ],
)
def test_threshold_illegal_directed_config_is_422(config):
    response = client.post(
        "/api/simplify", json={"points": POINTS, "directed_error": config}
    )
    assert response.status_code == 422, config


@pytest.mark.parametrize(
    "config",
    [
        {"above": 0, "below": 1},
        {"above": 1, "below": -2},
        {"above": 1.0, "below": 1},
        {"below": 1},
        {"above": 1, "below": 1, "extra": 0},
    ],
)
def test_budget_illegal_directed_config_is_422(config):
    response = client.post(
        "/api/simplify-budget",
        json={"budget": 1, "points": POINTS, "directed_error": config},
    )
    assert response.status_code == 422, config


def test_budget_directed_null_is_not_rejected_key_absent():
    # Absence of the optional config is the legacy request.
    response = client.post(
        "/api/simplify-budget", json={"budget": 1, "points": POINTS}
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "indices",
        "points",
        "segment_count",
        "budget",
        "max_error",
        "segments",
    }


def test_explicit_null_directed_error_is_422():
    # Explicit null does not satisfy "exactly one mode" on the threshold
    # endpoint and is not a valid config object on either.
    response = client.post(
        "/api/simplify",
        json={"points": POINTS, "directed_error": None},
    )
    assert response.status_code == 422


def test_directed_config_still_validates_points():
    response = client.post(
        "/api/simplify",
        json={
            "points": [
                {"time": 1, "value": 0},
                {"time": 0, "value": 0},
            ],
            "directed_error": {"above": 1, "below": 1},
        },
    )
    assert response.status_code == 422


def test_budget_directed_still_enforces_budget_range():
    response = client.post(
        "/api/simplify-budget",
        json={
            "budget": 3,
            "points": POINTS,
            "directed_error": {"above": 1, "below": 1},
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Legacy compatibility: item-for-item unchanged when config is absent
# ---------------------------------------------------------------------------


def test_legacy_threshold_response_unchanged():
    response = client.post(
        "/api/simplify", json={"points": POINTS, "tolerance": 0}
    )
    assert response.status_code == 200
    assert set(response.json()) == {"indices", "points", "segment_count"}


def test_legacy_budget_response_unchanged():
    response = client.post(
        "/api/simplify-budget", json={"budget": 1, "points": POINTS}
    )
    assert response.status_code == 200
    data = response.json()
    # cross product 2 / dt 2 -> deviation exactly 1
    assert data["max_error"] == {"numerator": 1, "denominator": 1}
    assert data["segments"][0]["witness"] == 1
    assert "worst_ratio" not in data and "directed_error" not in data

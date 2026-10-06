"""HTTP-level tests for the segment-budget endpoint and mode isolation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def body(points, budget):
    return {"points": points, "budget": budget}


POINTS = [
    {"time": 0, "value": 0},
    {"time": 1, "value": 0},
    {"time": 2, "value": 1},
]


def test_happy_path_response_contract_non_integer_error():
    response = client.post("/api/simplify-budget", json=body(POINTS, 1))
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "indices",
        "points",
        "segment_count",
        "budget",
        "max_error",
        "segments",
    }
    # exact reduced rational 1/2, never a rounded integer
    assert data["max_error"] == {"numerator": 1, "denominator": 2}
    assert data["budget"] == 1
    assert data["indices"] == [0, 2]
    assert data["segment_count"] == 1
    (segment,) = data["segments"]
    assert set(segment) == {"start", "end", "error", "witness"}
    assert segment["start"] == 0 and segment["end"] == 2
    assert segment["error"] == {"numerator": 1, "denominator": 2}
    assert segment["witness"] == 1


def test_zero_error_collinear_response():
    points = [
        {"time": 0, "value": 0},
        {"time": 1, "value": 2},
        {"time": 2, "value": 4},
    ]
    response = client.post("/api/simplify-budget", json=body(points, 1))
    assert response.status_code == 200
    data = response.json()
    assert data["indices"] == [0, 2]
    assert data["max_error"] == {"numerator": 0, "denominator": 1}
    assert data["segments"][0]["witness"] == 1
    assert data["segments"][0]["error"] == {"numerator": 0, "denominator": 1}


def test_full_budget_keeps_all_points_null_witnesses():
    response = client.post("/api/simplify-budget", json=body(POINTS, 2))
    assert response.status_code == 200
    data = response.json()
    assert data["indices"] == [0, 1, 2]
    assert data["segment_count"] == 2
    assert data["max_error"] == {"numerator": 0, "denominator": 1}
    assert [segment["witness"] for segment in data["segments"]] == [None, None]


def test_budget_boundaries_are_accepted():
    points = [{"time": i, "value": (i % 3) - 1} for i in range(11)]
    for budget in (1, 10):
        response = client.post("/api/simplify-budget", json=body(points, budget))
        assert response.status_code == 200


def test_modes_do_not_accept_each_others_parameter():
    # tolerance is unknown to the budget endpoint ...
    response = client.post(
        "/api/simplify-budget",
        json={"points": POINTS, "budget": 1, "tolerance": 5},
    )
    assert response.status_code == 422
    # ... and budget is unknown to the legacy endpoint.
    response = client.post(
        "/api/simplify",
        json={"points": POINTS, "tolerance": 0, "budget": 1},
    )
    assert response.status_code == 422


def test_legacy_endpoint_response_shape_is_unchanged():
    response = client.post(
        "/api/simplify", json={"points": POINTS, "tolerance": 0}
    )
    assert response.status_code == 200
    assert set(response.json()) == {"indices", "points", "segment_count"}


def test_budget_equal_to_point_count_is_422():
    response = client.post("/api/simplify-budget", json=body(POINTS, 3))
    assert response.status_code == 422


def test_budget_above_ten_is_422_even_when_points_allow_it():
    points = [{"time": i, "value": 0} for i in range(12)]
    response = client.post("/api/simplify-budget", json=body(points, 11))
    assert response.status_code == 422


def test_budget_below_one_is_422():
    response = client.post("/api/simplify-budget", json=body(POINTS, 0))
    assert response.status_code == 422


def test_float_or_bool_budget_is_422():
    for bad_budget in (1.0, True, False, "2"):
        response = client.post(
            "/api/simplify-budget", json=body(POINTS, bad_budget)
        )
        assert response.status_code == 422, bad_budget


def test_unknown_fields_and_point_violations_are_422():
    bad_bodies = [
        {**body(POINTS, 1), "extra": 1},
        body(
            [
                {"time": 0, "value": 0, "z": 1},
                {"time": 1, "value": 0},
                {"time": 2, "value": 1},
            ],
            1,
        ),
        body([{"time": 0, "value": 0}], 1),
        body(
            [
                {"time": 2, "value": 0},
                {"time": 1, "value": 0},
                {"time": 0, "value": 1},
            ],
            1,
        ),
        body(
            [
                {"time": 0, "value": 0.5},
                {"time": 1, "value": 0},
                {"time": 2, "value": 1},
            ],
            1,
        ),
        {"points": POINTS},  # missing budget
        {"budget": 1},  # missing points
    ]
    for payload in bad_bodies:
        response = client.post("/api/simplify-budget", json=payload)
        assert response.status_code == 422, payload

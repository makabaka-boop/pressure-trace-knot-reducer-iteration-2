"""HTTP-level tests: validation (422) and response contract."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def payload(points, tolerance=1):
    return {"points": points, "tolerance": tolerance}


GOOD = payload(
    [
        {"time": 0, "value": 0},
        {"time": 1, "value": 1},
        {"time": 2, "value": 0},
        {"time": 3, "value": 1},
    ],
    tolerance=0,
)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_happy_path_response_contract():
    response = client.post("/api/simplify", json=GOOD)
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"indices", "points", "segment_count"}
    assert data["indices"] == [0, 1, 2, 3]
    assert data["points"] == GOOD["points"]
    assert data["segment_count"] == 3


def test_endpoint_collapses_collinear_data():
    body = payload(
        [
            {"time": 0, "value": 0},
            {"time": 1, "value": 2},
            {"time": 2, "value": 4},
            {"time": 3, "value": 6},
        ],
        tolerance=0,
    )
    response = client.post("/api/simplify", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["indices"] == [0, 3]
    assert data["points"] == [{"time": 0, "value": 0}, {"time": 3, "value": 6}]
    assert data["segment_count"] == 1


@pytest.mark.parametrize(
    "body",
    [
        # unknown top-level field
        {**GOOD, "extra": 1},
        # unknown point field
        payload([{"time": 0, "value": 0, "z": 1}, {"time": 1, "value": 0}]),
        # float value / time / tolerance are not coerced
        payload([{"time": 0, "value": 0}, {"time": 1, "value": 1.5}]),
        payload([{"time": 0.5, "value": 0}, {"time": 1, "value": 0}]),
        {**GOOD, "tolerance": 0.0},
        # booleans are not accepted as integers
        payload([{"time": 0, "value": True}, {"time": 1, "value": 0}]),
        # wrong / equal ordering
        payload(
            [{"time": 1, "value": 0}, {"time": 0, "value": 0}]
        ),
        payload(
            [{"time": 1, "value": 0}, {"time": 1, "value": 1}]
        ),
        # range violations
        payload(
            [{"time": -1, "value": 0}, {"time": 1, "value": 0}]
        ),
        payload(
            [{"time": 0, "value": 10**6 + 1}, {"time": 1, "value": 0}]
        ),
        payload(
            [{"time": 0, "value": -10**6 - 1}, {"time": 1, "value": 0}]
        ),
        {**GOOD, "tolerance": -1},
        {**GOOD, "tolerance": 10**6 + 1},
        # missing field
        {"points": [{"time": 0}, {"time": 1, "value": 0}], "tolerance": 0},
        {"tolerance": 0},
    ],
)
def test_invalid_bodies_return_422(body):
    response = client.post("/api/simplify", json=body)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_too_few_points_returns_422():
    response = client.post(
        "/api/simplify",
        json=payload([{"time": 0, "value": 0}]),
    )
    assert response.status_code == 422


def test_too_many_points_returns_422():
    points = [{"time": i, "value": 0} for i in range(121)]
    response = client.post("/api/simplify", json=payload(points))
    assert response.status_code == 422


def test_malformed_json_returns_422():
    response = client.post(
        "/api/simplify",
        content="{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


def test_boundary_counts_are_accepted():
    for count in (2, 120):
        points = [{"time": i, "value": 0} for i in range(count)]
        response = client.post("/api/simplify", json=payload(points))
        assert response.status_code == 200
        assert response.json()["indices"] == [0, count - 1]

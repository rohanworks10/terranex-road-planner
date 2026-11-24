"""
Tests for the /plan endpoint.

All tests that call slope_profile mock it out so they never hit the real
Open-Meteo API — the tests stay fast and work offline.
"""
import pytest
from fastapi.testclient import TestClient
import main
from main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# A realistic fake result that slope_profile would return for a valid route.
# ---------------------------------------------------------------------------
FAKE_TERRAIN = {
    "distance_m": 32500.0,
    "elevations_m": [100.0] * 20,
    "sample_count": 20,
    "sample_interval_distance_m": 1710.5,
    "endpoint_slope_percent": 8.75,
    "endpoint_slope_degrees": 5.0,
    "endpoint_slope_magnitude_degrees": 5.0,
    "average_absolute_segment_slope_percent": 8.75,
    "average_absolute_segment_slope_degrees": 5.0,
    "steepest_segment_slope_percent": 14.3,
    "steepest_segment_slope_degrees": 8.1,
    "average_slope_percent": 8.75,
    "max_slope_percent": 14.3,
    "average_slope_degrees": 5.0,   # exactly matches SLOPE_TOLERANCE_DEGREES
}


# ---------------------------------------------------------------------------
# Original three tests — updated to match new response shape
# ---------------------------------------------------------------------------

def test_plan_accepts_valid_input(monkeypatch):
    """The endpoint returns 200 and status ok for valid input."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "endpoint_slope_degrees": 5.0,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_plan_rejects_bad_slope():
    """Schema validation rejects slope >= 90 degrees before terrain is called."""
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 120,
    })
    assert response.status_code == 422


def test_plan_rejects_bad_latitude():
    """Schema validation rejects latitude > 90."""
    response = client.post("/api/plan", json={
        "start": {"lat": 200, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 12,
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# New tests — terrain results are present in the response
# ---------------------------------------------------------------------------

def test_plan_returns_distance(monkeypatch):
    """Response includes the terrain distance in metres."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 5.0,
    })
    assert response.json()["distance_m"] == 32500.0


def test_plan_returns_calculated_slope(monkeypatch):
    """Response includes the slope that was calculated from elevation data."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 5.0,
    })
    data = response.json()
    assert data["calculated_slope_degrees"] == 5.0
    assert data["endpoint_slope_degrees"] == 5.0
    assert data["comparison_metric"] == "endpoint_slope_magnitude"
    assert data["average_slope_percent"] == 8.75
    assert data["max_slope_percent"] == 14.3
    assert data["average_absolute_segment_slope_degrees"] == 5.0
    assert data["steepest_segment_slope_degrees"] == 8.1


# ---------------------------------------------------------------------------
# New tests — slope comparison logic
# ---------------------------------------------------------------------------

def test_no_warning_when_slopes_match(monkeypatch):
    """No warning when user slope equals calculated slope."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 5.0,   # same as FAKE_TERRAIN
    })
    data = response.json()
    assert data["slope_difference_degrees"] == 0.0
    assert data["slope_warning"] is False


def test_warning_compares_endpoint_not_segment_average(monkeypatch):
    terrain_result = {
        **FAKE_TERRAIN,
        "average_absolute_segment_slope_degrees": 20.0,
    }
    monkeypatch.setattr(main, "slope_profile", lambda start, end: terrain_result)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "endpoint_slope_degrees": 5.0,
    })
    assert response.json()["slope_warning"] is False


def test_no_warning_when_difference_is_within_tolerance(monkeypatch):
    """No warning when the difference is less than 5.0 degrees."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 8.9,   # differs by 3.9 degrees — within 5.0
    })
    data = response.json()
    assert data["slope_difference_degrees"] < 5.0
    assert data["slope_warning"] is False


def test_warning_when_difference_exceeds_tolerance(monkeypatch):
    """Warning is True when user slope differs from calculated slope by > 5.0 degrees."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 15.0,  # differs by 10.0 degrees — over tolerance
    })
    data = response.json()
    assert data["slope_difference_degrees"] > 5.0
    assert data["slope_warning"] is True


def test_slope_difference_is_always_positive(monkeypatch):
    """The difference is always positive regardless of which is larger."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 1.0,   # user gave a smaller value
    })
    data = response.json()
    # calculated is 5.0, user is 1.0 — difference should be 4.0, not -4.0
    assert data["slope_difference_degrees"] == 4.0


def test_warning_uses_unrounded_endpoint_measurement(monkeypatch):
    terrain_result = {
        **FAKE_TERRAIN,
        "endpoint_slope_magnitude_degrees": 5.04,
        "endpoint_slope_degrees": 5.04,
    }
    monkeypatch.setattr(main, "slope_profile", lambda start, end: terrain_result)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "endpoint_slope_degrees": 10.02,
    })
    data = response.json()
    assert data["slope_difference_degrees"] == 4.98
    assert data["slope_warning"] is False


def test_response_includes_tolerance_value(monkeypatch):
    """The tolerance used is returned so the frontend can show it."""
    monkeypatch.setattr(main, "slope_profile", lambda start, end: FAKE_TERRAIN)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 5.0,
    })
    assert response.json()["slope_tolerance_degrees"] == 5.0


# ---------------------------------------------------------------------------
# New tests — error handling
# ---------------------------------------------------------------------------

def test_same_start_and_end_returns_error(monkeypatch):
    """When start == end, terrain raises ValueError and we return status error."""
    def raise_value_error(start, end):
        raise ValueError("Start and end are the same place.")
    monkeypatch.setattr(main, "slope_profile", raise_value_error)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.85, "lon": 74.50},
        "average_slope_degrees": 5.0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data


def test_elevation_api_failure_returns_error(monkeypatch):
    """When the elevation API is unreachable, we return status error (not a crash)."""
    def raise_network_error(start, end):
        raise Exception("Connection timed out")
    monkeypatch.setattr(main, "slope_profile", raise_network_error)
    response = client.post("/api/plan", json={
        "start": {"lat": 15.85, "lon": 74.50},
        "end":   {"lat": 15.60, "lon": 74.30},
        "average_slope_degrees": 5.0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "elevation" in data["error"].lower()

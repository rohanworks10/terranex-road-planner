import pytest
import terrain


def test_one_degree_of_latitude_is_about_111_km():
    d = terrain.distance_m((10.0, 75.0), (11.0, 75.0))
    assert 111000 < d < 111500


def test_sample_line_includes_both_ends():
    pts = terrain.sample_line((10.0, 75.0), (12.0, 77.0), 5)
    assert pts[0] == (10.0, 75.0)
    assert pts[-1] == (12.0, 77.0)
    assert len(pts) == 5


def test_flat_ground_gives_zero_slope(monkeypatch):
    monkeypatch.setattr(terrain, "get_elevations", lambda pts: [500.0] * len(pts))
    result = terrain.slope_profile((15.0, 74.0), (15.1, 74.0), 10)
    assert result["average_slope_percent"] == 0
    assert result["max_slope_percent"] == 0
    assert result["endpoint_slope_degrees"] == 0
    assert result["average_absolute_segment_slope_degrees"] == 0
    assert result["steepest_segment_slope_degrees"] == 0


def test_steady_climb_gives_expected_slope(monkeypatch):
    # climb of 111 m over ~11.1 km of straight line = about 1 %
    monkeypatch.setattr(terrain, "get_elevations",
                        lambda pts: [100.0 + 111 * i / (len(pts) - 1) for i in range(len(pts))])
    result = terrain.slope_profile((15.0, 74.0), (15.1, 74.0), 10)
    assert 0.9 < result["average_slope_percent"] < 1.1


def test_uphill_endpoint_slope_is_positive(monkeypatch):
    monkeypatch.setattr(
        terrain,
        "get_elevations",
        lambda pts: [100.0 * i / (len(pts) - 1) for i in range(len(pts))],
    )
    result = terrain.slope_profile((15.0, 74.0), (15.1, 74.0), 10)
    assert result["endpoint_slope_percent"] > 0
    assert result["endpoint_slope_degrees"] > 0


def test_downhill_endpoint_slope_is_negative(monkeypatch):
    monkeypatch.setattr(
        terrain,
        "get_elevations",
        lambda pts: [100.0 - 100.0 * i / (len(pts) - 1) for i in range(len(pts))],
    )
    result = terrain.slope_profile((15.0, 74.0), (15.1, 74.0), 10)
    assert result["endpoint_slope_percent"] < 0
    assert result["endpoint_slope_degrees"] < 0
    assert result["endpoint_slope_magnitude_degrees"] > 0


def test_varying_terrain_keeps_endpoint_and_segment_slopes_distinct(monkeypatch):
    monkeypatch.setattr(
        terrain, "get_elevations", lambda pts: [0.0, 100.0, 0.0, 100.0, 0.0]
    )
    result = terrain.slope_profile((15.0, 74.0), (15.04, 74.0), 5)
    assert result["endpoint_slope_degrees"] == 0
    assert result["average_absolute_segment_slope_percent"] > 0
    assert result["steepest_segment_slope_percent"] >= result[
        "average_absolute_segment_slope_percent"
    ]


def test_percent_to_degrees_conversion(monkeypatch):
    start = (15.0, 74.0)
    end = (15.01, 74.0)
    run_m = terrain.distance_m(start, end)
    monkeypatch.setattr(terrain, "get_elevations", lambda pts: [0.0, run_m * 0.1])
    result = terrain.slope_profile(start, end, 2)
    assert result["endpoint_slope_percent"] == pytest.approx(10.0, abs=0.1)
    assert result["endpoint_slope_degrees"] == pytest.approx(5.7, abs=0.1)


def test_slope_unit_conversions():
    assert terrain.slope_percent_to_degrees(10) == pytest.approx(5.7106, abs=1e-4)
    assert terrain.slope_degrees_to_percent(45) == pytest.approx(100)


def test_default_sampling_uses_100_points(monkeypatch):
    observed_count = []

    def flat_elevations(points):
        observed_count.append(len(points))
        return [100.0] * len(points)

    monkeypatch.setattr(terrain, "get_elevations", flat_elevations)
    result = terrain.slope_profile((15.0, 74.0), (15.1, 74.0))
    assert observed_count == [100]
    assert result["sample_count"] == 100


def test_invalid_elevation_values_are_rejected(monkeypatch):
    monkeypatch.setattr(terrain, "get_elevations", lambda pts: [0.0, None] + [0.0] * (len(pts) - 2))
    with pytest.raises(ValueError, match="Elevation values"):
        terrain.slope_profile((15.0, 74.0), (15.1, 74.0), 10)


def test_same_start_and_end_is_rejected(monkeypatch):
    monkeypatch.setattr(terrain, "get_elevations", lambda pts: [1.0] * len(pts))
    with pytest.raises(ValueError):
        terrain.slope_profile((15.0, 74.0), (15.0, 74.0))
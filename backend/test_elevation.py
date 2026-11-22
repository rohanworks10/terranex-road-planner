import json

import httpx
import pytest
import elevation


def fake_get(url, params=None, timeout=None):
    n = len(params["latitude"].split(","))
    return httpx.Response(200, json={"elevation": [100.0 + i for i in range(n)]},
                          request=httpx.Request("GET", url))


def test_returns_one_elevation_per_point(monkeypatch):
    monkeypatch.setattr(elevation.httpx, "get", fake_get)
    assert elevation.get_elevations([(15.85, 74.5), (15.9, 74.6)]) == [100.0, 101.0]


def test_sends_latitudes_and_longitudes_in_coordinate_order(monkeypatch):
    observed_params = {}

    def capture_get(url, params=None, timeout=None):
        observed_params.update(params)
        return fake_get(url, params=params, timeout=timeout)

    monkeypatch.setattr(elevation.httpx, "get", capture_get)
    elevation.get_elevations([(15.85, 74.5), (15.9, 74.6)])
    assert observed_params["latitude"] == "15.85,15.9"
    assert observed_params["longitude"] == "74.5,74.6"


def test_rejects_bad_latitude():
    with pytest.raises(ValueError):
        elevation.get_elevations([(95, 74.5)])


def test_rejects_empty_list():
    with pytest.raises(ValueError):
        elevation.get_elevations([])


def test_rejects_too_many_points():
    with pytest.raises(ValueError):
        elevation.get_elevations([(15.0, 74.0)] * 101)


@pytest.mark.parametrize("values", [[None], [float("nan")], [float("inf")], ["120"]])
def test_rejects_missing_or_invalid_elevation_values(monkeypatch, values):
    def response_with_values(url, params=None, timeout=None):
        return httpx.Response(
            200,
            content=json.dumps({"elevation": values}, allow_nan=True).encode(),
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(elevation.httpx, "get", response_with_values)
    with pytest.raises(ValueError, match="invalid elevation"):
        elevation.get_elevations([(15.85, 74.5)])


def test_rejects_response_without_elevation_field(monkeypatch):
    def response_without_elevation(url, params=None, timeout=None):
        return httpx.Response(
            200, json={}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(elevation.httpx, "get", response_without_elevation)
    with pytest.raises(ValueError, match="did not contain"):
        elevation.get_elevations([(15.85, 74.5)])
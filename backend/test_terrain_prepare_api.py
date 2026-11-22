from fastapi.testclient import TestClient

import main
from dem import DemDataError
from main import app


client = TestClient(app)


def test_terrain_prepare_endpoint_returns_area_and_dataset_metadata(monkeypatch):
    expected = {
        "status": "prepared",
        "area_id": "test-area",
        "study_area": {"west": 10, "south": 20, "east": 11, "north": 21},
        "dataset": {"name": "Copernicus DEM GLO-30 Public"},
    }
    observed = {}

    def fake_prepare(start, end, buffer_m):
        observed.update(start=start, end=end, buffer_m=buffer_m)
        return expected

    monkeypatch.setattr(main, "prepare_terrain", fake_prepare)
    response = client.post("/terrain/prepare", json={
        "start": {"lat": 20.1, "lon": 10.1},
        "end": {"lat": 20.9, "lon": 10.9},
        "buffer_m": 1200,
    })

    assert response.status_code == 200
    assert response.json() == expected
    assert observed == {
        "start": (20.1, 10.1),
        "end": (20.9, 10.9),
        "buffer_m": 1200,
    }


def test_terrain_prepare_endpoint_validates_coordinates():
    response = client.post("/terrain/prepare", json={
        "start": {"lat": 91, "lon": 10},
        "end": {"lat": 20, "lon": 11},
    })
    assert response.status_code == 422


def test_terrain_prepare_endpoint_reports_missing_dem_data(monkeypatch):
    def missing_data(start, end, buffer_m):
        raise DemDataError("No public DEM tile is available for this area.")

    monkeypatch.setattr(main, "prepare_terrain", missing_data)
    response = client.post("/terrain/prepare", json={
        "start": {"lat": 20.1, "lon": 10.1},
        "end": {"lat": 20.9, "lon": 10.9},
    })
    assert response.status_code == 503
    assert "No public DEM tile" in response.json()["detail"]

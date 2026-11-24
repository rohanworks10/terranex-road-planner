import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform

import main
from dem import TerrainNotPreparedError
from routing import NoRouteError, generate_route_alternatives


@pytest.fixture
def raster_factory(tmp_path):
    transform_affine = from_origin(500000, 1000000, 30, 30)
    height = width = 11
    nodata = -9999.0
    rasters = {
        "dem": np.zeros((height, width), dtype=np.float32),
        "slope": np.zeros((height, width), dtype=np.float32),
    }

    def write(slope=None, invalid_cells=()):
        slope_values = rasters["slope"].copy() if slope is None else slope.copy()
        dem_values = rasters["dem"].copy()
        cost_values = 1 + np.tan(np.radians(slope_values))
        for row, col in invalid_cells:
            dem_values[row, col] = nodata
            slope_values[row, col] = nodata
            cost_values[row, col] = nodata
        paths = {}
        for name, values in (
            ("dem", dem_values),
            ("slope", slope_values),
            ("cost", cost_values.astype(np.float32)),
        ):
            path = tmp_path / f"{name}.tif"
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype="float32",
                crs="EPSG:32643",
                transform=transform_affine,
                nodata=nodata,
            ) as dataset:
                dataset.write(values.astype(np.float32), 1)
            paths[name] = path
        paths["area_id"] = "artificial-test-grid"
        paths["transform"] = transform_affine
        paths["manifest"] = {
            "dataset": {
                "name": "Artificial unit-test DEM",
                "release": "test fixture",
                "nominal_resolution_m": 30,
                "retrieved_at_utc": "unit-test-only",
            }
        }
        return paths

    def point(row, col):
        x = transform_affine.c + transform_affine.a * (col + 0.5)
        y = transform_affine.f + transform_affine.e * (row + 0.5)
        lon, lat = transform("EPSG:32643", "EPSG:4326", [x], [y])
        return float(lat[0]), float(lon[0])

    return write, point


def _features(paths, raster_factory, start=None, end=None, snap_radius_m=90):
    _, point = raster_factory
    start = point(5, 0) if start is None else start
    end = point(5, 10) if end is None else end
    return generate_route_alternatives(
        start, end, paths, snap_radius_m=snap_radius_m
    )


def test_flat_raster_returns_two_geojson_routes_and_distance_metrics(raster_factory):
    write, _ = raster_factory
    result = _features(write(), raster_factory)

    assert result["type"] == "FeatureCollection"
    assert result["terrain_data"]["nominal_resolution_m"] == 30
    assert len(result["features"]) == 2
    route_a, route_b = result["features"]
    assert route_a["geometry"]["type"] == "LineString"
    longitude, latitude = route_a["geometry"]["coordinates"][0]
    assert 73 < longitude < 77
    assert 8 < latitude < 11
    assert route_a["properties"]["route_distance_km"] == pytest.approx(0.3, abs=0.01)
    assert route_a["properties"]["cells_traversed"] == 11
    assert route_a["properties"]["average_slope_degrees"] == 0
    assert route_a["properties"]["maximum_slope_degrees"] == 0
    assert route_a["properties"]["accumulated_cost_m"] == pytest.approx(300)
    assert route_a["properties"]["straight_line_distance_km"] == pytest.approx(
        route_a["properties"]["route_distance_km"], abs=0.005
    )
    assert result["route_similarity"]["same_path"] is True
    assert route_b["properties"]["accumulated_cost_m"] == pytest.approx(300)


def test_stronger_slope_penalty_avoids_a_steep_cell(raster_factory):
    write, _ = raster_factory
    slope = np.zeros((11, 11), dtype=np.float32)
    slope[5, 5] = 35
    result = _features(write(slope=slope), raster_factory)
    route_a, route_b = result["features"]
    path_a = route_a["geometry"]["coordinates"]
    path_b = route_b["geometry"]["coordinates"]

    assert route_a["properties"]["maximum_slope_degrees"] == 35
    assert route_a["properties"]["average_slope_degrees"] == pytest.approx(3.5)
    assert route_a["properties"]["average_slope_percent"] == pytest.approx(7.0)
    assert route_b["properties"]["maximum_slope_degrees"] == 0
    assert route_b["properties"]["route_distance_km"] > route_a["properties"]["route_distance_km"]
    assert route_a["properties"]["accumulated_cost_m"] < route_b["properties"]["accumulated_cost_m"]
    assert path_a != path_b


def test_route_avoids_nodata_cells_and_snaps_nearby_endpoint(raster_factory):
    write, point = raster_factory
    paths = write(invalid_cells=[(5, 5), (5, 0)])
    result = _features(
        paths,
        raster_factory,
        start=point(5, 0),
        snap_radius_m=90,
    )

    for feature in result["features"]:
        assert feature["properties"]["start_snap_distance_m"] == pytest.approx(30)
        assert feature["properties"]["cells_traversed"] > 0
        for longitude, latitude in feature["geometry"]["coordinates"]:
            x, y = transform(
                "EPSG:4326",
                "EPSG:32643",
                [longitude],
                [latitude],
            )
            row, col = rasterio.transform.rowcol(paths["transform"], x[0], y[0])
            assert (row, col) not in {(5, 5), (5, 0)}


def test_diagonal_step_distance_uses_cell_size_and_avoids_nodata(raster_factory):
    write, _ = raster_factory
    result = _features(write(invalid_cells=[(5, 5)]), raster_factory)

    for feature in result["features"]:
        assert feature["properties"]["route_distance_km"] == pytest.approx(
            (300 + 2 * (30 * np.sqrt(2) - 30)) / 1000,
            abs=0.001,
        )


def test_no_route_when_nodata_barrier_separates_endpoints(raster_factory):
    write, _ = raster_factory
    paths = write(invalid_cells=[(row, 5) for row in range(11)])

    with pytest.raises(NoRouteError, match="No feasible route"):
        _features(paths, raster_factory)


def test_invalid_coordinates_and_too_distant_snap_are_rejected(raster_factory):
    write, point = raster_factory
    paths = write(invalid_cells=[(5, 0)])
    valid_end = point(5, 10)

    with pytest.raises(ValueError, match="latitude"):
        generate_route_alternatives((91, 74), valid_end, paths)
    with pytest.raises(ValueError, match="latitude"):
        generate_route_alternatives(point(5, 0), (91, 74), paths)
    with pytest.raises(ValueError, match="snapping limit"):
        generate_route_alternatives(
            point(5, 0), valid_end, paths, snap_radius_m=10
        )


def test_route_endpoint_uses_cached_grid_and_returns_geojson(raster_factory, monkeypatch):
    paths = raster_factory[0]()
    monkeypatch.setattr(main, "cached_terrain_files", lambda *args: paths)
    client = TestClient(main.app)
    start = raster_factory[1](5, 0)
    end = raster_factory[1](5, 10)

    response = client.post(
        "/api/routes",
        json={
            "start": {"lat": start[0], "lon": start[1]},
            "end": {"lat": end[0], "lon": end[1]},
        },
    )

    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"
    assert [feature["id"] for feature in response.json()["features"]] == [
        "route_a", "route_b"
    ]


def test_route_endpoint_reports_missing_cached_grid(raster_factory, monkeypatch):
    def no_cached_grid(*args):
        raise TerrainNotPreparedError("Prepare the terrain grid first.")

    monkeypatch.setattr(main, "cached_terrain_files", no_cached_grid)
    client = TestClient(main.app)
    start = raster_factory[1](5, 0)
    end = raster_factory[1](5, 10)

    response = client.post(
        "/api/routes",
        json={
            "start": {"lat": start[0], "lon": start[1]},
            "end": {"lat": end[0], "lon": end[1]},
        },
    )

    assert response.status_code == 409
    assert "Prepare the terrain grid first" in response.json()["detail"]

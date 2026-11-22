from contextlib import contextmanager

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import dem
from dem import (
    DemDataError,
    TerrainNotPreparedError,
    _download_dem_tile,
    _cached_or_download_dem_tile,
    cached_terrain_files,
    clip_dem,
)
from study_area import calculate_study_area


def _write_test_dem(path, data, transform, nodata=-9999):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(data.astype(np.float32), 1)


def _mock_download(monkeypatch, content, content_length=None):
    class Response:
        headers = {
            "content-length": str(
                len(content) if content_length is None else content_length
            )
        }

        def raise_for_status(self):
            pass

        def iter_bytes(self, chunk_size):
            for offset in range(0, len(content), min(chunk_size, 128)):
                yield content[offset:offset + min(chunk_size, 128)]

    @contextmanager
    def fake_stream(method, url, **kwargs):
        assert method == "GET"
        yield Response()

    monkeypatch.setattr(dem.httpx, "stream", fake_stream)


def test_clip_dem_writes_only_the_requested_bounds(tmp_path):
    source_path = tmp_path / "test-dem.tif"
    output_path = tmp_path / "clipped-dem.tif"
    values = np.arange(100, dtype=np.float32).reshape((10, 10))
    _write_test_dem(
        source_path,
        values,
        from_origin(0, 1, 0.1, 0.1),
    )
    study_area = {
        "parts": [{"west": 0.2, "south": 0.2, "east": 0.8, "north": 0.8}]
    }

    summary = clip_dem(
        [source_path],
        study_area,
        output_path,
        target_crs="EPSG:4326",
    )

    with rasterio.open(output_path) as clipped:
        west, south, east, north = rasterio.transform.array_bounds(
            clipped.height, clipped.width, clipped.transform
        )
        assert west == pytest.approx(0.2)
        assert east == pytest.approx(0.8)
        assert south == pytest.approx(0.2)
        assert north == pytest.approx(0.8)
        assert clipped.crs.to_string() == "EPSG:4326"
    assert summary["valid_cells"] > 0


def test_clip_dem_reprojects_to_target_crs(tmp_path):
    source_path = tmp_path / "test-dem.tif"
    values = np.arange(100, dtype=np.float32).reshape((10, 10))
    _write_test_dem(source_path, values, from_origin(0, 1, 0.1, 0.1))
    study_area = {
        "parts": [{"west": 0.2, "south": 0.2, "east": 0.8, "north": 0.8}]
    }

    summary = clip_dem(
        [source_path],
        study_area,
        tmp_path / "reprojected-dem.tif",
        target_crs="EPSG:32631",
    )

    with rasterio.open(tmp_path / "reprojected-dem.tif") as clipped:
        assert clipped.crs.to_string() == "EPSG:32631"
        assert clipped.width > 0
        assert clipped.height > 0
        assert np.any(clipped.read(1) != clipped.nodata)
    assert summary["crs"] == "EPSG:32631"


def test_clip_dem_rejects_bounds_outside_source_raster(tmp_path):
    source_path = tmp_path / "test-dem.tif"
    _write_test_dem(
        source_path,
        np.ones((10, 10), dtype=np.float32),
        from_origin(0, 1, 0.1, 0.1),
    )
    output_path = tmp_path / "outside-clip.tif"
    study_area = {
        "parts": [{"west": 10, "south": 10, "east": 11, "north": 11}]
    }

    with pytest.raises(DemDataError, match="do not overlap"):
        clip_dem([source_path], study_area, output_path, target_crs="EPSG:4326")

    assert not output_path.exists()


def test_clip_dem_rejects_invalid_target_crs(tmp_path):
    source_path = tmp_path / "test-dem.tif"
    _write_test_dem(
        source_path,
        np.ones((10, 10), dtype=np.float32),
        from_origin(0, 1, 0.1, 0.1),
    )
    study_area = {
        "parts": [{"west": 0.2, "south": 0.2, "east": 0.8, "north": 0.8}]
    }

    with pytest.raises(DemDataError, match="Could not transform"):
        clip_dem(
            [source_path],
            study_area,
            tmp_path / "invalid-crs-clip.tif",
            target_crs="EPSG:invalid",
        )


def test_download_dem_tile_streams_and_validates_raster(tmp_path, monkeypatch):
    original_path = tmp_path / "source.tif"
    _write_test_dem(
        original_path,
        np.arange(100, dtype=np.float32).reshape((10, 10)),
        from_origin(0, 1, 0.1, 0.1),
    )
    _mock_download(monkeypatch, original_path.read_bytes())
    destination = tmp_path / "downloaded.tif"

    result = _download_dem_tile("https://example.test/tile.tif", destination)

    assert result == destination
    assert not (tmp_path / "downloaded.tif.part").exists()
    with rasterio.open(destination) as downloaded:
        assert downloaded.crs.to_string() == "EPSG:4326"
        assert downloaded.read(1).shape == (10, 10)


def test_download_dem_tile_rejects_raster_without_crs(tmp_path, monkeypatch):
    source_path = tmp_path / "missing-crs.tif"
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        transform=from_origin(0, 1, 0.1, 0.1),
    ) as dataset:
        dataset.write(np.ones((10, 10), dtype=np.float32), 1)
    _mock_download(monkeypatch, source_path.read_bytes())

    with pytest.raises(DemDataError, match="no coordinate reference system"):
        _download_dem_tile(
            "https://example.test/tile.tif", tmp_path / "missing-crs-download.tif"
        )


def test_download_dem_tile_cleans_up_incomplete_download(tmp_path, monkeypatch):
    content = b"incomplete tile"
    _mock_download(monkeypatch, content, content_length=len(content) + 1)
    destination = tmp_path / "incomplete.tif"

    with pytest.raises(DemDataError, match="Incomplete DEM download"):
        _download_dem_tile("https://example.test/tile.tif", destination)

    assert not destination.exists()
    assert not (tmp_path / "incomplete.tif.part").exists()


def test_download_dem_tile_rejects_corrupted_raster(tmp_path, monkeypatch):
    content = b"not a GeoTIFF"
    _mock_download(monkeypatch, content)
    destination = tmp_path / "corrupted.tif"

    with pytest.raises(DemDataError, match="unreadable or corrupted"):
        _download_dem_tile("https://example.test/tile.tif", destination)

    assert not destination.exists()
    assert not (tmp_path / "corrupted.tif.part").exists()


def test_cached_dem_tile_is_validated_before_reuse(tmp_path, monkeypatch):
    source_path = tmp_path / "source.tif"
    _write_test_dem(
        source_path,
        np.ones((10, 10), dtype=np.float32),
        from_origin(0, 1, 0.1, 0.1),
    )
    cached_path = tmp_path / "cached.tif"
    cached_path.write_bytes(source_path.read_bytes())
    monkeypatch.setattr(
        dem,
        "_download_dem_tile",
        lambda url, destination: pytest.fail("valid cached tiles should be reused"),
    )

    result = _cached_or_download_dem_tile(
        "https://example.test/tile.tif", cached_path
    )

    assert result == cached_path


def test_corrupt_cached_dem_tile_is_replaced(tmp_path, monkeypatch):
    source_path = tmp_path / "source.tif"
    _write_test_dem(
        source_path,
        np.ones((10, 10), dtype=np.float32),
        from_origin(0, 1, 0.1, 0.1),
    )
    content = source_path.read_bytes()
    _mock_download(monkeypatch, content)
    cached_path = tmp_path / "cached.tif"
    cached_path.write_bytes(b"corrupted cached tile")

    result = _cached_or_download_dem_tile(
        "https://example.test/tile.tif", cached_path
    )

    assert result == cached_path
    with rasterio.open(cached_path) as raster:
        assert raster.read(1).shape == (10, 10)


def test_clip_dem_reports_missing_source_file(tmp_path):
    study_area = {
        "parts": [{"west": 0.2, "south": 0.2, "east": 0.8, "north": 0.8}]
    }

    with pytest.raises(DemDataError, match="Could not clip or reproject DEM data"):
        clip_dem(
            [tmp_path / "missing.tif"],
            study_area,
            tmp_path / "missing-clip.tif",
        )


def test_clip_dem_reports_all_nodata_source(tmp_path):
    source_path = tmp_path / "empty-dem.tif"
    _write_test_dem(
        source_path,
        np.full((10, 10), -9999, dtype=np.float32),
        from_origin(0, 1, 0.1, 0.1),
    )
    study_area = {
        "parts": [{"west": 0.2, "south": 0.2, "east": 0.8, "north": 0.8}]
    }
    with pytest.raises(DemDataError, match="no valid elevation data"):
        clip_dem(
            [source_path],
            study_area,
            tmp_path / "empty-clip.tif",
            target_crs="EPSG:4326",
        )


def test_prepare_terrain_writes_rasters_and_provenance_without_network(
    tmp_path, monkeypatch
):
    source_path = tmp_path / "source-dem.tif"
    values = np.add.outer(
        np.arange(100, dtype=np.float32),
        np.arange(100, dtype=np.float32),
    )
    _write_test_dem(
        source_path,
        values,
        from_origin(0, 1, 0.01, 0.01),
    )
    monkeypatch.setattr(dem, "_check_source_tiles", lambda names: [str(source_path)])
    data_root = tmp_path / "processed"

    result = dem.prepare_terrain(
        (0.25, 0.25),
        (0.255, 0.255),
        buffer_m=100,
        data_root=data_root,
    )

    area_dir = data_root / result["area_id"]
    assert result["status"] == "prepared"
    assert result["dataset"]["name"] == "Copernicus DEM GLO-30 Public"
    assert result["dataset"]["nominal_resolution_m"] == 30
    assert result["dataset"]["retrieved_at_utc"]
    assert result["raster"]["valid_slope_cells"] > 0
    for name in ("dem.tif", "slope_degrees.tif", "cost.tif", "manifest.json"):
        assert (area_dir / name).is_file()

    monkeypatch.setattr(
        dem,
        "_check_source_tiles",
        lambda names: pytest.fail("cached terrain data should not be fetched again"),
    )
    cached = dem.prepare_terrain(
        (0.25, 0.25),
        (0.255, 0.255),
        buffer_m=100,
        data_root=data_root,
    )
    assert cached == result


def test_cached_terrain_lookup_requires_existing_matching_grid(tmp_path, monkeypatch):
    start = (0.25, 0.25)
    end = (0.255, 0.255)
    study_area = calculate_study_area(start, end, 100)
    area_id = dem._area_id(study_area)
    area_dir = tmp_path / area_id
    area_dir.mkdir()
    monkeypatch.setattr(dem, "DATA_ROOT", tmp_path)

    with pytest.raises(TerrainNotPreparedError, match="Prepare the terrain grid"):
        cached_terrain_files(start, end, 100)

    for name in ("dem.tif", "slope_degrees.tif", "cost.tif"):
        (area_dir / name).touch()
    (area_dir / "manifest.json").write_text(
        (
            f'{{"status": "prepared", "area_id": "{area_id}", '
            '"cost_surface": {"formula": "1 + slope_percent / 100"}, '
            '"dataset": {"name": "Test DEM", "release": "test", '
            '"nominal_resolution_m": 30, "retrieved_at_utc": "test"}}'
        ),
        encoding="utf-8",
    )
    result = cached_terrain_files(start, end, 100)

    assert result["area_id"] == area_id
    assert result["dem"] == area_dir / "dem.tif"
    assert result["slope"] == area_dir / "slope_degrees.tif"
    assert result["cost"] == area_dir / "cost.tif"

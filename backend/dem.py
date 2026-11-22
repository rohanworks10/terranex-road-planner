"""On-demand Copernicus DEM retrieval, clipping, reprojection, and metadata."""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import tempfile

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import RasterioError
from rasterio.crs import CRS
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from study_area import calculate_study_area, copernicus_tile_names, local_utm_crs
from terrain_grid import NODATA_VALUE, calculate_slope_and_cost


COPERNICUS_BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
COPERNICUS_SOURCE_URL = "https://registry.opendata.aws/copernicus-dem/"
COPERNICUS_RELEASE = "2021 release"
COPERNICUS_RESOLUTION_M = 30
MAX_SOURCE_TILES = 25
MAX_GRID_PIXELS = 25_000_000
DATA_ROOT = Path(__file__).resolve().parent / "data" / "terrain"
logger = logging.getLogger(__name__)


class DemDataError(RuntimeError):
    """Raised when source DEM data cannot be retrieved or processed."""


class TerrainNotPreparedError(DemDataError):
    """Raised when a request has no matching cached terrain grid."""


def copernicus_tile_url(tile_name):
    return f"{COPERNICUS_BASE_URL}/{tile_name}/{tile_name}.tif"


def _projected_bounds(study_area, target_crs):
    bounds = [
        transform_bounds(
            "EPSG:4326",
            target_crs,
            part["west"],
            part["south"],
            part["east"],
            part["north"],
            densify_pts=21,
        )
        for part in study_area["parts"]
    ]
    return (
        min(bound[0] for bound in bounds),
        min(bound[1] for bound in bounds),
        max(bound[2] for bound in bounds),
        max(bound[3] for bound in bounds),
    )


def _validate_grid_extent(bounds, resolution_m):
    width = math.ceil((bounds[2] - bounds[0]) / resolution_m)
    height = math.ceil((bounds[3] - bounds[1]) / resolution_m)
    if width <= 0 or height <= 0:
        raise ValueError("The projected study area has no usable area.")
    if width * height > MAX_GRID_PIXELS:
        raise ValueError(
            f"The study area would create more than {MAX_GRID_PIXELS:,} raster cells; "
            "reduce the buffer or use a smaller study area."
        )


def _write_raster(path, data, profile):
    output_profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": profile["crs"],
        "transform": profile["transform"],
        "nodata": NODATA_VALUE,
        "compress": "deflate",
        "tiled": True,
    }
    clean_data = np.where(np.isfinite(data), data, NODATA_VALUE).astype(np.float32)
    with rasterio.open(path, "w", **output_profile) as output:
        output.write(clean_data, 1)


def _validate_dem_tile(path, source_label):
    try:
        with rasterio.open(path) as source:
            if source.crs is None:
                raise DemDataError(
                    f"DEM tile {source_label} has no coordinate reference system."
                )
            if source.count < 1 or source.width <= 0 or source.height <= 0:
                raise DemDataError(
                    f"DEM tile {source_label} has invalid raster dimensions."
                )
            if (not all(math.isfinite(value) for value in source.bounds)
                    or source.bounds.left >= source.bounds.right
                    or source.bounds.bottom >= source.bounds.top):
                raise DemDataError(f"DEM tile {source_label} has invalid raster bounds.")

            block_count = 0
            for _, window in source.block_windows(1):
                source.read(1, window=window)
                block_count += 1
            if block_count == 0:
                raise DemDataError(
                    f"DEM tile {source_label} contains no readable raster blocks."
                )
    except DemDataError:
        raise
    except (RasterioError, OSError, ValueError) as exc:
        raise DemDataError(
            f"DEM tile {source_label} is unreadable or corrupted: {exc}"
        ) from exc


def _download_dem_tile(url, destination):
    """Download and fully decode a DEM tile before making it available to GDAL."""
    destination = Path(destination)
    partial_path = destination.with_name(destination.name + ".part")
    bytes_received = 0

    try:
        with httpx.stream("GET", url, timeout=60.0, follow_redirects=True) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            try:
                expected_length = (
                    int(content_length) if content_length is not None else None
                )
            except ValueError as exc:
                raise DemDataError(
                    f"Copernicus DEM tile {url} returned an invalid Content-Length."
                ) from exc

            with partial_path.open("wb") as downloaded_file:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    downloaded_file.write(chunk)
                    bytes_received += len(chunk)

        if bytes_received == 0:
            raise DemDataError(f"Copernicus DEM tile {url} downloaded no data.")
        if expected_length is not None and bytes_received != expected_length:
            raise DemDataError(
                f"Incomplete DEM download for {url}: expected {expected_length} "
                f"bytes but received {bytes_received}."
            )

        _validate_dem_tile(partial_path, url)
        os.replace(partial_path, destination)
        return destination
    except DemDataError:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise DemDataError(
            f"Could not download or validate Copernicus DEM tile {url}: {exc}"
        ) from exc
    finally:
        if partial_path.exists():
            partial_path.unlink()


def _cached_or_download_dem_tile(url, destination):
    destination = Path(destination)
    if destination.is_file():
        try:
            _validate_dem_tile(destination, url)
            return destination
        except DemDataError as exc:
            logger.warning(
                "Ignoring invalid cached Copernicus DEM tile %s: %s",
                destination,
                exc,
            )
    return _download_dem_tile(url, destination)


def clip_dem(source_paths, study_area, output_path, target_crs="EPSG:4326",
             resolution_m=None):
    """Clip one or more local or remote GeoTIFFs to the request bounds."""
    if not source_paths:
        raise ValueError("At least one DEM source is required.")
    if resolution_m is not None and (
        not math.isfinite(resolution_m) or resolution_m <= 0
    ):
        raise ValueError("Output resolution must be a positive finite number.")

    try:
        target_crs = CRS.from_user_input(target_crs)
        bounds = _projected_bounds(study_area, target_crs)
    except (RasterioError, ValueError) as exc:
        raise DemDataError(
            f"Could not transform the study-area bounds to {target_crs}: {exc}"
        ) from exc
    if (not all(math.isfinite(value) for value in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise DemDataError(
            "The study-area bounds could not be transformed to a valid raster extent."
        )

    merge_options = {"bounds": bounds, "nodata": NODATA_VALUE, "dtype": "float32"}
    if resolution_m is not None:
        _validate_grid_extent(bounds, resolution_m)
        merge_options["res"] = (resolution_m, resolution_m)

    try:
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
            GDAL_HTTP_TIMEOUT="30",
        ):
            with ExitStack() as stack:
                sources = []
                for source_path in source_paths:
                    source = stack.enter_context(rasterio.open(str(source_path)))
                    if source.crs is None:
                        raise DemDataError(f"DEM source has no coordinate reference system: {source_path}")
                    source_bounds = transform_bounds(
                        source.crs,
                        target_crs,
                        *source.bounds,
                        densify_pts=21,
                    )
                    if (not all(math.isfinite(value) for value in source_bounds)
                            or source_bounds[0] >= source_bounds[2]
                            or source_bounds[1] >= source_bounds[3]):
                        raise DemDataError(
                            f"DEM source has invalid bounds: {source_path}"
                        )
                    if (source_bounds[0] >= bounds[2]
                            or source_bounds[2] <= bounds[0]
                            or source_bounds[1] >= bounds[3]
                            or source_bounds[3] <= bounds[1]):
                        continue

                    vrt_options = {
                        "crs": target_crs,
                        "resampling": Resampling.bilinear,
                        "nodata": source.nodata if source.nodata is not None else NODATA_VALUE,
                    }
                    if resolution_m is not None:
                        vrt_options["resolution"] = (resolution_m, resolution_m)
                    sources.append(stack.enter_context(WarpedVRT(source, **vrt_options)))

                if not sources:
                    raise DemDataError(
                        "The requested clipping bounds do not overlap any DEM source raster."
                    )

                mosaic, transform = merge(sources, **merge_options)
                data = np.ma.filled(mosaic[0], NODATA_VALUE).astype(np.float32)
                valid_data = np.isfinite(data) & (data != NODATA_VALUE)
                if data.size == 0 or not np.any(valid_data):
                    raise DemDataError("The DEM contains no valid elevation data for this area.")
                data[~valid_data] = NODATA_VALUE

                profile = {"crs": target_crs, "transform": transform}
                _write_raster(output_path, data, profile)
                return {
                    "width": int(data.shape[1]),
                    "height": int(data.shape[0]),
                    "crs": target_crs.to_string(),
                    "resolution_m": resolution_m,
                    "valid_cells": int(np.count_nonzero(valid_data)),
                    "nodata_cells": int(data.size - np.count_nonzero(valid_data)),
                }
    except DemDataError:
        raise
    except (RasterioError, OSError, ValueError) as exc:
        raise DemDataError(f"Could not clip or reproject DEM data: {exc}") from exc


def _check_source_tiles(tile_names):
    if len(tile_names) > MAX_SOURCE_TILES:
        raise DemDataError(
            f"The requested area intersects {len(tile_names)} DEM tiles; "
            f"the current limit is {MAX_SOURCE_TILES}. Reduce the buffer or area."
        )
    tile_urls = [copernicus_tile_url(name) for name in tile_names]
    for tile_name, tile_url in zip(tile_names, tile_urls):
        try:
            response = httpx.head(tile_url, timeout=15.0, follow_redirects=True)
        except httpx.RequestError as exc:
            raise DemDataError(
                f"Could not check the Copernicus DEM tile {tile_name}: {exc}"
            ) from exc
        if response.status_code == 404:
            raise DemDataError(
                f"Copernicus GLO-30 has no public tile for {tile_name}; "
                "no elevation values were substituted."
            )
        if not response.is_success:
            raise DemDataError(
                f"Copernicus DEM tile check failed for {tile_name} "
                f"(HTTP {response.status_code})."
            )
    return tile_urls


def _area_id(study_area):
    stable_area = {
        "west": round(study_area["west"], 6),
        "south": round(study_area["south"], 6),
        "east": round(study_area["east"], 6),
        "north": round(study_area["north"], 6),
        "buffer_m": round(study_area["buffer_m"], 1),
    }
    digest = hashlib.sha256(
        json.dumps(stable_area, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def cached_terrain_files(start, end, buffer_m=5000):
    """Find an existing prepared grid without downloading or rebuilding data."""
    study_area = calculate_study_area(start, end, buffer_m)
    area_id = _area_id(study_area)
    output_dir = DATA_ROOT / area_id
    expected_files = {
        "dem": output_dir / "dem.tif",
        "slope": output_dir / "slope_degrees.tif",
        "cost": output_dir / "cost.tif",
        "manifest": output_dir / "manifest.json",
    }
    if not all(path.is_file() for path in expected_files.values()):
        raise TerrainNotPreparedError(
            "No prepared terrain grid matches these coordinates and buffer. "
            "Prepare the terrain grid first."
        )
    try:
        with expected_files["manifest"].open("r", encoding="utf-8") as file:
            manifest = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise DemDataError("The cached terrain manifest cannot be read.") from exc
    if not isinstance(manifest, dict) or manifest.get("area_id") != area_id:
        raise DemDataError("The cached terrain manifest does not match this study area.")
    dataset = manifest.get("dataset")
    cost_surface = manifest.get("cost_surface")
    if (manifest.get("status") != "prepared"
            or not isinstance(cost_surface, dict)
            or cost_surface.get("formula")
            != "1 + slope_percent / 100"
            or not isinstance(dataset, dict)
            or any(not dataset.get(key) for key in (
                "name", "release", "nominal_resolution_m", "retrieved_at_utc"
            ))):
        raise DemDataError(
            "The cached terrain grid is missing supported slope-cost or source metadata."
        )
    return {
        "area_id": area_id,
        "manifest": manifest,
        **{key: path for key, path in expected_files.items() if key != "manifest"},
    }


def _surface_statistics(values):
    valid = values[np.isfinite(values)]
    return {
        "minimum": round(float(valid.min()), 2),
        "mean": round(float(valid.mean()), 2),
        "maximum": round(float(valid.max()), 2),
    }


def prepare_terrain(start, end, buffer_m=5000, data_root=None):
    """Prepare and cache a clipped DEM, slope raster, cost raster, and manifest."""
    study_area = calculate_study_area(start, end, buffer_m)
    tile_names = copernicus_tile_names(study_area)
    if not tile_names:
        raise DemDataError("No Copernicus DEM tiles intersect the study area.")

    target_crs = local_utm_crs(start, end)
    projected_bounds = _projected_bounds(study_area, target_crs)
    try:
        _validate_grid_extent(projected_bounds, COPERNICUS_RESOLUTION_M)
    except ValueError as exc:
        raise DemDataError(str(exc)) from exc
    area_id = _area_id(study_area)
    root = Path(data_root) if data_root is not None else DATA_ROOT
    output_dir = root / area_id
    manifest_path = output_dir / "manifest.json"
    expected_files = ["dem.tif", "slope_degrees.tif", "cost.tif"]
    if manifest_path.exists() and all((output_dir / name).exists() for name in expected_files):
        with manifest_path.open("r", encoding="utf-8") as manifest_file:
            return json.load(manifest_file)

    tile_urls = _check_source_tiles(tile_names)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=root) as temp_dir:
            temp_path = Path(temp_dir)
            dem_path = temp_path / "dem.tif"
            source_paths = []
            for index, tile_url in enumerate(tile_urls):
                if tile_url.startswith(("http://", "https://")):
                    source_cache = root / "source_tiles"
                    source_cache.mkdir(parents=True, exist_ok=True)
                    source_path = source_cache / tile_url.rsplit("/", 1)[-1]
                    source_paths.append(
                        _cached_or_download_dem_tile(tile_url, source_path)
                    )
                else:
                    source_paths.append(Path(tile_url))
            dem_summary = clip_dem(
                source_paths,
                study_area,
                dem_path,
                target_crs=target_crs,
                resolution_m=COPERNICUS_RESOLUTION_M,
            )
            with rasterio.open(dem_path) as dem_source:
                dem_grid = dem_source.read(1)
                slope_degrees, slope_percent, cost, valid_mask = (
                    calculate_slope_and_cost(
                        dem_grid,
                        abs(dem_source.transform.a),
                        abs(dem_source.transform.e),
                        nodata=dem_source.nodata,
                    )
                )
                raster_profile = {
                    "crs": dem_source.crs,
                    "transform": dem_source.transform,
                }

            slope_path = temp_path / "slope_degrees.tif"
            cost_path = temp_path / "cost.tif"
            _write_raster(slope_path, slope_degrees, raster_profile)
            _write_raster(cost_path, cost, raster_profile)

            retrieved_at = datetime.now(timezone.utc).isoformat()
            slope_valid = slope_degrees[valid_mask]
            cost_valid = cost[valid_mask]
            manifest = {
                "status": "prepared",
                "area_id": area_id,
                "study_area": study_area,
                "dataset": {
                    "name": "Copernicus DEM GLO-30 Public",
                    "product_type": "Digital Surface Model",
                    "release": COPERNICUS_RELEASE,
                    "nominal_resolution_m": COPERNICUS_RESOLUTION_M,
                    "source_url": COPERNICUS_SOURCE_URL,
                    "license_url": (
                        "https://dataspace.copernicus.eu/explore-data/"
                        "data-collections/copernicus-contributing-missions/collections-description/COP-DEM"
                    ),
                    "tile_urls": tile_urls,
                    "retrieved_at_utc": retrieved_at,
                    "coverage_note": (
                        "Public coverage is incomplete in some areas; "
                        "ocean areas may not have tiles."
                    ),
                },
                "raster": {
                    **dem_summary,
                    "files": expected_files,
                    "valid_slope_cells": int(np.count_nonzero(valid_mask)),
                },
                "slope_degrees": _surface_statistics(slope_valid),
                "cost_surface": {
                    **_surface_statistics(cost_valid),
                    "formula": "1 + slope_percent / 100",
                    "meaning": (
                        "Prototype cost multiplier per metre; NoData and edge cells "
                        "without neighboring elevations are excluded."
                    ),
                },
                "constraints": {
                    "nodata_excluded": True,
                    "water_bodies": "not applied; no water dataset is configured",
                    "land_cover": "not applied; no land-cover dataset is configured",
                    "maximum_slope": "no hard cutoff; continuous penalty only",
                },
            }
            (temp_path / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

            for name in expected_files + ["manifest.json"]:
                os.replace(temp_path / name, output_dir / name)
            return manifest
    except DemDataError:
        raise
    except (RasterioError, OSError, ValueError) as exc:
        raise DemDataError(f"Could not prepare terrain data: {exc}") from exc

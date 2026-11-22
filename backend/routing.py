"""A* route search over prepared, slope-only terrain rasters."""
from heapq import heappop, heappush
import math

import numpy as np
import rasterio
from rasterio.warp import transform

from study_area import validate_point
from terrain import distance_m


ROUTE_A_SLOPE_WEIGHT = 1.0
ROUTE_B_SLOPE_WEIGHT = 3.0
NEIGHBORS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),             (0, 1),
    (1, -1),  (1, 0),  (1, 1),
)


class NoRouteError(RuntimeError):
    """Raised when no path can connect the snapped endpoint cells."""


def _read_aligned_rasters(paths):
    with rasterio.open(paths["dem"]) as dem_source, \
            rasterio.open(paths["slope"]) as slope_source, \
            rasterio.open(paths["cost"]) as cost_source:
        for source in (slope_source, cost_source):
            if (source.width != dem_source.width
                    or source.height != dem_source.height
                    or source.crs != dem_source.crs
                    or source.transform != dem_source.transform):
                raise ValueError("Prepared DEM, slope, and cost rasters are not aligned.")
        if (dem_source.crs is None or not dem_source.crs.is_projected
                or dem_source.crs.linear_units not in ("metre", "meter")):
            raise ValueError("Terrain routing requires a projected raster in metres.")

        dem = dem_source.read(1)
        slope = slope_source.read(1)
        cost_a = cost_source.read(1)
        profile = {
            "width": dem_source.width,
            "height": dem_source.height,
            "crs": dem_source.crs,
            "transform": dem_source.transform,
            "dem_nodata": dem_source.nodata,
            "slope_nodata": slope_source.nodata,
            "cost_nodata": cost_source.nodata,
        }

    valid = np.isfinite(dem) & np.isfinite(slope) & np.isfinite(cost_a)
    for array, nodata in (
        (dem, profile["dem_nodata"]),
        (slope, profile["slope_nodata"]),
        (cost_a, profile["cost_nodata"]),
    ):
        if nodata is not None:
            valid &= array != nodata
    valid &= (slope >= 0) & (slope < 90) & (cost_a >= 1)
    if not np.any(valid):
        raise ValueError("The prepared rasters contain no valid route cells.")

    grade_ratio = np.tan(np.radians(slope.astype(np.float64)))
    cost_b = 1 + ROUTE_B_SLOPE_WEIGHT * grade_ratio
    valid &= np.isfinite(cost_b)
    return slope, cost_a.astype(np.float64), cost_b, valid, profile


def _cell_center(transform_affine, row, col):
    col_offset = col + 0.5
    row_offset = row + 0.5
    x = transform_affine.c + transform_affine.a * col_offset + transform_affine.b * row_offset
    y = transform_affine.f + transform_affine.d * col_offset + transform_affine.e * row_offset
    return x, y


def _snap_to_valid_cell(point, valid, profile, snap_radius_m):
    lat, lon = validate_point(point)
    x_values, y_values = transform(
        "EPSG:4326",
        profile["crs"],
        [lon],
        [lat],
    )
    x, y = x_values[0], y_values[0]
    transform_affine = profile["transform"]
    row, col = rasterio.transform.rowcol(transform_affine, x, y)

    col_size = math.hypot(transform_affine.a, transform_affine.d)
    row_size = math.hypot(transform_affine.b, transform_affine.e)
    row_reach = math.ceil(snap_radius_m / row_size) + 1
    col_reach = math.ceil(snap_radius_m / col_size) + 1
    row_start = max(0, row - row_reach)
    row_stop = min(profile["height"], row + row_reach + 1)
    col_start = max(0, col - col_reach)
    col_stop = min(profile["width"], col + col_reach + 1)
    if row_start >= row_stop or col_start >= col_stop:
        raise ValueError("Endpoint is outside the prepared terrain grid.")

    candidates = valid[row_start:row_stop, col_start:col_stop]
    candidate_rows, candidate_cols = np.nonzero(candidates)
    if len(candidate_rows) == 0:
        raise ValueError("No valid terrain cell is available near an endpoint.")
    candidate_rows += row_start
    candidate_cols += col_start

    centers_x = (
        transform_affine.c
        + transform_affine.a * (candidate_cols + 0.5)
        + transform_affine.b * (candidate_rows + 0.5)
    )
    centers_y = (
        transform_affine.f
        + transform_affine.d * (candidate_cols + 0.5)
        + transform_affine.e * (candidate_rows + 0.5)
    )
    offsets = np.hypot(centers_x - x, centers_y - y)
    best = int(np.argmin(offsets))
    offset_m = float(offsets[best])
    if offset_m > snap_radius_m:
        raise ValueError(
            f"Nearest valid terrain cell is {offset_m:.1f} m away, beyond "
            f"the {snap_radius_m:.1f} m snapping limit."
        )
    return (
        (int(candidate_rows[best]), int(candidate_cols[best])),
        (float(centers_x[best]), float(centers_y[best])),
        offset_m,
        (lat, lon),
    )


def _movement_length(transform_affine, row_delta, col_delta):
    dx = transform_affine.a * col_delta + transform_affine.b * row_delta
    dy = transform_affine.d * col_delta + transform_affine.e * row_delta
    return math.hypot(dx, dy)


def _astar(cost, valid, transform_affine, start, goal):
    height, width = valid.shape
    start_index = start[0] * width + start[1]
    goal_index = goal[0] * width + goal[1]
    total_cells = height * width
    distances = np.full(total_cells, np.inf, dtype=np.float64)
    parents = np.full(total_cells, -1, dtype=np.int32)
    distances[start_index] = 0.0

    goal_x, goal_y = _cell_center(transform_affine, goal[0], goal[1])

    def heuristic(row, col):
        x, y = _cell_center(transform_affine, row, col)
        return math.hypot(goal_x - x, goal_y - y)

    frontier = [(heuristic(*start), 0.0, start_index)]
    while frontier:
        _, current_distance, current_index = heappop(frontier)
        if current_distance > distances[current_index] + 1e-9:
            continue
        if current_index == goal_index:
            break

        row, col = divmod(current_index, width)
        for row_delta, col_delta in NEIGHBORS:
            next_row = row + row_delta
            next_col = col + col_delta
            if (not 0 <= next_row < height or not 0 <= next_col < width
                    or not valid[next_row, next_col]):
                continue
            if row_delta and col_delta:
                if (not valid[row, next_col] or not valid[next_row, col]):
                    continue

            next_index = next_row * width + next_col
            step_m = _movement_length(
                transform_affine, row_delta, col_delta
            )
            step_cost = step_m * (
                cost[row, col] + cost[next_row, next_col]
            ) / 2
            candidate_distance = current_distance + step_cost
            if candidate_distance + 1e-9 >= distances[next_index]:
                continue
            distances[next_index] = candidate_distance
            parents[next_index] = current_index
            priority = candidate_distance + heuristic(next_row, next_col)
            heappush(frontier, (priority, candidate_distance, next_index))

    if not math.isfinite(distances[goal_index]):
        raise NoRouteError("No feasible route connects the snapped endpoints.")

    path = []
    current_index = goal_index
    while current_index != -1:
        path.append(divmod(current_index, width))
        if current_index == start_index:
            break
        current_index = int(parents[current_index])
    if path[-1] != start:
        raise NoRouteError("Could not reconstruct a complete route.")
    path.reverse()
    return path, float(distances[goal_index])


def _route_feature(route_id, label, objective, path, cost, slope,
                   transform_affine, crs, snap_info, straight_line_m):
    xs = []
    ys = []
    for row, col in path:
        x, y = _cell_center(transform_affine, row, col)
        xs.append(x)
        ys.append(y)
    longitudes, latitudes = transform(crs, "EPSG:4326", xs, ys)
    coordinates = [
        [float(lon), float(lat)]
        for lon, lat in zip(longitudes, latitudes)
    ]

    step_lengths = []
    step_slopes = []
    step_grades = []
    total_cost = 0.0
    for (row, col), (next_row, next_col) in zip(path, path[1:]):
        step_m = _movement_length(
            transform_affine, next_row - row, next_col - col
        )
        mean_slope = (float(slope[row, col]) + float(slope[next_row, next_col])) / 2
        mean_grade = (
            math.tan(math.radians(float(slope[row, col])))
            + math.tan(math.radians(float(slope[next_row, next_col])))
        ) / 2 * 100
        step_lengths.append(step_m)
        step_slopes.append(mean_slope)
        step_grades.append(mean_grade)
        total_cost += step_m * (cost[row, col] + cost[next_row, next_col]) / 2

    route_distance_m = sum(step_lengths)
    average_slope_degrees = (
        sum(angle * length for angle, length in zip(step_slopes, step_lengths))
        / route_distance_m
        if route_distance_m else float(slope[path[0]])
    )
    average_slope_percent = (
        sum(grade * length for grade, length in zip(step_grades, step_lengths))
        / route_distance_m
        if route_distance_m else math.tan(math.radians(float(slope[path[0]]))) * 100
    )
    path_slopes = [float(slope[row, col]) for row, col in path]
    maximum_slope_degrees = max(path_slopes)
    maximum_slope_percent = math.tan(math.radians(maximum_slope_degrees)) * 100
    route_start = snap_info["start"]
    route_end = snap_info["end"]

    return {
        "type": "Feature",
        "id": route_id,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "route_id": route_id,
            "name": label,
            "objective": objective,
            "route_distance_km": round(route_distance_m / 1000, 3),
            "average_slope_degrees": round(average_slope_degrees, 2),
            "average_slope_percent": round(average_slope_percent, 2),
            "slope_metric_definition": (
                "Distance-weighted mean of the neighboring slope-raster cell values "
                "for each route segment."
            ),
            "maximum_slope_degrees": round(maximum_slope_degrees, 2),
            "maximum_slope_percent": round(maximum_slope_percent, 2),
            "accumulated_cost_m": round(total_cost, 1),
            "cells_traversed": len(path),
            "start_snap_distance_m": round(route_start["offset_m"], 1),
            "destination_snap_distance_m": round(route_end["offset_m"], 1),
            "snapped_start": [route_start["lon"], route_start["lat"]],
            "snapped_destination": [route_end["lon"], route_end["lat"]],
            "straight_line_distance_km": round(straight_line_m / 1000, 3),
            "explanation": objective,
        },
    }


def generate_route_alternatives(start, end, raster_paths, snap_radius_m=90):
    """Return two least-cost paths from existing aligned terrain rasters."""
    start = validate_point(start, "Start")
    end = validate_point(end, "Destination")
    if start == end:
        raise ValueError("Start and destination must be different points.")
    if (isinstance(snap_radius_m, bool)
            or not isinstance(snap_radius_m, (int, float))
            or not math.isfinite(snap_radius_m)
            or snap_radius_m <= 0):
        raise ValueError("Snapping limit must be a positive finite distance in metres.")

    slope, cost_a, cost_b, valid, profile = _read_aligned_rasters(raster_paths)
    start_cell, _, start_offset, normalized_start = _snap_to_valid_cell(
        start, valid, profile, snap_radius_m
    )
    end_cell, _, end_offset, normalized_end = _snap_to_valid_cell(
        end, valid, profile, snap_radius_m
    )
    if start_cell == end_cell:
        raise ValueError("Both endpoints snap to the same terrain cell.")

    path_a, _ = _astar(
        cost_a, valid, profile["transform"], start_cell, end_cell
    )
    path_b, _ = _astar(
        cost_b, valid, profile["transform"], start_cell, end_cell
    )
    straight_line_m = distance_m(normalized_start, normalized_end)
    snap_info = {
        "start": {
            "lat": normalized_start[0],
            "lon": normalized_start[1],
            "offset_m": start_offset,
        },
        "end": {
            "lat": normalized_end[0],
            "lon": normalized_end[1],
            "offset_m": end_offset,
        },
    }
    feature_a = _route_feature(
        "route_a",
        "Route A — Efficiency-focused",
        "Minimizes distance with the existing moderate slope penalty (weight 1).",
        path_a,
        cost_a,
        slope,
        profile["transform"],
        profile["crs"],
        snap_info,
        straight_line_m,
    )
    feature_b = _route_feature(
        "route_b",
        "Route B — Terrain-focused",
        "Minimizes distance with a stronger slope penalty (weight 3).",
        path_b,
        cost_b,
        slope,
        profile["transform"],
        profile["crs"],
        snap_info,
        straight_line_m,
    )

    cells_a = set(path_a)
    cells_b = set(path_b)
    shared_cells_percent = 100 * len(cells_a & cells_b) / min(len(cells_a), len(cells_b))
    same_path = path_a == path_b
    if same_path:
        similarity_note = (
            "Both objectives selected the same path in this slope-only grid; "
            "no artificial detour was added."
        )
    else:
        similarity_note = (
            f"The routes share {shared_cells_percent:.1f}% of the cells in the "
            "shorter path; compare their distance, slope, and cost metrics."
        )

    return {
        "type": "FeatureCollection",
        "area_id": raster_paths["area_id"],
        "terrain_data": {
            "source": raster_paths["manifest"]["dataset"]["name"],
            "release": raster_paths["manifest"]["dataset"]["release"],
            "nominal_resolution_m": raster_paths["manifest"]["dataset"][
                "nominal_resolution_m"
            ],
            "retrieved_at_utc": raster_paths["manifest"]["dataset"][
                "retrieved_at_utc"
            ],
        },
        "straight_line_distance_km": round(straight_line_m / 1000, 3),
        "route_similarity": {
            "same_path": same_path,
            "shared_cells_percent": round(shared_cells_percent, 1),
            "note": similarity_note,
        },
        "cost_weights": {
            "route_a": ROUTE_A_SLOPE_WEIGHT,
            "route_b": ROUTE_B_SLOPE_WEIGHT,
            "formula": (
                "movement distance × mean of the two neighboring cell cost multipliers"
            ),
        },
        "limitations": [
            "Slope is the only terrain cost.",
            "Construction difficulty beyond slope is not modeled.",
            "Water bodies and land cover are not modeled.",
            "These are terrain-cost paths, not construction-suitability or safety approvals.",
        ],
        "features": [feature_a, feature_b],
    }

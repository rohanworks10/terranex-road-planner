"""Slope and prototype routing-cost calculations for projected DEM grids."""
import math

import numpy as np


NODATA_VALUE = -9999.0


def calculate_slope_and_cost(dem, x_resolution_m, y_resolution_m, nodata=None):
    """Return slope degrees, slope percent, cost multiplier, and valid-cell mask."""
    values = np.asarray(dem, dtype=np.float64)
    if values.ndim != 2 or min(values.shape) < 3:
        raise ValueError("A DEM grid must be two-dimensional and at least 3 by 3.")
    if (not math.isfinite(x_resolution_m) or not math.isfinite(y_resolution_m)
            or x_resolution_m <= 0 or y_resolution_m <= 0):
        raise ValueError("DEM pixel sizes must be positive finite metre values.")

    valid_dem = np.isfinite(values)
    if nodata is not None:
        valid_dem &= values != nodata

    slope_degrees = np.full(values.shape, np.nan, dtype=np.float32)
    slope_percent = np.full(values.shape, np.nan, dtype=np.float32)
    cost = np.full(values.shape, np.nan, dtype=np.float32)

    center = valid_dem[1:-1, 1:-1]
    neighbors_valid = (
        valid_dem[1:-1, :-2]
        & valid_dem[1:-1, 2:]
        & valid_dem[:-2, 1:-1]
        & valid_dem[2:, 1:-1]
    )
    interior_valid = center & neighbors_valid
    if not np.any(interior_valid):
        raise ValueError("The DEM has no valid cells with valid neighboring elevations.")

    dz_dx = (values[1:-1, 2:] - values[1:-1, :-2]) / (2 * x_resolution_m)
    dz_dy = (values[2:, 1:-1] - values[:-2, 1:-1]) / (2 * y_resolution_m)
    grade_ratio = np.hypot(dz_dx, dz_dy)
    interior_slope_percent = grade_ratio * 100
    interior_slope_degrees = np.degrees(np.arctan(grade_ratio))

    slope_percent_view = slope_percent[1:-1, 1:-1]
    slope_degrees_view = slope_degrees[1:-1, 1:-1]
    cost_view = cost[1:-1, 1:-1]
    slope_percent_view[interior_valid] = interior_slope_percent[interior_valid]
    slope_degrees_view[interior_valid] = interior_slope_degrees[interior_valid]
    cost_view[interior_valid] = 1 + interior_slope_percent[interior_valid] / 100

    valid_surface = np.isfinite(slope_degrees)
    return slope_degrees, slope_percent, cost, valid_surface

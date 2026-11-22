import numpy as np
import pytest

from terrain_grid import calculate_slope_and_cost


def test_planar_dem_has_expected_slope_and_cost():
    dem = np.tile(np.arange(5, dtype=np.float32) * 30, (5, 1))
    slope_degrees, slope_percent, cost, valid = calculate_slope_and_cost(
        dem, x_resolution_m=30, y_resolution_m=30
    )
    assert np.allclose(slope_percent[valid], 100)
    assert np.allclose(slope_degrees[valid], 45)
    assert np.allclose(cost[valid], 2)
    assert not valid[0, :].any()


def test_nodata_cells_and_their_unmeasurable_neighbors_are_excluded():
    dem = np.tile(np.arange(5, dtype=np.float32) * 30, (5, 1))
    dem[2, 2] = -9999
    _, _, cost, valid = calculate_slope_and_cost(
        dem, x_resolution_m=30, y_resolution_m=30, nodata=-9999
    )
    assert not valid[2, 2]
    assert np.isnan(cost[2, 2])
    assert np.count_nonzero(valid) < 9


def test_rejects_grid_without_valid_slope_cells():
    with pytest.raises(ValueError, match="no valid cells"):
        calculate_slope_and_cost(
            np.full((3, 3), -9999, dtype=np.float32), 30, 30, nodata=-9999
        )

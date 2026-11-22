import math

import pytest

from study_area import calculate_study_area, copernicus_tile_names, local_utm_crs


def test_study_area_contains_endpoints_and_applies_buffer():
    area = calculate_study_area((10, 20), (10.1, 20.2), buffer_m=1000)
    assert area["west"] < 20
    assert area["east"] > 20.2
    assert area["south"] < 10
    assert area["north"] > 10.1
    assert area["buffer_m"] == 1000


def test_study_area_splits_at_antimeridian():
    area = calculate_study_area((10, 179.9), (10, -179.9), buffer_m=1000)
    assert len(area["parts"]) == 2
    assert area["west"] > area["east"]


@pytest.mark.parametrize(
    "start,end",
    [
        ((91, 0), (0, 0)),
        ((0, 181), (0, 0)),
        ((math.nan, 0), (0, 0)),
        ((0, math.inf), (0, 0)),
    ],
)
def test_rejects_invalid_coordinates(start, end):
    with pytest.raises(ValueError):
        calculate_study_area(start, end)


def test_rejects_identical_endpoints():
    with pytest.raises(ValueError, match="different points"):
        calculate_study_area((10, 20), (10, 20))


def test_rejects_zero_buffer_for_corridor_area():
    with pytest.raises(ValueError, match="positive"):
        calculate_study_area((10, 20), (10.1, 20.1), buffer_m=0)


def test_selects_local_utm_crs():
    assert local_utm_crs((15, 74), (16, 75)) == "EPSG:32643"
    assert local_utm_crs((-20, 130), (-21, 131)) == "EPSG:32752"


def test_tile_names_cover_requested_bbox():
    area = {
        "parts": [{"west": 74.2, "south": 15.2, "east": 74.8, "north": 15.8}]
    }
    assert copernicus_tile_names(area) == [
        "Copernicus_DSM_COG_10_N15_00_E074_00_DEM"
    ]

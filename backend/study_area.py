"""Coordinate validation and request-specific study-area geometry."""
import math

EARTH_RADIUS_M = 6_371_008.8


def validate_point(point, name="Point"):
    if len(point) != 2:
        raise ValueError(f"{name} must contain latitude and longitude.")
    lat, lon = point
    if (isinstance(lat, bool) or isinstance(lon, bool)
            or not isinstance(lat, (int, float))
            or not isinstance(lon, (int, float))
            or not math.isfinite(lat) or not math.isfinite(lon)):
        raise ValueError(f"{name} coordinates must be finite numbers.")
    if not -90 <= lat <= 90:
        raise ValueError(f"{name} latitude must be between -90 and 90.")
    if not -180 <= lon <= 180:
        raise ValueError(f"{name} longitude must be between -180 and 180.")
    return float(lat), float(lon)


def _box_part(west, south, east, north):
    return {"west": west, "south": south, "east": east, "north": north}


def calculate_study_area(start, end, buffer_m=5000):
    """Return buffered WGS84 bounds and one or two antimeridian-safe parts."""
    start_lat, start_lon = validate_point(start, "Start")
    end_lat, end_lon = validate_point(end, "Destination")
    if (isinstance(buffer_m, bool) or not isinstance(buffer_m, (int, float))
            or not math.isfinite(buffer_m) or buffer_m <= 0):
        raise ValueError("Buffer must be a positive finite number of metres.")
    if start_lat == end_lat and start_lon == end_lon:
        raise ValueError("Start and destination must be different points.")

    latitude_padding = math.degrees(buffer_m / EARTH_RADIUS_M)
    south = max(-90.0, min(start_lat, end_lat) - latitude_padding)
    north = min(90.0, max(start_lat, end_lat) + latitude_padding)

    max_abs_latitude = max(abs(south), abs(north))
    longitude_scale = math.cos(math.radians(max_abs_latitude))
    if longitude_scale < 1e-6:
        raise ValueError("A buffered study area is not supported at the poles.")
    longitude_padding = math.degrees(
        buffer_m / (EARTH_RADIUS_M * longitude_scale)
    )

    longitude_delta = (end_lon - start_lon + 180) % 360 - 180
    end_lon_unwrapped = start_lon + longitude_delta
    west_unwrapped = min(start_lon, end_lon_unwrapped) - longitude_padding
    east_unwrapped = max(start_lon, end_lon_unwrapped) + longitude_padding
    if east_unwrapped - west_unwrapped >= 360:
        raise ValueError("The study area is too wide to represent as a local corridor.")

    if west_unwrapped < -180:
        west = west_unwrapped + 360
        east = east_unwrapped
        parts = [
            _box_part(-180.0, south, east_unwrapped, north),
            _box_part(west, south, 180.0, north),
        ]
    elif east_unwrapped > 180:
        west = west_unwrapped
        east = east_unwrapped - 360
        parts = [
            _box_part(west_unwrapped, south, 180.0, north),
            _box_part(-180.0, south, east, north),
        ]
    else:
        west = west_unwrapped
        east = east_unwrapped
        parts = [_box_part(west, south, east, north)]

    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "parts": parts,
        "buffer_m": float(buffer_m),
    }


def local_utm_crs(start, end):
    """Choose the UTM zone at the midpoint for a local, metre-based grid."""
    start_lat, start_lon = validate_point(start, "Start")
    end_lat, end_lon = validate_point(end, "Destination")
    midpoint_lat = (start_lat + end_lat) / 2
    midpoint_lon = start_lon + ((end_lon - start_lon + 180) % 360 - 180) / 2
    if not -80 <= midpoint_lat <= 84:
        raise ValueError("The requested area is outside the UTM latitude range.")
    normalized_lon = (midpoint_lon + 180) % 360 - 180
    zone = min(60, max(1, int((normalized_lon + 180) // 6) + 1))
    epsg = (32600 if midpoint_lat >= 0 else 32700) + zone
    return f"EPSG:{epsg}"


def copernicus_tile_names(study_area):
    """List 1-degree GLO-30 tile object names intersecting the study area."""
    names = set()
    for part in study_area["parts"]:
        south_index = math.floor(part["south"])
        north_index = math.floor(math.nextafter(part["north"], -math.inf))
        west_index = math.floor(part["west"])
        east_index = math.floor(math.nextafter(part["east"], -math.inf))
        for lat_index in range(south_index, north_index + 1):
            latitude = f"{'N' if lat_index >= 0 else 'S'}{abs(lat_index):02d}_00"
            for lon_index in range(west_index, east_index + 1):
                longitude = f"{'E' if lon_index >= 0 else 'W'}{abs(lon_index):03d}_00"
                names.add(f"Copernicus_DSM_COG_10_{latitude}_{longitude}_DEM")
    return sorted(names)

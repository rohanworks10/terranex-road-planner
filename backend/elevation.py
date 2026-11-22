"""Fetch ground elevation (metres above sea level) from the Open-Meteo Elevation API."""
import math

import httpx

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
MAX_POINTS = 100  # the service accepts at most 100 points per request


def get_elevations(points):
    """points: list of (latitude, longitude). Returns a list of elevations in metres."""
    if not points:
        raise ValueError("Give at least one point.")
    if len(points) > MAX_POINTS:
        raise ValueError(f"At most {MAX_POINTS} points per request.")
    for lat, lon in points:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError(f"Invalid coordinate: {lat}, {lon}")

    params = {
        "latitude": ",".join(str(lat) for lat, _ in points),
        "longitude": ",".join(str(lon) for _, lon in points),
    }
    response = httpx.get(ELEVATION_URL, params=params, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or "elevation" not in payload:
        raise ValueError("The service response did not contain elevation values.")
    elevations = payload["elevation"]
    if not isinstance(elevations, list):
        raise ValueError("The service returned invalid elevation values.")
    if len(elevations) != len(points):
        raise ValueError("The service returned an unexpected number of values.")
    for value in elevations:
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError("The service returned a missing or invalid elevation value.")
    return [float(value) for value in elevations]
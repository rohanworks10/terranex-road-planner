"""Sample points along a straight line and measure how steep the ground is."""
import math

from elevation import get_elevations

EARTH_RADIUS_M = 6371000
DEFAULT_SAMPLE_COUNT = 100


def slope_percent_to_degrees(slope_percent):
    return math.degrees(math.atan(slope_percent / 100))


def slope_degrees_to_percent(slope_degrees):
    return math.tan(math.radians(slope_degrees)) * 100


def distance_m(a, b):
    """Distance in metres between two (lat, lon) points (haversine formula)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def sample_line(start, end, n_points=DEFAULT_SAMPLE_COUNT):
    """n_points evenly spaced (lat, lon) points from start to end, both included."""
    if n_points < 2:
        raise ValueError("Need at least 2 points.")
    return [
        (start[0] + (end[0] - start[0]) * i / (n_points - 1),
         start[1] + (end[1] - start[1]) * i / (n_points - 1))
        for i in range(n_points)
    ]


def slope_profile(start, end, n_points=DEFAULT_SAMPLE_COUNT):
    """Elevation and slope along the straight line from start to end."""
    route_distance_m = distance_m(start, end)
    if route_distance_m == 0:
        raise ValueError("Start and end are the same place.")

    points = sample_line(start, end, n_points)
    elevations = get_elevations(points)
    if len(elevations) != n_points:
        raise ValueError("The service returned an unexpected number of values.")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in elevations):
        raise ValueError("Elevation values must be finite numbers.")

    segment_runs_m = [
        distance_m(points[i], points[i + 1])
        for i in range(n_points - 1)
    ]
    if any(run == 0 for run in segment_runs_m):
        raise ValueError("Sample points must be distinct.")

    segment_grade_percent = [
        (elevations[i + 1] - elevations[i]) / segment_runs_m[i] * 100
        for i in range(n_points - 1)
    ]
    segment_angles_degrees = [
        slope_percent_to_degrees(grade)
        for grade in segment_grade_percent
    ]
    average_absolute_segment_percent = sum(
        abs(grade) for grade in segment_grade_percent
    ) / len(segment_grade_percent)
    average_absolute_segment_degrees = sum(
        abs(angle) for angle in segment_angles_degrees
    ) / len(segment_angles_degrees)
    steepest_segment_percent = max(abs(grade) for grade in segment_grade_percent)
    steepest_segment_degrees = max(abs(angle) for angle in segment_angles_degrees)

    endpoint_grade_percent = (elevations[-1] - elevations[0]) / route_distance_m * 100
    endpoint_slope_degrees = slope_percent_to_degrees(endpoint_grade_percent)

    return {
        "distance_m": round(route_distance_m, 1),
        "elevations_m": elevations,
        "sample_count": n_points,
        "sample_interval_distance_m": round(
            sum(segment_runs_m) / len(segment_runs_m), 1
        ),
        "endpoint_slope_percent": endpoint_grade_percent,
        "endpoint_slope_degrees": endpoint_slope_degrees,
        "endpoint_slope_magnitude_degrees": abs(endpoint_slope_degrees),
        "average_absolute_segment_slope_percent": round(average_absolute_segment_percent, 1),
        "average_absolute_segment_slope_degrees": round(average_absolute_segment_degrees, 1),
        "steepest_segment_slope_percent": round(steepest_segment_percent, 1),
        "steepest_segment_slope_degrees": round(steepest_segment_degrees, 1),
        # Retain the original response fields for existing clients.
        "average_slope_percent": round(average_absolute_segment_percent, 1),
        "max_slope_percent": round(steepest_segment_percent, 1),
        "average_slope_degrees": round(
            slope_percent_to_degrees(average_absolute_segment_percent), 1
        ),
    }
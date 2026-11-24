import logging

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from dem import (
    DemDataError,
    TerrainNotPreparedError,
    cached_terrain_files,
    prepare_terrain,
)
from routing import NoRouteError, generate_route_alternatives
from schemas import RouteGenerationRequest, RouteRequest, StudyAreaRequest
from terrain import slope_degrees_to_percent, slope_profile
from config import SLOPE_TOLERANCE_DEGREES

app = FastAPI(title="Road Corridor Planner API")
api = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

# Allow the React dev page (running on port 5173) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {"message": "Road Corridor Planner API is running"}


@api.get("/health")
def health():
    return {"status": "ok"}


@api.post("/plan")
def plan(request: RouteRequest):
    """
    Receive start, end and a user-supplied slope.
    Call terrain analysis to get real elevation data, then:
      - Return distance, calculated slope values.
      - Compare user slope with calculated slope.
      - Warn if the difference exceeds the configured tolerance.
    """
    start = (request.start.lat, request.start.lon)
    end = (request.end.lat, request.end.lon)

    # --- Run real terrain analysis ---
    try:
        terrain = slope_profile(start, end)
    except ValueError as exc:
        # start == end, or bad coordinates caught inside terrain/elevation
        return {
            "status": "error",
            "error": str(exc),
        }
    except Exception as exc:
        # Network failure, Open-Meteo unavailable, unexpected response, etc.
        return {
            "status": "error",
            "error": f"Could not fetch elevation data: {str(exc)}",
        }

    # --- Slope comparison ---
    user_slope_deg = request.endpoint_slope_degrees
    calc_slope_deg = terrain["endpoint_slope_magnitude_degrees"]
    precise_difference_deg = abs(user_slope_deg - calc_slope_deg)
    slope_warning = precise_difference_deg > SLOPE_TOLERANCE_DEGREES

    return {
        "status": "ok",
        # Terrain measurements
        "distance_m": terrain["distance_m"],
        "sample_count": terrain["sample_count"],
        "sample_interval_distance_m": terrain["sample_interval_distance_m"],
        "endpoint_slope_percent": terrain["endpoint_slope_percent"],
        "endpoint_slope_degrees": terrain["endpoint_slope_degrees"],
        "endpoint_slope_magnitude_degrees": calc_slope_deg,
        "average_absolute_segment_slope_percent": terrain["average_absolute_segment_slope_percent"],
        "average_absolute_segment_slope_degrees": terrain["average_absolute_segment_slope_degrees"],
        "steepest_segment_slope_percent": terrain["steepest_segment_slope_percent"],
        "steepest_segment_slope_degrees": terrain["steepest_segment_slope_degrees"],
        # Legacy terrain names retained for existing clients.
        "average_slope_percent": terrain["average_slope_percent"],
        "max_slope_percent": terrain["max_slope_percent"],
        "average_slope_degrees": terrain["average_slope_degrees"],
        # The entered value and comparison are both endpoint slope magnitudes in degrees.
        "user_slope_degrees": user_slope_deg,
        "user_slope_percent": round(slope_degrees_to_percent(user_slope_deg), 1),
        "calculated_slope_degrees": calc_slope_deg,
        "comparison_metric": "endpoint_slope_magnitude",
        "slope_difference_degrees": round(precise_difference_deg, 2),
        # Warning
        "slope_warning": slope_warning,
        "slope_tolerance_degrees": SLOPE_TOLERANCE_DEGREES,
    }


@api.post("/terrain/prepare")
def prepare_terrain_endpoint(request: StudyAreaRequest):
    """Create a buffered, request-specific DEM and terrain-cost grid."""
    start = (request.start.lat, request.start.lon)
    end = (request.end.lat, request.end.lon)
    try:
        return prepare_terrain(start, end, request.buffer_m)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DemDataError as exc:
        logger.exception("Terrain preparation failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@api.post("/routes")
def generate_routes_endpoint(request: RouteGenerationRequest):
    """Generate two routes from an already prepared terrain grid."""
    start = (request.start.lat, request.start.lon)
    end = (request.end.lat, request.end.lon)
    try:
        raster_paths = cached_terrain_files(start, end, request.buffer_m)
        return generate_route_alternatives(
            start,
            end,
            raster_paths,
            snap_radius_m=request.snap_radius_m,
        )
    except TerrainNotPreparedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NoRouteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DemDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


app.include_router(api)

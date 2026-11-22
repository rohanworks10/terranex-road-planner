from pydantic import AliasChoices, BaseModel, Field


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    start: Point
    end: Point
    endpoint_slope_degrees: float = Field(
        gt=0,
        lt=90,
        validation_alias=AliasChoices("endpoint_slope_degrees", "average_slope_degrees"),
    )


class StudyAreaRequest(BaseModel):
    start: Point
    end: Point
    buffer_m: float = Field(default=5000, gt=0)


class RouteGenerationRequest(BaseModel):
    start: Point
    end: Point
    buffer_m: float = Field(default=5000, gt=0)
    snap_radius_m: float = Field(default=90, gt=0)
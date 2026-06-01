"""FastAPI wrapper for the NBA natural-language search engine."""

from functools import lru_cache
from math import isfinite
from time import perf_counter

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from search_engine import SearchEngine
DEFAULT_SEASON = "2025-26"


class QueryRequest(BaseModel):
    """Client-provided search settings."""

    query: str = Field(min_length=1, examples=["harden clutch misses q4"])
    season: str = DEFAULT_SEASON
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    use_play_by_play: bool = False


class QueryResponse(BaseModel):
    """JSON-safe search response."""

    query: str
    interpretation: str
    latency_ms: int
    raw_result_count: int
    filtered_result_count: int
    limit: int
    offset: int
    warnings: list[str]
    user_agent: str
    query_params: dict
    results: list[dict]


app = FastAPI(
    title="CourtVision NBA Search API",
    description="Natural-language NBA video search powered by nba_api.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=32)
def get_engine(season: str, use_play_by_play: bool) -> SearchEngine:
    """Reuse engines so spaCy matchers are not rebuilt on every request."""
    return SearchEngine(season=season, use_play_by_play=use_play_by_play)


def to_json_safe(value):
    """Convert pandas/numpy values into strict JSON-compatible primitives."""
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def dataframe_records(frame: pd.DataFrame, offset: int, limit: int) -> list[dict]:
    """Return paged DataFrame records that FastAPI can serialize safely."""
    if frame.empty:
        return []

    page = frame.iloc[offset : offset + limit].copy()
    return [
        {column: to_json_safe(value) for column, value in row.items()}
        for row in page.to_dict(orient="records")
    ]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    started_at = perf_counter()
    engine = get_engine(request.season, request.use_play_by_play)
    result = engine.search(request.query)
    latency_ms = round((perf_counter() - started_at) * 1000)

    return QueryResponse(
        query=result.query,
        interpretation=result.interpretation,
        latency_ms=latency_ms,
        raw_result_count=result.raw_result_count,
        filtered_result_count=result.result_count,
        limit=request.limit,
        offset=request.offset,
        warnings=result.warnings,
        user_agent=result.user_agent,
        query_params=result.query_params,
        results=dataframe_records(result.results, request.offset, request.limit),
    )

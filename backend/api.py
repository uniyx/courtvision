"""FastAPI wrapper for the NBA natural-language search engine."""

from collections import OrderedDict
from functools import lru_cache
from math import isfinite
from time import perf_counter
from time import time
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, HTTPException, Query as QueryParam
from fastapi.middleware.cors import CORSMiddleware
from nba_api.stats.endpoints import commonteamroster, leaguedashplayerstats, leaguestandingsv3
from pydantic import BaseModel, Field

from backend.nba_client import build_nba_stats_headers
from backend.names.aliases import PLAYER_ALIASES, TEAM_ALIASES
from backend.names.keywords import (
    CONTEXT_KEYWORDS,
    MISS_KEYWORDS,
    MONTH_KEYWORDS,
    PERIOD_KEYWORDS,
    PHRASE_KEYWORDS,
    SCORE_CONTEXT_KEYWORDS,
    SEASON_TYPE_KEYWORDS,
    SHOT_KEYWORDS,
    TIME_CONTEXT_KEYWORDS,
)
from backend.search_engine import SearchEngine


DEFAULT_SEASON = "2025-26"
SUPPORTED_SEASONS = [
    "2025-26",
    "2024-25",
    "2023-24",
    "2022-23",
    "2021-22",
    "2020-21",
    "2019-20",
    "2018-19",
]

SEARCH_CACHE_TTL_SECONDS = 30 * 60
SEARCH_CACHE_MAX_ITEMS = 32
search_cache = OrderedDict()
TEAM_BROWSER_CACHE_TTL_SECONDS = 30 * 60
TEAM_BROWSER_CACHE_MAX_ITEMS = 8
team_browser_cache = OrderedDict()
TEAM_ROSTER_CACHE_TTL_SECONDS = 30 * 60
TEAM_ROSTER_CACHE_MAX_ITEMS = 128
team_roster_cache = OrderedDict()

class QueryRequest(BaseModel):
    """Client-provided search settings."""

    query: str = Field(min_length=1, examples=["harden clutch misses q4"])
    season: str = DEFAULT_SEASON
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    use_play_by_play: bool = False


class QueryResponse(BaseModel):
    """JSON-safe search response."""

    search_id: str
    query: str
    interpretation: str
    latency_ms: int
    raw_result_count: int
    filtered_result_count: int
    limit: int
    offset: int
    has_more: bool
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


def sorted_mapping(mapping):
    return dict(sorted(mapping.items(), key=lambda item: item[0]))


def scalar_or_default(value, default=None):
    if value is None:
        return default
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not isfinite(value):
        return default
    return value


def row_value(row, keys, default=None):
    for key in keys:
        if key in row:
            value = scalar_or_default(row[key], default=None)
            if value is not None and value != "":
                return value
    return default


def team_logo_url(team_id):
    return f"https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg"


def build_player_stats_record(row):
    return {
        "gp": row_value(row, ["GP"], 0),
        "min": row_value(row, ["MIN"], 0),
        "fgm": row_value(row, ["FGM"], 0),
        "fga": row_value(row, ["FGA"], 0),
        "fg_pct": row_value(row, ["FG_PCT"], ""),
        "fg3m": row_value(row, ["FG3M"], 0),
        "fg3a": row_value(row, ["FG3A"], 0),
        "fg3_pct": row_value(row, ["FG3_PCT"], ""),
        "ftm": row_value(row, ["FTM"], 0),
        "fta": row_value(row, ["FTA"], 0),
        "ft_pct": row_value(row, ["FT_PCT"], ""),
        "reb": row_value(row, ["REB"], 0),
        "ast": row_value(row, ["AST"], 0),
        "stl": row_value(row, ["STL"], 0),
        "blk": row_value(row, ["BLK"], 0),
        "tov": row_value(row, ["TOV"], 0),
        "pts": row_value(row, ["PTS"], 0),
        "plus_minus": row_value(row, ["PLUS_MINUS"], 0),
    }


def build_player_record(row, stats_by_player_id):
    player_id = row_value(row, ["PLAYER_ID"])
    return {
        "id": player_id,
        "name": row_value(row, ["PLAYER"], "Unknown Player"),
        "slug": row_value(row, ["PLAYER_SLUG"]),
        "number": row_value(row, ["NUM"], ""),
        "position": row_value(row, ["POSITION"], ""),
        "height": row_value(row, ["HEIGHT"], ""),
        "weight": row_value(row, ["WEIGHT"], ""),
        "age": row_value(row, ["AGE"], ""),
        "experience": row_value(row, ["EXP"], ""),
        "school": row_value(row, ["SCHOOL"], ""),
        "stats": stats_by_player_id.get(player_id, build_player_stats_record({})),
    }


def fetch_team_player_stats(team_id, season):
    response = leaguedashplayerstats.LeagueDashPlayerStats(
        team_id_nullable=team_id,
        season=season,
        season_type_all_star="Regular Season",
        per_mode_detailed="Totals",
        measure_type_detailed_defense="Base",
        headers=build_nba_stats_headers(rotate_user_agent=True),
        timeout=20,
    )
    frame = response.get_data_frames()[0]
    return {
        row_value(row, ["PLAYER_ID"]): build_player_stats_record(row)
        for row in frame.to_dict(orient="records")
    }


def fetch_team_roster(team_id, season):
    roster_response = commonteamroster.CommonTeamRoster(
        team_id=team_id,
        season=season,
        headers=build_nba_stats_headers(rotate_user_agent=True),
        timeout=20,
    )
    stats_by_player_id = fetch_team_player_stats(team_id, season)
    roster_frame = roster_response.get_data_frames()[0]
    players = [build_player_record(row, stats_by_player_id) for row in roster_frame.to_dict(orient="records")]
    return sorted(players, key=lambda player: (-(player["stats"]["gp"] or 0), player["name"] or ""))


def build_team_record(row):
    team_id = row_value(row, ["TeamID"])
    abbreviation = row_value(row, ["TeamSlug"], "").upper()
    city = row_value(row, ["TeamCity"], "")
    nickname = row_value(row, ["TeamName"], "")
    conference = row_value(row, ["Conference"], "")
    conference_rank = row_value(row, ["PlayoffRank"], 999)

    return {
        "id": team_id,
        "abbreviation": abbreviation,
        "city": city,
        "nickname": nickname,
        "full_name": f"{city} {nickname}".strip(),
        "conference": conference,
        "conference_rank": conference_rank,
        "division": row_value(row, ["Division"], ""),
        "division_rank": row_value(row, ["DivisionRank"]),
        "wins": row_value(row, ["WINS"], 0),
        "losses": row_value(row, ["LOSSES"], 0),
        "win_pct": row_value(row, ["WinPCT"], ""),
        "record": row_value(row, ["Record"], ""),
        "home": row_value(row, ["HOME"], ""),
        "road": row_value(row, ["ROAD"], ""),
        "last_10": row_value(row, ["L10"], ""),
        "conference_record": row_value(row, ["ConferenceRecord"], ""),
        "division_record": row_value(row, ["DivisionRecord"], ""),
        "points_pg": row_value(row, ["PointsPG"], ""),
        "opp_points_pg": row_value(row, ["OppPointsPG"], ""),
        "diff_points_pg": row_value(row, ["DiffPointsPG"], ""),
        "current_streak": row_value(row, ["strCurrentStreak", "CurrentStreak"], ""),
        "logo_url": team_logo_url(team_id) if team_id else None,
    }


def prune_team_browser_cache():
    now = time()
    expired_keys = [
        cache_key
        for cache_key, entry in team_browser_cache.items()
        if now - entry["created_at"] > TEAM_BROWSER_CACHE_TTL_SECONDS
    ]
    for cache_key in expired_keys:
        team_browser_cache.pop(cache_key, None)

    while len(team_browser_cache) > TEAM_BROWSER_CACHE_MAX_ITEMS:
        team_browser_cache.popitem(last=False)


def prune_team_roster_cache():
    now = time()
    expired_keys = [
        cache_key
        for cache_key, entry in team_roster_cache.items()
        if now - entry["created_at"] > TEAM_ROSTER_CACHE_TTL_SECONDS
    ]
    for cache_key in expired_keys:
        team_roster_cache.pop(cache_key, None)

    while len(team_roster_cache) > TEAM_ROSTER_CACHE_MAX_ITEMS:
        team_roster_cache.popitem(last=False)


def fetch_team_browser(season):
    response = leaguestandingsv3.LeagueStandingsV3(
        season=season,
        season_type="Regular Season",
        league_id="00",
        headers=build_nba_stats_headers(rotate_user_agent=True),
        timeout=20,
    )
    standings = response.get_data_frames()[0]
    teams = [build_team_record(row) for row in standings.to_dict(orient="records")]

    def sort_key(team):
        return (team["conference_rank"] or 999, -(team["wins"] or 0), team["full_name"])

    east = sorted([team for team in teams if team["conference"] == "East"], key=sort_key)
    west = sorted([team for team in teams if team["conference"] == "West"], key=sort_key)
    return {
        "season": season,
        "conferences": [
            {"name": "Eastern Conference", "conference": "East", "teams": east},
            {"name": "Western Conference", "conference": "West", "teams": west},
        ],
        "warnings": [],
    }


def get_team_browser(season):
    prune_team_browser_cache()
    entry = team_browser_cache.get(season)
    if entry:
        entry["created_at"] = time()
        team_browser_cache.move_to_end(season)
        return entry["payload"]

    try:
        payload = fetch_team_browser(season)
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"NBA standings request failed for {season}: {type(error).__name__}: {error}",
        ) from error

    team_browser_cache[season] = {"created_at": time(), "payload": payload}
    return payload


def get_team_roster(team_id, season):
    prune_team_roster_cache()
    cache_key = (season, int(team_id))
    entry = team_roster_cache.get(cache_key)
    if entry:
        entry["created_at"] = time()
        team_roster_cache.move_to_end(cache_key)
        return entry["payload"]

    try:
        players = fetch_team_roster(team_id, season)
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"NBA roster request failed for team {team_id} in {season}: {type(error).__name__}: {error}",
        ) from error

    payload = {"season": season, "team_id": team_id, "players": players}
    team_roster_cache[cache_key] = {"created_at": time(), "payload": payload}
    return payload


def prune_search_cache():
    now = time()
    expired_ids = [
        search_id
        for search_id, entry in search_cache.items()
        if now - entry["created_at"] > SEARCH_CACHE_TTL_SECONDS
    ]
    for search_id in expired_ids:
        search_cache.pop(search_id, None)

    while len(search_cache) > SEARCH_CACHE_MAX_ITEMS:
        search_cache.popitem(last=False)


def cache_search_result(result):
    prune_search_cache()
    search_id = uuid4().hex
    search_cache[search_id] = {
        "created_at": time(),
        "result": result,
    }
    return search_id


def get_cached_search_result(search_id):
    prune_search_cache()
    entry = search_cache.get(search_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Search result cache entry was not found or has expired.")

    entry["created_at"] = time()
    search_cache.move_to_end(search_id)
    return entry["result"]


def build_query_response(search_id, result, offset, limit, latency_ms):
    return QueryResponse(
        search_id=search_id,
        query=result.query,
        interpretation=result.interpretation,
        latency_ms=latency_ms,
        raw_result_count=result.raw_result_count,
        filtered_result_count=result.result_count,
        limit=limit,
        offset=offset,
        has_more=offset + limit < result.result_count,
        warnings=result.warnings,
        user_agent=result.user_agent,
        query_params=result.query_params,
        results=dataframe_records(result.results, offset, limit),
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/seasons")
def seasons():
    return {"default": DEFAULT_SEASON, "seasons": SUPPORTED_SEASONS}


@app.get("/vocabulary")
def vocabulary():
    """Expose the live alias and keyword dictionaries used by the parser."""
    groups = {
        "player_aliases": sorted_mapping(PLAYER_ALIASES),
        "team_aliases": sorted_mapping(TEAM_ALIASES),
        "context_keywords": sorted_mapping(CONTEXT_KEYWORDS),
        "shot_keywords": sorted_mapping(SHOT_KEYWORDS),
        "phrase_keywords": sorted_mapping(PHRASE_KEYWORDS),
        "miss_keywords": sorted(MISS_KEYWORDS),
        "time_context_keywords": sorted_mapping(TIME_CONTEXT_KEYWORDS),
        "score_context_keywords": sorted_mapping(SCORE_CONTEXT_KEYWORDS),
        "season_type_keywords": sorted_mapping(SEASON_TYPE_KEYWORDS),
        "month_keywords": sorted_mapping(MONTH_KEYWORDS),
        "period_keywords": sorted_mapping(PERIOD_KEYWORDS),
    }
    return {
        "description": "Aliases and keyword maps are imported directly from backend/names/*.py.",
        "counts": {name: len(values) for name, values in groups.items()},
        "groups": groups,
    }


@app.get("/teams")
def teams(season: str = DEFAULT_SEASON):
    """Return standings-ranked teams for the team browser."""
    if season not in SUPPORTED_SEASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported season '{season}'. Supported seasons: {', '.join(SUPPORTED_SEASONS)}",
        )
    return get_team_browser(season)


@app.get("/teams/{team_id}/roster")
def team_roster(team_id: int, season: str = DEFAULT_SEASON):
    """Return one team's roster for the selected season."""
    if season not in SUPPORTED_SEASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported season '{season}'. Supported seasons: {', '.join(SUPPORTED_SEASONS)}",
        )
    return get_team_roster(team_id, season)


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    started_at = perf_counter()
    if request.season not in SUPPORTED_SEASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported season '{request.season}'. Supported seasons: {', '.join(SUPPORTED_SEASONS)}",
        )

    engine = get_engine(request.season, request.use_play_by_play)
    try:
        result = engine.search(request.query)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    latency_ms = round((perf_counter() - started_at) * 1000)
    search_id = cache_search_result(result)

    return build_query_response(search_id, result, request.offset, request.limit, latency_ms)


@app.get("/query/{search_id}", response_model=QueryResponse)
def query_page(
    search_id: str,
    offset: int = QueryParam(default=0, ge=0),
    limit: int = QueryParam(default=25, ge=1, le=100),
):
    started_at = perf_counter()
    result = get_cached_search_result(search_id)
    latency_ms = round((perf_counter() - started_at) * 1000)
    return build_query_response(search_id, result, offset, limit, latency_ms)

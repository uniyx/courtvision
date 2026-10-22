"""NBA Stats API request helpers.

The stats endpoints are unofficial and sensitive to request shape, so this
module centralizes browser-like headers, params, and retry behavior.
"""

import logging
from datetime import date
from time import sleep

from nba_api.stats.endpoints import commonallplayers
from nba_api.stats.endpoints import playbyplayv3
from nba_api.stats.endpoints import videodetailsasset


logger = logging.getLogger(__name__)


NBA_STATS_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Host": "stats.nba.com",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


def season_label(start_year):
    """Format an NBA season such as 2026 -> '2026-27'."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def current_season(today=None):
    """NBA seasons start in October, so January-September belong to the season that began last year."""
    today = today or date.today()
    return season_label(today.year if today.month >= 10 else today.year - 1)


QUERY_PARAMS = {
    "team_id": 0,
    "context_measure_detailed": "PTS",
    "season": current_season(),
    "season_type_all_star": "Regular Season",
    "last_n_games": 105,
    "month": 0,
    "opponent_team_id": 0,
    "period": 0,
    "league_id_nullable": "00",
}


def build_nba_stats_headers(
    referer="https://www.nba.com/",
):
    """Build headers for stats.nba.com requests."""
    headers = NBA_STATS_HEADERS.copy()
    headers["Referer"] = referer
    return headers


def build_query_params(
    player,
    context_measure=None,
    season=None,
    season_type=None,
    opponent_team_id=0,
    month=None,
    period=None,
):
    """Build VideoDetailsAsset params from resolved player/query fields."""
    params = QUERY_PARAMS.copy()
    params["player_id"] = player["id"]
    if context_measure:
        params["context_measure_detailed"] = context_measure
    if season:
        params["season"] = season
    if season_type:
        params["season_type_all_star"] = season_type
    params["opponent_team_id"] = opponent_team_id
    if month is not None:
        params["month"] = month
    if period is not None:
        params["period"] = period
    return params


def _request_with_retries(request, retries, warning_context, failure_context):
    last_error = None

    for attempt in range(retries + 1):
        try:
            return request()
        except Exception as error:
            last_error = error
            logger.warning(
                "%s attempt=%s/%s error=%r",
                warning_context,
                attempt + 1,
                retries + 1,
                error,
            )
            if attempt < retries:
                sleep(1 + attempt)

    error_detail = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"
    raise RuntimeError(f"{failure_context}: {error_detail}") from last_error


def fetch_video_details(
    player,
    context_measure=None,
    season=None,
    season_type=None,
    opponent_team_id=0,
    month=None,
    period=None,
    headers=None,
    retries=2,
    timeout=30,
):
    """Fetch raw VideoDetailsAsset data, retrying transient non-JSON NBA responses."""
    params = build_query_params(
        player,
        context_measure=context_measure,
        season=season,
        season_type=season_type,
        opponent_team_id=opponent_team_id,
        month=month,
        period=period,
    )
    return _request_with_retries(
        lambda: videodetailsasset.VideoDetailsAsset(
            **params,
            headers=headers or build_nba_stats_headers(),
            timeout=timeout,
        ).get_dict(),
        retries,
        warning_context=(
            f"VideoDetailsAsset failed for player={player['full_name']} context={context_measure} "
            f"season={season} season_type={season_type} opponent_team_id={opponent_team_id} "
            f"month={month} period={period}"
        ),
        failure_context=f"NBA video details request failed for {player['full_name']} ({context_measure})",
    )


def fetch_play_by_play(game_id, headers=None, retries=2, timeout=10):
    """Fetch PlayByPlayV3 rows for one game so video rows can be enriched with clock data."""
    return _request_with_retries(
        lambda: playbyplayv3.PlayByPlayV3(
            game_id=game_id,
            headers=headers or build_nba_stats_headers(),
            timeout=timeout,
        ).get_data_frames()[0],
        retries,
        warning_context=f"PlayByPlayV3 failed for game_id={game_id} timeout={timeout}",
        failure_context=f"NBA play-by-play request failed for game {game_id}",
    )


def fetch_all_players(headers=None, retries=1, timeout=20):
    """Fetch every NBA player with FROM_YEAR/TO_YEAR, so rookies and past seasons resolve."""
    return _request_with_retries(
        lambda: commonallplayers.CommonAllPlayers(
            is_only_current_season=0,
            headers=headers or build_nba_stats_headers(),
            timeout=timeout,
        ).get_data_frames()[0],
        retries,
        warning_context=f"CommonAllPlayers failed timeout={timeout}",
        failure_context="NBA player list request failed",
    )

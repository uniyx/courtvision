"""NBA Stats API request helpers.

The stats endpoints are unofficial and sensitive to request shape, so this
module centralizes browser-like headers, user-agent generation, params, and
retry behavior.
"""

from time import sleep

from fake_useragent import UserAgent
from nba_api.stats.endpoints import videodetailsasset


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


FALLBACK_USER_AGENT = NBA_STATS_HEADERS["User-Agent"]


def build_desktop_user_agent():
    """Generate a desktop Chrome/Firefox UA, falling back to a known-good string."""
    try:
        user_agent = UserAgent(
            browsers=["Chrome", "Firefox"],
            os=["Windows", "Mac OS X"],
            platforms=["desktop"],
            fallback=FALLBACK_USER_AGENT,
        )
        return user_agent.random
    except Exception:
        return FALLBACK_USER_AGENT


QUERY_PARAMS = {
    "team_id": 0,
    "context_measure_detailed": "PTS",
    "season": "2025-26",
    "season_type_all_star": "Regular Season",
    "last_n_games": 200,
    "month": 0,
    "opponent_team_id": 0,
    "period": 0,
    "league_id_nullable": "00",
}


def build_nba_stats_headers(
    referer="https://www.nba.com/",
    rotate_user_agent=False,
):
    """Build headers for stats.nba.com requests."""
    headers = NBA_STATS_HEADERS.copy()
    headers["Referer"] = referer
    if rotate_user_agent:
        headers["User-Agent"] = build_desktop_user_agent()
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


def fetch_video_details(
    player,
    context_measure=None,
    season=None,
    season_type=None,
    opponent_team_id=0,
    month=None,
    period=None,
    headers=None,
    rotate_user_agent=False,
    retries=2,
):
    """Fetch raw VideoDetailsAsset data, retrying transient non-JSON NBA responses."""
    last_error = None

    for attempt in range(retries + 1):
        try:
            # nba_api does the final HTTP call, but we supply the headers and
            # full parameter set so the rest of the project stays independent
            # from endpoint quirks.
            response = videodetailsasset.VideoDetailsAsset(
                **build_query_params(
                    player,
                    context_measure=context_measure,
                    season=season,
                    season_type=season_type,
                    opponent_team_id=opponent_team_id,
                    month=month,
                    period=period,
                ),
                headers=headers or build_nba_stats_headers(rotate_user_agent=rotate_user_agent),
                timeout=30,
            )
            return response.get_dict()
        except Exception as error:
            last_error = error
            if attempt == retries:
                break
            sleep(1 + attempt)

    raise RuntimeError(f"NBA API request failed for {player['full_name']} ({context_measure}).") from last_error

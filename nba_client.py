from random import choice
from time import sleep

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


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:151.0) Gecko/20100101 Firefox/151.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
]


def choose_user_agent():
    return choice(USER_AGENTS)


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
    headers = NBA_STATS_HEADERS.copy()
    headers["Referer"] = referer
    if rotate_user_agent:
        headers["User-Agent"] = choose_user_agent()
    return headers


def build_query_params(
    player,
    context_measure=None,
    season_type=None,
    opponent_team_id=0,
    month=None,
    period=None,
):
    params = QUERY_PARAMS.copy()
    params["player_id"] = player["id"]
    if context_measure:
        params["context_measure_detailed"] = context_measure
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
    season_type=None,
    opponent_team_id=0,
    month=None,
    period=None,
    rotate_user_agent=False,
    retries=2,
):
    """Fetch raw VideoDetailsAsset data, retrying transient non-JSON NBA responses."""
    last_error = None

    for attempt in range(retries + 1):
        try:
            response = videodetailsasset.VideoDetailsAsset(
                **build_query_params(
                    player,
                    context_measure=context_measure,
                    season_type=season_type,
                    opponent_team_id=opponent_team_id,
                    month=month,
                    period=period,
                ),
                headers=build_nba_stats_headers(rotate_user_agent=rotate_user_agent),
                timeout=30,
            )
            return response.get_dict()
        except Exception as error:
            last_error = error
            if attempt == retries:
                break
            sleep(1 + attempt)

    raise RuntimeError(f"NBA API request failed for {player['full_name']} ({context_measure}).") from last_error

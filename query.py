from pathlib import Path
from random import choice
from re import findall
from urllib.parse import urlencode

import pandas as pd
from nba_api.stats.endpoints import videodetailsasset
from nba_api.stats.static import players

from keywords import CONTEXT_KEYWORDS, MISS_KEYWORDS, SHOT_KEYWORDS


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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15.5; rv:151.0) Gecko/20100101 Firefox/151.0",
]


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


PLAYER_NAME = "Cade Cunningham"
QUERY_TEXT = "dunks"


def build_nba_stats_headers(referer="https://www.nba.com/", rotate_user_agent=False):
    headers = NBA_STATS_HEADERS.copy()
    headers["Referer"] = referer
    if rotate_user_agent:
        headers["User-Agent"] = choice(USER_AGENTS)
    return headers


def normalize_name(value):
    return " ".join(value.lower().split())


def tokenize_query(query_text):
    return findall(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)?", query_text.lower())


def parse_keywords(query_text):
    tokens = tokenize_query(query_text)
    context_measure = "PTS"
    shot_specifiers = set()
    miss_filter = False

    for token in tokens:
        if token in CONTEXT_KEYWORDS:
            context_measure = CONTEXT_KEYWORDS[token]
        if token in SHOT_KEYWORDS:
            shot_specifiers.add(SHOT_KEYWORDS[token])
        if token in MISS_KEYWORDS:
            miss_filter = True

    if shot_specifiers and context_measure == "PTS":
        context_measure = "PTS"

    return {
        "context_measure": context_measure,
        "shot_specifiers": shot_specifiers,
        "miss_filter": miss_filter,
    }


def get_player_lookup():
    player_lookup = {}
    for player in players.get_active_players():
        player_lookup[normalize_name(player["full_name"])] = player
    return player_lookup


def format_player_options(matches):
    return ", ".join(player["full_name"] for player in matches[:8])


def resolve_player(player_name):
    normalized = normalize_name(player_name)
    player_lookup = get_player_lookup()

    if normalized in player_lookup:
        return player_lookup[normalized]

    matches = [
        player
        for player in player_lookup.values()
        if normalized in {normalize_name(player["first_name"]), normalize_name(player["last_name"])}
    ]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        raise ValueError(f"Ambiguous player name '{player_name}'. Matches: {format_player_options(matches)}")

    raise ValueError(f"No active NBA player found for '{player_name}'.")


def build_query_params(player_name=PLAYER_NAME, context_measure=None):
    player = resolve_player(player_name)
    params = QUERY_PARAMS.copy()
    params["player_id"] = player["id"]
    if context_measure:
        params["context_measure_detailed"] = context_measure
    return params


def build_event_link(row):
    game_id = str(row["Game_ID"])
    season_start = 2000 + int(game_id[3:5])
    params = {
        "GameEventID": row["Event_Index"],
        "GameID": game_id,
        "Season": f"{season_start}-{season_start + 1}",
        "flag": 1,
        "title": row["Description"],
    }
    return f"https://www.nba.com/stats/events?{urlencode(params)}"


def fetch_video_details(player_name=PLAYER_NAME, context_measure=None, rotate_user_agent=False):
    response = videodetailsasset.VideoDetailsAsset(
        **build_query_params(player_name, context_measure=context_measure),
        headers=build_nba_stats_headers(rotate_user_agent=rotate_user_agent),
        timeout=30,
    )
    return response.get_dict()


def calculate_point_change(row):
    home_change = row["Home_Points_After"] - row["Home_Points_Before"]
    visitor_change = row["Visitor_Points_After"] - row["Visitor_Points_Before"]
    return max(home_change, visitor_change)


def process_videos(video_details):
    result_sets = video_details["resultSets"]
    playlist = result_sets["playlist"]
    video_urls = result_sets["Meta"]["videoUrls"]

    print(f"playlist rows: {len(playlist)}")
    print(f"video URL rows: {len(video_urls)}")

    if not playlist:
        return pd.DataFrame()

    df = pd.DataFrame(playlist)
    df["Video_URL"] = video_urls
    df["Game_Date"] = pd.to_datetime(
        df["y"].astype(str)
        + "-"
        + df["m"].astype(str).str.zfill(2)
        + "-"
        + df["d"].astype(str).str.zfill(2)
    )

    formatted = df.rename(
        columns={
            "gi": "Game_ID",
            "ei": "Event_Index",
            "gc": "Game_Code",
            "p": "Period",
            "dsc": "Description",
            "ha": "Home_Team",
            "va": "Visitor_Team",
            "hpb": "Home_Points_Before",
            "hpa": "Home_Points_After",
            "vpb": "Visitor_Points_Before",
            "vpa": "Visitor_Points_After",
        }
    )

    score_columns = [
        "Home_Points_Before",
        "Home_Points_After",
        "Visitor_Points_Before",
        "Visitor_Points_After",
    ]
    formatted[score_columns] = formatted[score_columns].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)

    formatted["Point_Change"] = formatted.apply(calculate_point_change, axis=1)
    formatted["Score_Diff"] = (formatted["Home_Points_Before"] - formatted["Visitor_Points_Before"]).abs()
    formatted["Score_Diff_After"] = (formatted["Home_Points_After"] - formatted["Visitor_Points_After"]).abs()
    formatted["Video_Link"] = formatted["Video_URL"].apply(
        lambda value: value.get("lurl") if isinstance(value, dict) else None
    )
    formatted["Thumbnail_Link"] = formatted["Video_URL"].apply(
        lambda value: value.get("lth") if isinstance(value, dict) else None
    )
    formatted["Event_Link"] = formatted.apply(build_event_link, axis=1)

    columns = [
        "Game_ID",
        "Event_Index",
        "Game_Date",
        "Game_Code",
        "Period",
        "Home_Team",
        "Visitor_Team",
        "Description",
        "Home_Points_Before",
        "Home_Points_After",
        "Visitor_Points_Before",
        "Visitor_Points_After",
        "Point_Change",
        "Score_Diff",
        "Score_Diff_After",
        "Video_Link",
        "Thumbnail_Link",
        "Event_Link",
    ]
    return formatted[columns].sort_values("Game_Date", ascending=False)


def filter_by_shot_specifiers(results, shot_specifiers):
    if results.empty or not shot_specifiers:
        return results

    description = results["Description"].fillna("").str.upper()
    mask = pd.Series(True, index=results.index)

    for shot_specifier in shot_specifiers:
        mask &= description.str.contains(shot_specifier.upper(), regex=False)

    return results[mask].copy()


def apply_keyword_filters(results, keyword_params):
    filtered = filter_by_shot_specifiers(results, keyword_params["shot_specifiers"])
    if keyword_params["miss_filter"]:
        filtered = filtered[filtered["Point_Change"] == 0].copy()
    return filtered


def run_keyword_query(player_name=PLAYER_NAME, query_text=QUERY_TEXT):
    keyword_params = parse_keywords(query_text)
    video_details = fetch_video_details(player_name, context_measure=keyword_params["context_measure"])
    results = process_videos(video_details)
    return apply_keyword_filters(results, keyword_params)


def main():
    keyword_params = parse_keywords(QUERY_TEXT)

    print("Running NBA API query...")
    print(f"Player name: {PLAYER_NAME}")
    print(f"Query text: {QUERY_TEXT}")
    print(f"Keyword params: {keyword_params}")
    print(f"Query params: {build_query_params(context_measure=keyword_params['context_measure'])}")

    video_details = fetch_video_details(context_measure=keyword_params["context_measure"])
    results = process_videos(video_details)
    results = apply_keyword_filters(results, keyword_params)

    if results.empty:
        print("No rows returned from the NBA API.")
        return

    print()
    print(
        results[
            [
                "Game_Date",
                "Game_Code",
                "Description",
                "Point_Change",
                "Score_Diff",
                "Score_Diff_After",
                "Video_Link",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )

    output_path = Path("output/video_details_sample.csv")
    output_path.parent.mkdir(exist_ok=True)
    results.to_csv(output_path, index=False)

    print()
    print(f"Wrote CSV: {output_path.resolve()}")


if __name__ == "__main__":
    main()

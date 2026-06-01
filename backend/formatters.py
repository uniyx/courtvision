"""Normalize NBA video responses into DataFrames and apply local filters."""

from re import fullmatch
from urllib.parse import urlencode

import pandas as pd


VIDEO_COLUMNS = [
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
    "Home_Score_Diff_Before",
    "Home_Score_Diff_After",
    "Point_Change",
    "Score_Diff",
    "Score_Diff_After",
    "Scoring_Side",
    "Scoring_Margin_Before",
    "Scoring_Margin_After",
    "Is_Game_Tying",
    "Is_Go_Ahead",
    "Video_Link",
    "Thumbnail_Link",
    "Event_Link",
]


def build_event_link(row):
    """Build the stable NBA stats event page link for a play."""
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


def build_display_description(description, player_name, keyword_params):
    """Make NBA block rows read from the searched player's perspective."""
    if not isinstance(description, str):
        return description

    if not keyword_params.get("miss_filter"):
        return description

    block_marker = " BLOCK"
    if block_marker in description and not description.upper().startswith("MISS "):
        player_label = player_name.split()[-1]
        return f"MISS {player_label} - {description}"

    return description


def add_search_context(results, player_name, keyword_params, season_type=None):
    """Attach user-facing context that clarifies why a row matched the query."""
    if results.empty:
        for column in ["Display_Description", "Original_Description", "Searched_Player", "Season_Type"]:
            if column not in results.columns:
                results[column] = pd.Series(dtype="object")
        return results

    contextualized = results.copy()
    contextualized["Original_Description"] = contextualized["Description"]
    contextualized["Searched_Player"] = player_name
    contextualized["Season_Type"] = season_type
    contextualized["Display_Description"] = contextualized["Description"].apply(
        lambda description: build_display_description(description, player_name, keyword_params)
    )
    return contextualized


def process_videos(video_details):
    """Normalize the raw NBA playlist and video metadata into a DataFrame."""
    result_sets = video_details["resultSets"]
    playlist = result_sets["playlist"]
    video_urls = result_sets["Meta"]["videoUrls"]

    print(f"playlist rows: {len(playlist)}")
    print(f"video URL rows: {len(video_urls)}")

    if not playlist:
        return pd.DataFrame(columns=VIDEO_COLUMNS)

    # NBA returns compact field names in playlist rows. Rename once here so
    # downstream search/UI code can use readable column names.
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

    home_change = formatted["Home_Points_After"] - formatted["Home_Points_Before"]
    visitor_change = formatted["Visitor_Points_After"] - formatted["Visitor_Points_Before"]
    formatted["Home_Score_Diff_Before"] = formatted["Home_Points_Before"] - formatted["Visitor_Points_Before"]
    formatted["Home_Score_Diff_After"] = formatted["Home_Points_After"] - formatted["Visitor_Points_After"]

    # Point_Change powers local miss filtering: made shots change the score,
    # missed field-goal attempts do not.
    formatted["Point_Change"] = pd.concat([home_change, visitor_change], axis=1).max(axis=1)
    formatted["Score_Diff"] = (formatted["Home_Points_Before"] - formatted["Visitor_Points_Before"]).abs()
    formatted["Score_Diff_After"] = (formatted["Home_Points_After"] - formatted["Visitor_Points_After"]).abs()
    formatted["Scoring_Side"] = "NONE"
    formatted.loc[home_change > visitor_change, "Scoring_Side"] = "HOME"
    formatted.loc[visitor_change > home_change, "Scoring_Side"] = "VISITOR"
    formatted["Scoring_Margin_Before"] = 0
    formatted["Scoring_Margin_After"] = 0
    home_scored = formatted["Scoring_Side"] == "HOME"
    visitor_scored = formatted["Scoring_Side"] == "VISITOR"
    formatted.loc[home_scored, "Scoring_Margin_Before"] = formatted.loc[home_scored, "Home_Score_Diff_Before"]
    formatted.loc[home_scored, "Scoring_Margin_After"] = formatted.loc[home_scored, "Home_Score_Diff_After"]
    formatted.loc[visitor_scored, "Scoring_Margin_Before"] = -formatted.loc[visitor_scored, "Home_Score_Diff_Before"]
    formatted.loc[visitor_scored, "Scoring_Margin_After"] = -formatted.loc[visitor_scored, "Home_Score_Diff_After"]
    formatted["Is_Game_Tying"] = formatted["Score_Diff_After"] == 0
    formatted["Is_Go_Ahead"] = (
        formatted["Point_Change"].gt(0)
        & formatted["Scoring_Margin_Before"].le(0)
        & formatted["Scoring_Margin_After"].gt(0)
    )
    formatted["Video_Link"] = formatted["Video_URL"].apply(
        lambda value: value.get("lurl") if isinstance(value, dict) else None
    )
    formatted["Thumbnail_Link"] = formatted["Video_URL"].apply(
        lambda value: value.get("lth") if isinstance(value, dict) else None
    )
    formatted["Event_Link"] = formatted.apply(build_event_link, axis=1)

    return formatted[VIDEO_COLUMNS].sort_values("Game_Date", ascending=False)


def parse_clock_seconds(clock):
    """Parse PlayByPlayV3 ISO-ish period clocks such as PT03M47.00S."""
    if not isinstance(clock, str):
        return None

    match = fullmatch(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", clock)
    if not match:
        return None

    minutes = int(match.group(1) or 0)
    seconds = float(match.group(2) or 0)
    return int(minutes * 60 + seconds)


def extract_play_by_play_clock(play_by_play):
    """Return event clock columns needed to enrich VideoDetailsAsset rows."""
    if play_by_play.empty:
        return pd.DataFrame(columns=["Game_ID", "Event_Index", "Clock", "Seconds_Remaining"])

    clock_data = play_by_play[["gameId", "actionNumber", "clock"]].copy()
    clock_data = clock_data.rename(
        columns={
            "gameId": "Game_ID",
            "actionNumber": "Event_Index",
            "clock": "Clock",
        }
    )
    clock_data["Game_ID"] = clock_data["Game_ID"].astype(str)
    clock_data["Event_Index"] = pd.to_numeric(clock_data["Event_Index"], errors="coerce").astype("Int64")
    clock_data["Seconds_Remaining"] = clock_data["Clock"].apply(parse_clock_seconds)
    return clock_data.dropna(subset=["Event_Index"]).drop_duplicates(["Game_ID", "Event_Index"])


def enrich_with_play_by_play(results, play_by_play_by_game):
    """Attach period clock data to video rows using Game_ID and Event_Index."""
    if results.empty or not play_by_play_by_game:
        return results

    clock_frames = [
        extract_play_by_play_clock(play_by_play)
        for play_by_play in play_by_play_by_game.values()
    ]
    clock_data = pd.concat(clock_frames, ignore_index=True) if clock_frames else pd.DataFrame()
    if clock_data.empty:
        return results

    enriched = results.copy()
    enriched["Game_ID"] = enriched["Game_ID"].astype(str)
    enriched["Event_Index"] = pd.to_numeric(enriched["Event_Index"], errors="coerce").astype("Int64")
    return enriched.merge(clock_data, on=["Game_ID", "Event_Index"], how="left")


def filter_by_shot_specifiers(results, shot_specifiers):
    """Require every requested shot descriptor to appear in the play text."""
    if results.empty or not shot_specifiers:
        return results
    if "Description" not in results.columns:
        return results.iloc[0:0].copy()

    description = results["Description"].fillna("").str.upper()
    mask = pd.Series(True, index=results.index)

    for shot_specifier in shot_specifiers:
        mask &= description.str.contains(shot_specifier.upper(), regex=False)

    return results[mask].copy()


def filter_by_score_context(results, score_filter):
    if results.empty or not score_filter:
        return results
    if score_filter == "GAME_TYING" and "Is_Game_Tying" not in results.columns:
        return results.iloc[0:0].copy()
    if score_filter == "GO_AHEAD" and "Is_Go_Ahead" not in results.columns:
        return results.iloc[0:0].copy()
    if score_filter == "GAME_TYING":
        return results[results["Is_Game_Tying"]].copy()
    if score_filter == "GO_AHEAD":
        return results[results["Is_Go_Ahead"]].copy()
    return results


def filter_by_clutch(results, clutch_seconds):
    if results.empty or clutch_seconds is None:
        return results
    if "Period" not in results.columns or "Score_Diff" not in results.columns:
        return results.iloc[0:0].copy()

    approximate_mask = results["Period"].ge(4) & results["Score_Diff"].le(5)
    if "Seconds_Remaining" not in results.columns:
        return results[approximate_mask].copy()

    clutch_mask = (
        approximate_mask
        & results["Seconds_Remaining"].notna()
        & results["Seconds_Remaining"].le(clutch_seconds)
    )
    return results[clutch_mask].copy()


def apply_keyword_filters(results, keyword_params):
    """Apply local filters that are easier to handle after the NBA response."""
    filtered = filter_by_shot_specifiers(results, keyword_params["shot_specifiers"])
    if keyword_params["miss_filter"]:
        if "Point_Change" not in filtered.columns:
            return filtered.iloc[0:0].copy()
        filtered = filtered[filtered["Point_Change"] == 0].copy()
    filtered = filter_by_score_context(filtered, keyword_params.get("score_filter"))
    filtered = filter_by_clutch(filtered, keyword_params.get("clutch_seconds"))
    return filtered

from urllib.parse import urlencode

import pandas as pd


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


def process_videos(video_details):
    """Normalize the raw NBA playlist and video metadata into a DataFrame."""
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

    home_change = formatted["Home_Points_After"] - formatted["Home_Points_Before"]
    visitor_change = formatted["Visitor_Points_After"] - formatted["Visitor_Points_Before"]
    formatted["Point_Change"] = pd.concat([home_change, visitor_change], axis=1).max(axis=1)
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
    """Apply local filters that are easier to handle after the NBA response."""
    filtered = filter_by_shot_specifiers(results, keyword_params["shot_specifiers"])
    if keyword_params["miss_filter"]:
        filtered = filtered[filtered["Point_Change"] == 0].copy()
    return filtered

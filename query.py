from pathlib import Path

from formatters import apply_keyword_filters, process_videos
from nba_client import NBA_STATS_HEADERS, QUERY_PARAMS, build_nba_stats_headers
from nba_client import build_query_params as build_nba_query_params
from nba_client import fetch_video_details as fetch_nba_video_details
from parsing import (
    build_player_matcher,
    build_team_matcher,
    extract_query_parts,
    load_nlp,
    parse_keywords,
    resolve_player,
)


PLAYER_NAME = "Cade Cunningham"
QUERY_TEXT = "dunks"
TEXT_QUERY = "victor wembanyama dunk playoffs against thunder in may q4"


def build_query_params(
    player_name=PLAYER_NAME,
    context_measure=None,
    season_type=None,
    opponent_team_id=0,
    month=None,
    period=None,
):
    player = resolve_player(player_name)
    return build_nba_query_params(
        player,
        context_measure=context_measure,
        season_type=season_type,
        opponent_team_id=opponent_team_id,
        month=month,
        period=period,
    )


def fetch_video_details(
    player_name=PLAYER_NAME,
    context_measure=None,
    season_type=None,
    opponent_team_id=0,
    month=None,
    period=None,
    rotate_user_agent=False,
    retries=2,
):
    player = resolve_player(player_name)
    return fetch_nba_video_details(
        player,
        context_measure=context_measure,
        season_type=season_type,
        opponent_team_id=opponent_team_id,
        month=month,
        period=period,
        rotate_user_agent=rotate_user_agent,
        retries=retries,
    )


def run_keyword_query(player_name=PLAYER_NAME, query_text=QUERY_TEXT):
    keyword_params = parse_keywords(query_text)
    video_details = fetch_video_details(player_name, context_measure=keyword_params["context_measure"])
    results = process_videos(video_details)
    return apply_keyword_filters(results, keyword_params)


def run_text_query(query_text=TEXT_QUERY):
    """Run the full current pipeline from one text query string."""
    query_parts = extract_query_parts(query_text)
    video_details = fetch_nba_video_details(
        query_parts["player"],
        context_measure=query_parts["keyword_params"]["context_measure"],
        season_type=query_parts["season_type"],
        opponent_team_id=query_parts["opponent_team_id"],
        month=query_parts["month"],
        period=query_parts["period"],
    )
    results = process_videos(video_details)
    return apply_keyword_filters(results, query_parts["keyword_params"])


def main():
    query_parts = extract_query_parts(TEXT_QUERY)

    print("Running NBA API query...")
    print(f"Text query: {TEXT_QUERY}")
    print(f"Player name: {query_parts['player_name']}")
    print(f"Opponent team: {query_parts['opponent_team']}")
    print(f"Season type: {query_parts['season_type']}")
    print(f"Month: {query_parts['month']}")
    print(f"Period: {query_parts['period']}")
    print(f"Keyword text: {query_parts['keyword_text']}")
    print(f"Keyword params: {query_parts['keyword_params']}")
    print(
        "Query params: "
        f"{build_nba_query_params(query_parts['player'], context_measure=query_parts['keyword_params']['context_measure'], season_type=query_parts['season_type'], opponent_team_id=query_parts['opponent_team_id'], month=query_parts['month'], period=query_parts['period'])}"
    )

    video_details = fetch_nba_video_details(
        query_parts["player"],
        context_measure=query_parts["keyword_params"]["context_measure"],
        season_type=query_parts["season_type"],
        opponent_team_id=query_parts["opponent_team_id"],
        month=query_parts["month"],
        period=query_parts["period"],
    )
    results = process_videos(video_details)
    results = apply_keyword_filters(results, query_parts["keyword_params"])

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

"""Small script entry point for running a text query from the terminal.

Application code should use SearchEngine directly. This file is intentionally
thin so the backend logic stays in the dedicated modules.
"""

from pathlib import Path

from backend.search_engine import SearchEngine


TEXT_QUERY = "victor wembanyama dunk playoffs against thunder in may q4"


def run_text_query(query_text=TEXT_QUERY, season="2025-26"):
    """Run a text search and return the filtered results DataFrame."""
    search_engine = SearchEngine(season)
    return search_engine.query(query_text)


def main():
    search_engine = SearchEngine("2025-26")
    search_result = search_engine.search(TEXT_QUERY)
    results = search_result.results

    print("Running NBA API query...")
    print(f"Text query: {search_result.query}")
    print(f"Interpreted as: {search_result.interpretation}")
    print(f"Query params: {search_result.query_params}")

    if search_result.warnings:
        print(f"Warnings: {search_result.warnings}")

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

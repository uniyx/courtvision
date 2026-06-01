"""High-level orchestration for natural-language NBA video search.

Lower-level modules handle parsing, API calls, and DataFrame cleanup. This
module is the stable entry point that ties those pieces into one workflow.
"""

from dataclasses import dataclass, field

import pandas as pd

from formatters import apply_keyword_filters, enrich_with_play_by_play, process_videos
from keywords import MONTH_LABELS, PERIOD_LABELS
from nba_client import build_nba_stats_headers, build_query_params, fetch_play_by_play, fetch_video_details
from parsing import build_player_matcher, build_team_matcher, extract_query_parts, load_nlp


def format_seconds(seconds):
    if seconds is None:
        return None
    if seconds % 60 == 0:
        minutes = seconds // 60
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit}"
    return f"{seconds} seconds"


@dataclass
class SearchResult:
    """Full search response with both user-facing results and debug metadata."""

    query: str
    interpretation: str
    query_parts: dict
    query_params: dict
    raw_results: pd.DataFrame
    results: pd.DataFrame
    user_agent: str
    warnings: list[str] = field(default_factory=list)

    @property
    def result_count(self):
        return len(self.results)

    @property
    def raw_result_count(self):
        return len(self.raw_results)


class SearchEngine:
    """NBA video search orchestrator."""

    def __init__(self, season="2025-26", rotate_user_agent=True, retries=2):
        self.season = season
        self.rotate_user_agent = rotate_user_agent
        self.retries = retries
        self.play_by_play_cache = {}

        # Matcher setup is the expensive local work. Keep it on the engine
        # instance so repeated queries do not rebuild spaCy patterns.
        self.nlp = load_nlp()
        self.player_matcher, self.player_lookup = build_player_matcher(self.nlp)
        self.team_matcher, self.team_lookup = build_team_matcher(self.nlp)

    def parse(self, query_text):
        return extract_query_parts(
            query_text,
            self.nlp,
            self.player_matcher,
            self.player_lookup,
            self.team_matcher,
            self.team_lookup,
        )

    def build_query_params(self, query_parts):
        return build_query_params(
            query_parts["player"],
            context_measure=query_parts["keyword_params"]["context_measure"],
            season=self.season,
            season_type=query_parts["season_type"],
            opponent_team_id=query_parts["opponent_team_id"],
            month=query_parts["month"],
            period=query_parts["period"],
        )

    def build_interpretation(self, query_parts):
        """Turn parsed fields into a sentence users can verify before trusting results."""
        keyword_params = query_parts["keyword_params"]
        shot_specifiers = sorted(keyword_params["shot_specifiers"])
        action = " ".join(specifier.lower() for specifier in shot_specifiers)

        if keyword_params["miss_filter"]:
            action = f"{action} misses".strip()
        elif keyword_params["context_measure"] == "PTS":
            action = f"{action} field goals made".strip()
        else:
            action = keyword_params["context_measure"].lower()

        if not action:
            action = keyword_params["context_measure"].lower()

        pieces = [
            f"{query_parts['player_name']} {action}",
            f"during the {self.season} season",
        ]

        if query_parts["season_type"]:
            pieces.append(f"in the {query_parts['season_type']}")
        if query_parts["opponent_team"]:
            pieces.append(f"against the {query_parts['opponent_team']}")
        if MONTH_LABELS.get(query_parts["month"]):
            pieces.append(f"in {MONTH_LABELS[query_parts['month']]}")
        if PERIOD_LABELS.get(query_parts["period"]):
            pieces.append(f"during the {PERIOD_LABELS[query_parts['period']]}")
        if keyword_params.get("clutch_seconds"):
            pieces.append(
                f"in the final {format_seconds(keyword_params['clutch_seconds'])} "
                "of the 4th quarter or overtime with the score within 5 points"
            )
        if keyword_params.get("score_filter") == "GAME_TYING":
            pieces.append("that tied the game")
        if keyword_params.get("score_filter") == "GO_AHEAD":
            pieces.append("that took the lead")

        return " ".join(pieces)

    def fetch_play_by_play_for_results(self, results, headers):
        """Fetch play-by-play clocks for the games represented in a result set."""
        play_by_play_by_game = {}
        for game_id in sorted(results["Game_ID"].dropna().astype(str).unique()):
            if game_id not in self.play_by_play_cache:
                self.play_by_play_cache[game_id] = fetch_play_by_play(
                    game_id,
                    headers=headers,
                    retries=self.retries,
                )
            play_by_play_by_game[game_id] = self.play_by_play_cache[game_id]
        return play_by_play_by_game

    def search(self, query_text):
        """Run the complete search pipeline and return results plus metadata."""
        query_parts = self.parse(query_text)
        query_params = self.build_query_params(query_parts)
        headers = build_nba_stats_headers(rotate_user_agent=self.rotate_user_agent)
        keyword_params = query_parts["keyword_params"]

        video_details = fetch_video_details(
            query_parts["player"],
            context_measure=query_parts["keyword_params"]["context_measure"],
            season=self.season,
            season_type=query_parts["season_type"],
            opponent_team_id=query_parts["opponent_team_id"],
            month=query_parts["month"],
            period=query_parts["period"],
            headers=headers,
            retries=self.retries,
        )

        raw_results = process_videos(video_details)
        warnings = []

        if keyword_params.get("clutch_seconds") and not raw_results.empty:
            try:
                preliminary_params = {**keyword_params, "clutch_seconds": None}
                preliminary_results = apply_keyword_filters(raw_results, preliminary_params)
                play_by_play_by_game = self.fetch_play_by_play_for_results(preliminary_results, headers)
                results_source = enrich_with_play_by_play(preliminary_results, play_by_play_by_game)
            except Exception as error:
                results_source = raw_results
                warnings.append(f"Could not enrich results with play-by-play clock data: {error}")
        else:
            results_source = raw_results

        results = apply_keyword_filters(results_source, keyword_params)

        # Empty result causes are useful to surface later in notebooks/API/UI.
        if raw_results.empty:
            warnings.append("The NBA API returned no rows for the parsed query parameters.")
        elif keyword_params.get("clutch_seconds") and "Seconds_Remaining" not in results_source.columns:
            warnings.append("Clutch filtering needs play-by-play clock data, but no clock data was available.")
        elif results.empty:
            warnings.append("Rows were returned, but local keyword filters removed every row.")

        return SearchResult(
            query=query_text,
            interpretation=self.build_interpretation(query_parts),
            query_parts=query_parts,
            query_params=query_params,
            raw_results=raw_results,
            results=results,
            user_agent=headers["User-Agent"],
            warnings=warnings,
        )

    def query(self, query_text):
        """Convenience API for notebook users who only want the filtered DataFrame."""
        search_result = self.search(query_text)
        results = search_result.results.copy()
        results.attrs["query"] = search_result.query
        results.attrs["interpretation"] = search_result.interpretation
        results.attrs["query_parts"] = search_result.query_parts
        results.attrs["query_params"] = search_result.query_params
        results.attrs["raw_result_count"] = search_result.raw_result_count
        results.attrs["warnings"] = search_result.warnings
        results.attrs["user_agent"] = search_result.user_agent
        return results

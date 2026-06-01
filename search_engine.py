"""High-level orchestration for natural-language NBA video search.

Lower-level modules handle parsing, API calls, and DataFrame cleanup. This
module is the stable entry point that ties those pieces into one workflow.
"""

from dataclasses import dataclass, field

import pandas as pd

from formatters import apply_keyword_filters, process_videos
from keywords import MONTH_LABELS, PERIOD_LABELS
from nba_client import build_nba_stats_headers, build_query_params, fetch_video_details
from parsing import build_player_matcher, build_team_matcher, extract_query_parts, load_nlp


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

        return " ".join(pieces)

    def search(self, query_text):
        """Run the complete search pipeline and return results plus metadata."""
        query_parts = self.parse(query_text)
        query_params = self.build_query_params(query_parts)
        headers = build_nba_stats_headers(rotate_user_agent=self.rotate_user_agent)

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
        results = apply_keyword_filters(raw_results, query_parts["keyword_params"])
        warnings = []

        # Empty result causes are useful to surface later in notebooks/API/UI.
        if raw_results.empty:
            warnings.append("The NBA API returned no rows for the parsed query parameters.")
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

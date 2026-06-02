"""High-level orchestration for natural-language NBA video search.

Lower-level modules handle parsing, API calls, and DataFrame cleanup. This
module is the stable entry point that ties those pieces into one workflow.
"""

import logging
from dataclasses import dataclass, field

import pandas as pd

from backend.formatters import add_search_context, apply_keyword_filters, enrich_with_play_by_play, process_videos
from backend.names.keywords import MONTH_LABELS, PERIOD_LABELS
from backend.nba_client import build_nba_stats_headers, build_query_params, fetch_play_by_play, fetch_video_details
from backend.parsing import extract_query_parts, get_default_matchers


logger = logging.getLogger(__name__)
DEFAULT_SEASON_TYPES = ["Regular Season", "Playoffs"]


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

    def __init__(
        self,
        season="2025-26",
        rotate_user_agent=True,
        retries=2,
        video_timeout=30,
        play_by_play_timeout=10,
        use_play_by_play=False,
    ):
        self.season = season
        self.rotate_user_agent = rotate_user_agent
        self.retries = retries
        self.video_timeout = video_timeout
        self.play_by_play_timeout = play_by_play_timeout
        self.use_play_by_play = use_play_by_play
        self.play_by_play_cache = {}

        # Matcher setup is process-cached. Engines for different seasons can
        # share the same text parser because season only affects API params.
        (
            self.nlp,
            self.player_matcher,
            self.player_lookup,
            self.team_matcher,
            self.team_lookup,
        ) = get_default_matchers()

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
        params = build_query_params(
            query_parts["player"],
            context_measure=query_parts["keyword_params"]["context_measure"],
            season=self.season,
            season_type=query_parts["season_type"],
            opponent_team_id=query_parts["opponent_team_id"],
            month=query_parts["month"],
            period=query_parts["period"],
        )
        if query_parts["season_type"] is None:
            params["season_type_all_star"] = DEFAULT_SEASON_TYPES.copy()
        return params

    def build_interpretation(self, query_parts):
        """Turn parsed fields into a sentence users can verify before trusting results."""
        keyword_params = query_parts["keyword_params"]
        shot_specifiers = sorted(keyword_params["shot_specifiers"])
        action = " ".join(specifier.lower() for specifier in shot_specifiers)

        if keyword_params.get("recipient_player_name") and keyword_params["context_measure"] == "AST":
            action = f"assists to {keyword_params['recipient_player_name']}"
            if shot_specifiers:
                action = f"{action} on {' '.join(specifier.lower() for specifier in shot_specifiers)}"
        elif keyword_params["miss_filter"]:
            action = f"{action} misses".strip()
        elif keyword_params["context_measure"] == "PTS":
            action = f"{action} field goals made".strip()
        else:
            action = keyword_params["context_measure"].lower()

        if not action:
            action = keyword_params["context_measure"].lower()

        season_type = query_parts["season_type"]
        season_label = f"{self.season} season"
        if season_type == "Regular Season":
            season_label = f"{self.season} regular season"
        elif season_type:
            season_label = f"{self.season} {season_type.lower()} season"

        pieces = [
            f"{query_parts['player_name']} {action}",
            f"during the {season_label}",
        ]
        if query_parts["opponent_team"]:
            pieces.append(f"against the {query_parts['opponent_team']}")
        if MONTH_LABELS.get(query_parts["month"]):
            pieces.append(f"in {MONTH_LABELS[query_parts['month']]}")
        if PERIOD_LABELS.get(query_parts["period"]):
            pieces.append(f"during the {PERIOD_LABELS[query_parts['period']]}")
        if keyword_params.get("clutch_seconds"):
            clutch_period_label = "4th quarter or overtime"
            if query_parts["period"] == 4:
                clutch_period_label = "4th quarter"
            elif query_parts["period"] and query_parts["period"] >= 5:
                clutch_period_label = PERIOD_LABELS.get(query_parts["period"], "overtime")
            if self.use_play_by_play:
                pieces.append(
                    f"in the final {format_seconds(keyword_params['clutch_seconds'])} "
                    f"of the {clutch_period_label} with the score within 5 points"
                )
            else:
                pieces.append(f"in clutch situations, approximated as {clutch_period_label} with the score within 5 points")
        if keyword_params.get("score_filter") == "GAME_TYING":
            pieces.append("that tied the game")
        if keyword_params.get("score_filter") == "GO_AHEAD":
            pieces.append("that took the lead")

        return " ".join(pieces)

    def fetch_play_by_play_for_results(self, results, headers):
        """Fetch play-by-play clocks for the games represented in a result set."""
        play_by_play_by_game = {}
        warnings = []
        game_ids = sorted(results["Game_ID"].dropna().astype(str).unique())
        logger.info("Fetching play-by-play clock data for %s games", len(game_ids))
        logger.debug("Play-by-play game IDs: %s", game_ids)

        for game_id in game_ids:
            try:
                if game_id not in self.play_by_play_cache:
                    logger.debug("Fetching PlayByPlayV3 for game_id=%s", game_id)
                    self.play_by_play_cache[game_id] = fetch_play_by_play(
                        game_id,
                        headers=headers,
                        retries=self.retries,
                        timeout=self.play_by_play_timeout,
                    )
                else:
                    logger.debug("Using cached PlayByPlayV3 for game_id=%s", game_id)
            except Exception as error:
                logger.warning("Skipping PlayByPlayV3 enrichment for game_id=%s error=%r", game_id, error)
                warnings.append(f"Could not fetch play-by-play clock data for game {game_id}: {type(error).__name__}: {error}")
                continue
            play_by_play_by_game[game_id] = self.play_by_play_cache[game_id]

        logger.info(
            "Play-by-play enrichment fetched=%s failed=%s",
            len(play_by_play_by_game),
            len(warnings),
        )
        return play_by_play_by_game, warnings

    def search(self, query_text):
        """Run the complete search pipeline and return results plus metadata."""
        query_parts = self.parse(query_text)
        query_params = self.build_query_params(query_parts)
        headers = build_nba_stats_headers(rotate_user_agent=self.rotate_user_agent)
        keyword_params = query_parts["keyword_params"]
        season_types = [query_parts["season_type"]] if query_parts["season_type"] else DEFAULT_SEASON_TYPES

        warnings = []
        raw_frames = []

        for season_type in season_types:
            try:
                video_details = fetch_video_details(
                    query_parts["player"],
                    context_measure=query_parts["keyword_params"]["context_measure"],
                    season=self.season,
                    season_type=season_type,
                    opponent_team_id=query_parts["opponent_team_id"],
                    month=query_parts["month"],
                    period=query_parts["period"],
                    headers=headers,
                    retries=self.retries,
                    timeout=self.video_timeout,
                )
            except Exception as error:
                warnings.append(f"Could not fetch {season_type} video details: {type(error).__name__}: {error}")
                continue

            season_results = process_videos(video_details)
            season_results = add_search_context(
                season_results,
                query_parts["player_name"],
                keyword_params,
                season_type=season_type,
            )
            raw_frames.append(season_results)

        if not raw_frames:
            empty_results = pd.DataFrame()
            return SearchResult(
                query=query_text,
                interpretation=self.build_interpretation(query_parts),
                query_parts=query_parts,
                query_params=query_params,
                raw_results=empty_results,
                results=empty_results,
                user_agent=headers["User-Agent"],
                warnings=warnings,
            )

        raw_results = pd.concat(raw_frames, ignore_index=True)
        if "Game_Date" in raw_results.columns and not raw_results.empty:
            raw_results = raw_results.sort_values("Game_Date", ascending=False)

        if keyword_params.get("clutch_seconds") and self.use_play_by_play and not raw_results.empty:
            try:
                preliminary_params = {**keyword_params, "clutch_seconds": None}
                preliminary_results = apply_keyword_filters(raw_results, preliminary_params)
                preliminary_results = preliminary_results[
                    preliminary_results["Period"].ge(4)
                    & preliminary_results["Score_Diff"].le(5)
                ].copy()
                play_by_play_by_game, clock_warnings = self.fetch_play_by_play_for_results(
                    preliminary_results,
                    headers,
                )
                warnings.extend(clock_warnings)
                if play_by_play_by_game:
                    results_source = enrich_with_play_by_play(preliminary_results, play_by_play_by_game)
                else:
                    results_source = preliminary_results
            except Exception as error:
                results_source = preliminary_results if "preliminary_results" in locals() else raw_results
                warnings.append(f"Could not enrich results with play-by-play clock data: {error}")
        else:
            results_source = raw_results

        results = apply_keyword_filters(results_source, keyword_params)

        # Empty result causes are useful to surface later in notebooks/API/UI.
        if raw_results.empty:
            warnings.append("The NBA API returned no rows for the parsed query parameters.")
        elif keyword_params.get("clutch_seconds") and not self.use_play_by_play:
            warnings.append("PlayByPlayV3 is disabled; clutch filtering uses period and score margin only.")
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

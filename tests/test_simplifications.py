import unittest
from collections import OrderedDict
from datetime import date
from time import time
from unittest.mock import patch

import pandas as pd

from backend import api as api_module
from backend import entities
from backend import nba_client
from backend import parsing
from backend import search_engine as search_engine_module
from backend.formatters import process_videos
from backend.search_engine import SearchEngine


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.cade = {
            "id": 1,
            "full_name": "Cade Cunningham",
            "first_name": "Cade",
            "last_name": "Cunningham",
        }
        self.duren = {
            "id": 2,
            "full_name": "Jalen Duren",
            "first_name": "Jalen",
            "last_name": "Duren",
        }
        self.thunder = {
            "id": 3,
            "full_name": "Oklahoma City Thunder",
            "abbreviation": "OKC",
        }
        self.players = {
            "cade": self.cade,
            "cade cunningham": self.cade,
            "duren": self.duren,
            "jalen duren": self.duren,
        }
        self.teams = {"okc": self.thunder}

    def test_parser_resolves_entities_without_nlp_model(self):
        query = "cade assists to duren dunk against okc q4"
        with patch.object(parsing, "get_player_lookup", return_value=self.players), patch.object(
            parsing, "get_team_lookup", return_value=self.teams
        ):
            parts = parsing.extract_query_parts(query)

        self.assertEqual(parts["player"], self.cade)
        self.assertEqual(parts["recipient_player"], self.duren)
        self.assertEqual(parts["opponent_team"], "Oklahoma City Thunder")
        self.assertEqual(parts["period"], 4)
        self.assertEqual(parts["keyword_params"]["context_measure"], "AST")
        self.assertEqual(parts["keyword_params"]["shot_specifiers"], {"DUNK"})


class BackendHelperTests(unittest.TestCase):
    def test_retry_helper_retries_then_returns(self):
        attempts = []

        def request():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise ValueError("temporary")
            return "ok"

        with patch.object(nba_client, "sleep") as sleep:
            result = nba_client._request_with_retries(request, 2, "test operation", "test failed")

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, [1, 2, 3])
        self.assertEqual(sleep.call_count, 2)

    def test_cache_pruner_removes_oldest_entries(self):
        cache = OrderedDict((key, {"created_at": time()}) for key in ("first", "second", "third"))

        api_module.prune_cache(cache, ttl_seconds=600, max_items=2)

        self.assertEqual(list(cache), ["second", "third"])

    def test_cache_pruner_removes_expired_entries(self):
        cache = OrderedDict({"old": {"created_at": 0}})

        api_module.prune_cache(cache, ttl_seconds=1, max_items=2)

        self.assertEqual(cache, {})

    def test_dataframe_records_use_shared_scalar_normalizer(self):
        frame = pd.DataFrame([{"when": pd.Timestamp("2026-01-02"), "missing": float("nan")}])

        self.assertEqual(
            api_module.dataframe_records(frame, 0, 1),
            [{"when": "2026-01-02T00:00:00", "missing": None}],
        )


class SeasonTests(unittest.TestCase):
    def test_current_season_rolls_over_in_october(self):
        self.assertEqual(nba_client.current_season(date(2026, 9, 30)), "2025-26")
        self.assertEqual(nba_client.current_season(date(2026, 10, 1)), "2026-27")
        self.assertEqual(nba_client.current_season(date(2027, 1, 15)), "2026-27")

    def test_season_players_come_from_live_list_filtered_by_years(self):
        frame = pd.DataFrame(
            [
                {"PERSON_ID": 1, "DISPLAY_FIRST_LAST": "AJ Dybantsa", "DISPLAY_LAST_COMMA_FIRST": "Dybantsa, AJ", "FROM_YEAR": "2026", "TO_YEAR": "2026"},
                {"PERSON_ID": 2, "DISPLAY_FIRST_LAST": "Dwyane Wade", "DISPLAY_LAST_COMMA_FIRST": "Wade, Dwyane", "FROM_YEAR": "2003", "TO_YEAR": "2018"},
                {"PERSON_ID": 3, "DISPLAY_FIRST_LAST": "Nene", "DISPLAY_LAST_COMMA_FIRST": "Nene", "FROM_YEAR": "2002", "TO_YEAR": "2026"},
            ]
        )
        with patch.object(entities, "all_players_frame", return_value=frame):
            players = entities.season_players("2026-27")

        self.assertEqual(
            players,
            [
                {"id": 1, "full_name": "AJ Dybantsa", "first_name": "AJ", "last_name": "Dybantsa"},
                {"id": 3, "full_name": "Nene", "first_name": "", "last_name": "Nene"},
            ],
        )

    def test_player_lookup_falls_back_to_bundled_list(self):
        with patch.object(entities, "season_player_lookup", side_effect=RuntimeError("down")), patch.object(
            entities, "bundled_player_lookup", return_value={"bundled": {}}
        ):
            self.assertEqual(entities.get_player_lookup("2026-27"), {"bundled": {}})


class FormatterTests(unittest.TestCase):
    def test_scoring_flags_ignore_misses(self):
        base = {"gi": "0022600001", "gc": "20261020/HOUOKC", "p": 4, "ha": "OKC", "va": "HOU", "y": 2026, "m": 10, "d": 20}
        playlist = [
            {**base, "ei": 10, "dsc": "Jump Shot (2 PTS)", "hpb": 98, "hpa": 100, "vpb": 100, "vpa": 100},
            {**base, "ei": 11, "dsc": "MISS Jump Shot", "hpb": 100, "hpa": 100, "vpb": 100, "vpa": 100},
            {**base, "ei": 12, "dsc": "3PT Jump Shot (3 PTS)", "hpb": 100, "hpa": 103, "vpb": 101, "vpa": 101},
        ]

        frame = process_videos({"resultSets": {"playlist": playlist, "Meta": {"videoUrls": []}}}).set_index("Event_Index")

        self.assertEqual(frame["Point_Change"].to_dict(), {10: 2, 11: 0, 12: 3})
        self.assertEqual(frame["Is_Game_Tying"].to_dict(), {10: True, 11: False, 12: False})
        self.assertEqual(frame["Is_Go_Ahead"].to_dict(), {10: False, 11: False, 12: True})


class PlayByPlayCacheTests(unittest.TestCase):
    def test_recent_games_are_refetched_instead_of_cached(self):
        engine = SearchEngine("2026-27")
        results = pd.DataFrame(
            {
                "Game_ID": ["0022600001", "0022600002"],
                "Game_Date": [pd.Timestamp("2026-10-01"), pd.Timestamp.today().normalize()],
            }
        )

        with patch.object(search_engine_module, "fetch_play_by_play", return_value=pd.DataFrame()) as fetch:
            engine.fetch_play_by_play_for_results(results, headers={})
            by_game, _ = engine.fetch_play_by_play_for_results(results, headers={})

        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(set(engine.play_by_play_cache), {"0022600001"})
        self.assertEqual(set(by_game), {"0022600001", "0022600002"})


if __name__ == "__main__":
    unittest.main()

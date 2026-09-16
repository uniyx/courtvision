import json
import inspect
import unittest
from collections import OrderedDict
from pathlib import Path
from time import time
from unittest.mock import patch

import pandas as pd

from backend import api as api_module
from backend import nba_client
from backend import parsing
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

    def test_removed_runtime_dependencies_and_arguments(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("spacy", requirements.lower())
        self.assertNotIn("fake-useragent", requirements.lower())
        self.assertNotIn("requests==", requirements.lower())
        self.assertNotIn("rotate_user_agent", inspect.signature(nba_client.build_nba_stats_headers).parameters)


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


class CleanupStateTests(unittest.TestCase):
    def test_one_off_paths_and_frontend_leftovers_are_gone(self):
        frontend = Path("frontend/app.js").read_text(encoding="utf-8")
        query_module = Path("backend/query.py").read_text(encoding="utf-8")
        demo = Path("demo.ipynb").read_text(encoding="utf-8")
        api_notebook = Path("api.ipynb").read_text(encoding="utf-8")

        self.assertFalse(hasattr(SearchEngine, "query"))
        self.assertNotIn("run_text_query", query_module)
        self.assertNotIn("formatScore", frontend)
        self.assertNotIn("resultObserver", frontend)
        self.assertNotIn("RUN_CONVENIENCE_QUERY", demo)
        self.assertNotIn("RUN_LIVE_SERVER_TEST", api_notebook)
        self.assertFalse(Path("start.md").exists())
        json.loads(demo)
        json.loads(api_notebook)


if __name__ == "__main__":
    unittest.main()

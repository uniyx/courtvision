"""Entity lookup and fuzzy matching for NBA players and teams."""

import logging
from functools import lru_cache

import pandas as pd
from nba_api.stats.static import players, teams
from rapidfuzz import fuzz, process

from backend.names.aliases import PLAYER_ALIASES, TEAM_ALIASES
from backend.nba_client import fetch_all_players
from backend.utils import normalize_name, query_token_ranges, tokenize_query


logger = logging.getLogger(__name__)

PLAYER_FUZZY_THRESHOLD = 82
TEAM_FUZZY_THRESHOLD = 84


# ponytail: fetched once per process, so mid-season signings appear after an API restart.
@lru_cache(maxsize=1)
def all_players_frame():
    return fetch_all_players()


def season_players(season):
    """Players who appeared in a season, shaped like nba_api's static player dicts."""
    frame = all_players_frame()
    start_year = int(season[:4])
    in_season = frame[
        pd.to_numeric(frame["FROM_YEAR"], errors="coerce").le(start_year)
        & pd.to_numeric(frame["TO_YEAR"], errors="coerce").ge(start_year)
    ]
    season_list = []
    for row in in_season.to_dict(orient="records"):
        last_name, _, first_name = row["DISPLAY_LAST_COMMA_FIRST"].partition(", ")
        season_list.append(
            {
                "id": row["PERSON_ID"],
                "full_name": row["DISPLAY_FIRST_LAST"],
                "first_name": first_name,
                "last_name": last_name,
            }
        )
    return season_list


@lru_cache(maxsize=16)
def season_player_lookup(season):
    return build_player_lookup(season_players(season))


@lru_cache(maxsize=1)
def bundled_player_lookup():
    return build_player_lookup(players.get_active_players())


def get_player_lookup(season=None):
    """Return the season's player lookup, or nba_api's bundled active list if the live list fails."""
    if season:
        try:
            # Failures are not cached, so the live list is retried on the next query.
            return season_player_lookup(season)
        except Exception as error:
            logger.warning("Using bundled active players for season=%s error=%r", season, error)
    return bundled_player_lookup()


def build_player_lookup(player_list):
    """Build the normalized-name lookup used for entity resolution."""
    player_lookup = {}
    for player in player_list:
        player_lookup[normalize_name(player["full_name"])] = player

    # Aliases only become active when their target is present in the player
    # list. That keeps retired or future-only aliases from resolving to stale IDs.
    full_name_lookup = {normalize_name(player["full_name"]): player for player in player_lookup.values()}
    for alias, full_name in PLAYER_ALIASES.items():
        normalized_full_name = normalize_name(full_name)
        if normalized_full_name in full_name_lookup:
            player_lookup[normalize_name(alias)] = full_name_lookup[normalized_full_name]

    return player_lookup


@lru_cache(maxsize=1)
def get_team_lookup():
    """Build team lookup patterns from nba_api plus common fan shorthand."""
    team_lookup = {}
    all_teams = teams.get_teams()
    full_name_lookup = {team["full_name"]: team for team in all_teams}

    for team in all_teams:
        for key in {team["full_name"], team["nickname"], team["abbreviation"]}:
            team_lookup[normalize_name(key)] = team

    city_counts = {}
    for team in all_teams:
        city_key = normalize_name(team["city"])
        city_counts[city_key] = city_counts.get(city_key, 0) + 1

    for team in all_teams:
        city_key = normalize_name(team["city"])
        if city_counts[city_key] == 1:
            team_lookup[city_key] = team

    # Team slang is intentionally explicit; nba_api covers official names,
    # nicknames, abbreviations, and unambiguous cities.
    for alias, full_name in TEAM_ALIASES.items():
        if full_name in full_name_lookup:
            team_lookup[normalize_name(alias)] = full_name_lookup[full_name]

    return team_lookup


def is_searchable_span(span_text, ignored_tokens):
    tokens = tokenize_query(span_text)
    if not tokens:
        return False
    return not any(token in ignored_tokens for token in tokens)


def candidate_spans(query_text, ignored_tokens=None, max_tokens=3):
    """Generate short query spans that are plausible entity candidates."""
    ignored_tokens = ignored_tokens or set()
    tokens = query_token_ranges(query_text)
    spans = []
    for start in range(len(tokens)):
        for end in range(start + 1, min(len(tokens), start + max_tokens) + 1):
            start_char = tokens[start][1]
            end_char = tokens[end - 1][2]
            span_text = query_text[start_char:end_char]
            if is_searchable_span(span_text, ignored_tokens):
                spans.append((span_text, start_char, end_char))
    return sorted(spans, key=lambda span: len(tokenize_query(span[0])), reverse=True)


def best_fuzzy_choice(text, choices, threshold):
    """Return the best RapidFuzz choice, unless the best match is too ambiguous."""
    match = process.extractOne(
        normalize_name(text),
        choices,
        scorer=fuzz.WRatio,
        score_cutoff=threshold,
    )
    if not match:
        return None

    value, score, _ = match

    # If the next-best result is effectively tied, do not guess. This is
    # important for short names and abbreviations where false positives are
    # easy to create.
    tied_matches = process.extract(
        normalize_name(text),
        choices,
        scorer=fuzz.WRatio,
        score_cutoff=max(threshold, score - 2),
        limit=3,
    )
    if len(tied_matches) > 1 and tied_matches[1][1] >= score - 2:
        return None

    return value


def overlaps_blocked_range(span, blocked_ranges):
    _, span_start, span_end = span
    return any(span_start < end and span_end > start for start, end in blocked_ranges)


def resolve_entity_from_spans(query_text, lookup, threshold, ignored_tokens=None, blocked_ranges=None):
    """Resolve an entity by trying exact span lookup first, then fuzzy fallback."""
    blocked_ranges = blocked_ranges or []
    choices = list(lookup.keys())
    spans = candidate_spans(query_text, ignored_tokens=ignored_tokens)

    for span_text, start_char, end_char in spans:
        span = (span_text, start_char, end_char)
        if overlaps_blocked_range(span, blocked_ranges):
            continue
        normalized = normalize_name(span_text)
        if normalized in lookup:
            return lookup[normalized], (start_char, end_char)

    for span_text, start_char, end_char in spans:
        span = (span_text, start_char, end_char)
        if overlaps_blocked_range(span, blocked_ranges):
            continue
        choice = best_fuzzy_choice(span_text, choices, threshold)
        if choice:
            return lookup[choice], (start_char, end_char)

    return None, None

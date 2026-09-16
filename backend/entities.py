"""Entity lookup and fuzzy matching for NBA players and teams."""

from functools import lru_cache

from nba_api.stats.static import players, teams
from rapidfuzz import fuzz, process

from backend.names.aliases import PLAYER_ALIASES, TEAM_ALIASES
from backend.utils import normalize_name, query_token_ranges, tokenize_query


PLAYER_FUZZY_THRESHOLD = 82
TEAM_FUZZY_THRESHOLD = 84


@lru_cache(maxsize=1)
def get_player_lookup():
    """Build the current active-player lookup used for entity resolution."""
    player_lookup = {}
    for player in players.get_active_players():
        player_lookup[normalize_name(player["full_name"])] = player

    # Aliases only become active when their target is present in the current
    # active-player list. That keeps retired or future-only aliases from
    # resolving to stale IDs.
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


def format_player_options(matches):
    return ", ".join(player["full_name"] for player in matches[:8])


def resolve_player(player_name):
    """Resolve a direct player input into an active-player dict."""
    normalized = normalize_name(player_name)
    player_lookup = get_player_lookup()

    if normalized in player_lookup:
        return player_lookup[normalized]

    matches = [
        player
        for player in player_lookup.values()
        if normalized in {normalize_name(player["first_name"]), normalize_name(player["last_name"])}
    ]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        raise ValueError(f"Ambiguous player name '{player_name}'. Matches: {format_player_options(matches)}")

    choice = best_fuzzy_choice(player_name, list(player_lookup.keys()), PLAYER_FUZZY_THRESHOLD)
    if choice:
        return player_lookup[choice]

    raise ValueError(f"No active NBA player found for '{player_name}'.")

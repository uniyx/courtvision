"""Convert user text into structured search parameters."""

from functools import lru_cache

from backend.entities import (
    PLAYER_FUZZY_THRESHOLD,
    TEAM_FUZZY_THRESHOLD,
    candidate_spans as entity_candidate_spans,
    get_player_lookup,
    get_team_lookup,
    overlaps_blocked_range,
    resolve_entity_from_spans,
)
from backend.names.keywords import (
    CONTEXT_KEYWORDS,
    MISS_KEYWORDS,
    MONTH_KEYWORDS,
    PERIOD_KEYWORDS,
    PHRASE_KEYWORDS,
    SCORE_CONTEXT_KEYWORDS,
    SEASON_TYPE_KEYWORDS,
    SHOT_KEYWORDS,
    TIME_CONTEXT_KEYWORDS,
)
from backend.nba_client import QUERY_PARAMS
from backend.utils import normalize_name, query_token_ranges, remove_char_ranges, tokenize_query


CONTROL_WORDS = {
    "against",
    "for",
    "versus",
    "vs",
    "v",
    "in",
    "to",
    "during",
    "playoff",
    "playoffs",
    "postseason",
    "regular",
    "season",
    "quarter",
    "quarters",
    "overtime",
}

RECIPIENT_MARKER_WORDS = {"to", "for"}


def sorted_keyword_items(keyword_map):
    """Prefer longer phrases so 'step back three' wins before 'three'."""
    return sorted(keyword_map.items(), key=lambda item: len(tokenize_query(item[0])), reverse=True)


SORTED_PHRASE_KEYWORDS = sorted_keyword_items(PHRASE_KEYWORDS)
SORTED_SCORE_CONTEXT_KEYWORDS = sorted_keyword_items(SCORE_CONTEXT_KEYWORDS)
SORTED_SEASON_TYPE_KEYWORDS = sorted_keyword_items(SEASON_TYPE_KEYWORDS)
SORTED_TIME_CONTEXT_KEYWORDS = sorted_keyword_items(TIME_CONTEXT_KEYWORDS)
SORTED_PERIOD_KEYWORDS = sorted_keyword_items(PERIOD_KEYWORDS)


def add_shot_specifiers(shot_specifiers, value):
    for specifier in value.split("|"):
        shot_specifiers.add(specifier)


def token_sequence_contains(tokens, phrase):
    """Return True when phrase tokens appear as a complete token sequence."""
    phrase_tokens = tokenize_query(phrase)
    if not phrase_tokens or len(phrase_tokens) > len(tokens):
        return False

    phrase_length = len(phrase_tokens)
    return any(tokens[index : index + phrase_length] == phrase_tokens for index in range(len(tokens) - phrase_length + 1))


def parse_keywords(query_text):
    """Map basketball words into NBA API context and local filter settings."""
    tokens = tokenize_query(query_text)
    context_measure = "PTS"
    shot_specifiers = set()
    miss_filter = False
    clutch_seconds = None
    score_filter = None

    # Phrase keywords can imply multiple local filters, such as
    # "step back three" -> {"STEP BACK", "3PT"}.
    for phrase, specifier in SORTED_PHRASE_KEYWORDS:
        if token_sequence_contains(tokens, phrase):
            add_shot_specifiers(shot_specifiers, specifier)

    for phrase, seconds in SORTED_TIME_CONTEXT_KEYWORDS:
        if token_sequence_contains(tokens, phrase):
            clutch_seconds = seconds
            break

    for phrase, score_context in SORTED_SCORE_CONTEXT_KEYWORDS:
        if token_sequence_contains(tokens, phrase):
            score_filter = score_context
            break

    for token in tokens:
        if token in CONTEXT_KEYWORDS:
            context_measure = CONTEXT_KEYWORDS[token]
        if token in SHOT_KEYWORDS:
            add_shot_specifiers(shot_specifiers, SHOT_KEYWORDS[token])
        if token in MISS_KEYWORDS:
            miss_filter = True

    return {
        "context_measure": context_measure,
        "shot_specifiers": shot_specifiers,
        "miss_filter": miss_filter,
        "clutch_seconds": clutch_seconds,
        "score_filter": score_filter,
    }


def parse_season_type(query_text):
    """Detect NBA season type words such as playoffs or regular season."""
    tokens = tokenize_query(query_text)

    for phrase, season_type in SORTED_SEASON_TYPE_KEYWORDS:
        if token_sequence_contains(tokens, phrase):
            return season_type

    return None


def parse_month(query_text):
    """Detect NBA Stats season-month bucket keywords."""
    tokens = tokenize_query(query_text)

    for token in tokens:
        if token in MONTH_KEYWORDS:
            return MONTH_KEYWORDS[token]

    return QUERY_PARAMS["month"]


def parse_period(query_text):
    """Detect quarter/period keywords for the NBA Stats Period parameter."""
    tokens = tokenize_query(query_text)

    for phrase, period in SORTED_PERIOD_KEYWORDS:
        if token_sequence_contains(tokens, phrase):
            return period

    return QUERY_PARAMS["period"]


@lru_cache(maxsize=1)
def control_word_tokens():
    """Words that describe filters but should not be fuzzy-matched as entities."""
    phrase_tokens = set()
    for phrase in [*MONTH_KEYWORDS.keys(), *PERIOD_KEYWORDS.keys(), *SEASON_TYPE_KEYWORDS.keys()]:
        phrase_tokens.update(tokenize_query(phrase))
    return phrase_tokens


@lru_cache(maxsize=1)
def ignored_entity_tokens():
    """Vocabulary that should not become a player/team fuzzy candidate."""
    tokens = CONTROL_WORDS | control_word_tokens()
    for keyword_map in (CONTEXT_KEYWORDS, SHOT_KEYWORDS, TIME_CONTEXT_KEYWORDS, SCORE_CONTEXT_KEYWORDS):
        tokens.update(keyword_map.keys())
        for phrase in keyword_map.keys():
            tokens.update(tokenize_query(phrase))
    tokens.update(MISS_KEYWORDS)
    return tokens


def candidate_spans(query_text, max_tokens=3):
    return entity_candidate_spans(query_text, ignored_tokens=ignored_entity_tokens(), max_tokens=max_tokens)


def range_after_recipient_marker(query_text):
    """Return the text range after assist-recipient markers such as 'to'."""
    for token, _, end in query_token_ranges(query_text):
        if token in RECIPIENT_MARKER_WORDS:
            return end, len(query_text)
    return None


def unique_player_by_name_part(text, player_lookup):
    normalized = normalize_name(text)
    matches = {}
    for player in player_lookup.values():
        if normalized in {normalize_name(player["first_name"]), normalize_name(player["last_name"])}:
            matches[player["id"]] = player

    if len(matches) == 1:
        return next(iter(matches.values()))
    return None


def resolve_recipient_player(query_text, player_lookup, blocked_ranges):
    """Resolve a secondary player mentioned after 'to'/'for' recipient language."""
    recipient_range = range_after_recipient_marker(query_text)
    if not recipient_range:
        return None, None

    start, end = recipient_range
    blocked_ranges = [*blocked_ranges, (0, start)]
    for span_text, start_char, end_char in candidate_spans(query_text):
        span = (span_text, start_char, end_char)
        if overlaps_blocked_range(span, blocked_ranges):
            continue
        player = unique_player_by_name_part(span_text, player_lookup)
        if player:
            return player, (start_char, end_char)

    return resolve_entity_from_spans(
        query_text,
        player_lookup,
        PLAYER_FUZZY_THRESHOLD,
        ignored_tokens=ignored_entity_tokens(),
        blocked_ranges=blocked_ranges,
    )


def resolve_unmarked_recipient_player(query_text, player_lookup, blocked_ranges):
    """Resolve a secondary player in assist queries without explicit 'to'/'for'."""
    for span_text, start_char, end_char in candidate_spans(query_text):
        span = (span_text, start_char, end_char)
        if overlaps_blocked_range(span, blocked_ranges):
            continue

        normalized = normalize_name(span_text)
        if normalized in player_lookup:
            return player_lookup[normalized], (start_char, end_char)

        player = unique_player_by_name_part(span_text, player_lookup)
        if player:
            return player, (start_char, end_char)

    return None, None


def remove_control_words(text):
    """Remove non-action connector/filter words before keyword parsing."""
    tokens = [
        token
        for token in tokenize_query(text)
        if token
        not in CONTROL_WORDS | control_word_tokens()
    ]
    return " ".join(tokens)


def extract_query_parts(query_text):
    """Split a full text query into player identity and basketball keywords."""
    player_lookup = get_player_lookup()
    team_lookup = get_team_lookup()
    player, player_range = resolve_entity_from_spans(
        query_text,
        player_lookup,
        PLAYER_FUZZY_THRESHOLD,
        ignored_tokens=ignored_entity_tokens(),
    )
    if not player:
        raise ValueError(f"No player name found in query: '{query_text}'")
    remove_ranges = [player_range]

    recipient_player = None
    recipient_range = None
    recipient_player, recipient_range = resolve_recipient_player(query_text, player_lookup, remove_ranges)
    if recipient_player and recipient_player["id"] == player["id"]:
        recipient_player = None
        recipient_range = None
    if not recipient_player:
        preliminary_keyword_text = remove_control_words(remove_char_ranges(query_text, remove_ranges))
        preliminary_keyword_params = parse_keywords(preliminary_keyword_text)
        if preliminary_keyword_params["context_measure"] == "AST":
            recipient_player, recipient_range = resolve_unmarked_recipient_player(query_text, player_lookup, remove_ranges)
            if recipient_player and recipient_player["id"] == player["id"]:
                recipient_player = None
                recipient_range = None
    if recipient_player:
        remove_ranges.append(recipient_range)

    opponent_team = None
    opponent_team, team_range = resolve_entity_from_spans(
        query_text,
        team_lookup,
        TEAM_FUZZY_THRESHOLD,
        ignored_tokens=ignored_entity_tokens(),
        blocked_ranges=remove_ranges,
    )
    if opponent_team:
        remove_ranges.append(team_range)

    keyword_text = remove_control_words(remove_char_ranges(query_text, remove_ranges))

    # Endpoint-level filters are parsed from the original query. Local action
    # keywords are parsed after removing entity names so names like "Curry" do
    # not accidentally become basketball action text.
    season_type = parse_season_type(query_text)
    month = parse_month(query_text)
    period = parse_period(query_text)

    keyword_params = parse_keywords(keyword_text)
    keyword_params["recipient_player"] = recipient_player
    keyword_params["recipient_player_name"] = recipient_player["full_name"] if recipient_player else None
    if recipient_player:
        keyword_params["context_measure"] = "AST"

    return {
        "player": player,
        "player_name": player["full_name"],
        "recipient_player": recipient_player,
        "recipient_player_name": recipient_player["full_name"] if recipient_player else None,
        "opponent_team": opponent_team["full_name"] if opponent_team else None,
        "opponent_team_id": opponent_team["id"] if opponent_team else 0,
        "season_type": season_type,
        "month": month,
        "period": period,
        "keyword_text": keyword_text,
        "keyword_params": keyword_params,
    }

from functools import lru_cache

from entities import (
    PLAYER_FUZZY_THRESHOLD,
    TEAM_FUZZY_THRESHOLD,
    best_fuzzy_choice,
    build_player_matcher,
    build_team_matcher,
    candidate_spans as entity_candidate_spans,
    get_default_matchers,
    get_player_lookup,
    get_team_lookup,
    load_nlp,
    resolve_entity_from_spans,
    resolve_player,
)
from keywords import (
    CONTEXT_KEYWORDS,
    MISS_KEYWORDS,
    MONTH_KEYWORDS,
    PERIOD_KEYWORDS,
    PHRASE_KEYWORDS,
    SEASON_TYPE_KEYWORDS,
    SHOT_KEYWORDS,
)
from nba_client import QUERY_PARAMS
from utils import normalize_name, remove_char_ranges, tokenize_query


CONTROL_WORDS = {
    "against",
    "versus",
    "vs",
    "v",
    "in",
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


def sorted_keyword_items(keyword_map):
    return sorted(keyword_map.items(), key=lambda item: len(tokenize_query(item[0])), reverse=True)


SORTED_PHRASE_KEYWORDS = sorted_keyword_items(PHRASE_KEYWORDS)
SORTED_SEASON_TYPE_KEYWORDS = sorted_keyword_items(SEASON_TYPE_KEYWORDS)
SORTED_PERIOD_KEYWORDS = sorted_keyword_items(PERIOD_KEYWORDS)


def add_shot_specifiers(shot_specifiers, value):
    for specifier in value.split("|"):
        shot_specifiers.add(specifier)


def parse_keywords(query_text):
    """Map basketball words into NBA API context and local filter settings."""
    tokens = tokenize_query(query_text)
    normalized_query = " ".join(tokens)
    context_measure = "PTS"
    shot_specifiers = set()
    miss_filter = False

    for phrase, specifier in SORTED_PHRASE_KEYWORDS:
        normalized_phrase = " ".join(tokenize_query(phrase))
        if normalized_phrase and normalized_phrase in normalized_query:
            add_shot_specifiers(shot_specifiers, specifier)

    for token in tokens:
        if token in CONTEXT_KEYWORDS:
            context_measure = CONTEXT_KEYWORDS[token]
        if token in SHOT_KEYWORDS:
            add_shot_specifiers(shot_specifiers, SHOT_KEYWORDS[token])
        if token in MISS_KEYWORDS:
            miss_filter = True

    if shot_specifiers and context_measure == "PTS":
        context_measure = "PTS"

    return {
        "context_measure": context_measure,
        "shot_specifiers": shot_specifiers,
        "miss_filter": miss_filter,
    }


def parse_season_type(query_text):
    """Detect NBA season type words such as playoffs or regular season."""
    tokens = tokenize_query(query_text)
    normalized_query = " ".join(tokens)

    for phrase, season_type in SORTED_SEASON_TYPE_KEYWORDS:
        normalized_phrase = " ".join(tokenize_query(phrase))
        if normalized_phrase and normalized_phrase in normalized_query:
            return season_type

    return QUERY_PARAMS["season_type_all_star"]


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
    normalized_query = " ".join(tokens)

    for phrase, period in SORTED_PERIOD_KEYWORDS:
        normalized_phrase = " ".join(tokenize_query(phrase))
        if normalized_phrase and normalized_phrase in normalized_query:
            return period

    return QUERY_PARAMS["period"]


@lru_cache(maxsize=1)
def control_word_tokens():
    phrase_tokens = set()
    for phrase in [*MONTH_KEYWORDS.keys(), *PERIOD_KEYWORDS.keys(), *SEASON_TYPE_KEYWORDS.keys()]:
        phrase_tokens.update(tokenize_query(phrase))
    return phrase_tokens


@lru_cache(maxsize=1)
def ignored_entity_tokens():
    tokens = CONTROL_WORDS | control_word_tokens()
    for keyword_map in (CONTEXT_KEYWORDS, SHOT_KEYWORDS):
        tokens.update(keyword_map.keys())
    tokens.update(MISS_KEYWORDS)
    return tokens


def candidate_spans(doc, max_tokens=3):
    return entity_candidate_spans(doc, ignored_tokens=ignored_entity_tokens(), max_tokens=max_tokens)


def remove_control_words(text):
    tokens = [
        token
        for token in tokenize_query(text)
        if token
        not in CONTROL_WORDS | control_word_tokens()
    ]
    return " ".join(tokens)


def extract_query_parts(query_text, nlp=None, player_matcher=None, player_lookup=None, team_matcher=None, team_lookup=None):
    """Split a full text query into player identity and basketball keywords."""
    if any(value is None for value in (nlp, player_matcher, player_lookup, team_matcher, team_lookup)):
        default_nlp, default_player_matcher, default_player_lookup, default_team_matcher, default_team_lookup = get_default_matchers()
        nlp = nlp or default_nlp
        player_matcher = player_matcher or default_player_matcher
        player_lookup = player_lookup or default_player_lookup
        team_matcher = team_matcher or default_team_matcher
        team_lookup = team_lookup or default_team_lookup

    doc = nlp(query_text)
    player_matches = player_matcher(doc)

    if player_matches:
        match_id, start, end = max(player_matches, key=lambda match: match[2] - match[1])
        player_span = doc[start:end]
        player = player_lookup[normalize_name(player_span.text)]
        remove_ranges = [(player_span.start_char, player_span.end_char)]
    else:
        player, player_range = resolve_entity_from_spans(
            doc,
            player_lookup,
            PLAYER_FUZZY_THRESHOLD,
            ignored_tokens=ignored_entity_tokens(),
        )
        if not player:
            raise ValueError(f"No player name found in query: '{query_text}'")
        remove_ranges = [player_range]

    opponent_team = None
    team_matches = team_matcher(doc)
    if team_matches:
        team_match = max(team_matches, key=lambda match: match[2] - match[1])
        match_id, start, end = team_match
        team_span = doc[start:end]
        opponent_team = team_lookup[normalize_name(team_span.text)]
        remove_ranges.append((team_span.start_char, team_span.end_char))
    else:
        opponent_team, team_range = resolve_entity_from_spans(
            doc,
            team_lookup,
            TEAM_FUZZY_THRESHOLD,
            ignored_tokens=ignored_entity_tokens(),
            blocked_ranges=remove_ranges,
        )
        if opponent_team:
            remove_ranges.append(team_range)

    keyword_text = remove_control_words(remove_char_ranges(query_text, remove_ranges))
    season_type = parse_season_type(query_text)
    month = parse_month(query_text)
    period = parse_period(query_text)

    return {
        "player": player,
        "player_name": player["full_name"],
        "opponent_team": opponent_team["full_name"] if opponent_team else None,
        "opponent_team_id": opponent_team["id"] if opponent_team else 0,
        "season_type": season_type,
        "month": month,
        "period": period,
        "keyword_text": keyword_text,
        "keyword_params": parse_keywords(keyword_text),
    }

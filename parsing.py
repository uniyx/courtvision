import spacy
from functools import lru_cache
from nba_api.stats.static import players, teams
from spacy.matcher import PhraseMatcher

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


TEAM_ALIASES = {
    "okc": "Oklahoma City Thunder",
    "gsw": "Golden State Warriors",
    "dubs": "Golden State Warriors",
    "la lakers": "Los Angeles Lakers",
    "la clippers": "Los Angeles Clippers",
    "clips": "Los Angeles Clippers",
    "sixers": "Philadelphia 76ers",
    "wolves": "Minnesota Timberwolves",
    "t-wolves": "Minnesota Timberwolves",
    "mavs": "Dallas Mavericks",
    "blazers": "Portland Trail Blazers",
    "cavs": "Cleveland Cavaliers",
}


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
def get_player_lookup():
    """Build the current active-player lookup used by both spaCy and ID resolution."""
    player_lookup = {}
    for player in players.get_active_players():
        player_lookup[normalize_name(player["full_name"])] = player
    return player_lookup


@lru_cache(maxsize=1)
def get_team_lookup():
    """Build team lookup patterns from nba_api plus a few common aliases."""
    team_lookup = {}
    all_teams = teams.get_teams()
    full_name_lookup = {team["full_name"]: team for team in all_teams}

    for team in all_teams:
        for key in {team["full_name"], team["nickname"], team["abbreviation"]}:
            team_lookup[normalize_name(key)] = team

    city_counts = {}
    for team in all_teams:
        city_counts[normalize_name(team["city"])] = city_counts.get(normalize_name(team["city"]), 0) + 1

    for team in all_teams:
        city_key = normalize_name(team["city"])
        if city_counts[city_key] == 1:
            team_lookup[city_key] = team

    for alias, full_name in TEAM_ALIASES.items():
        if full_name in full_name_lookup:
            team_lookup[normalize_name(alias)] = full_name_lookup[full_name]

    return team_lookup


@lru_cache(maxsize=1)
def load_nlp():
    """Load spaCy's English model.

    spaCy does not know anything NBA-specific. We use it as the text
    engine that tokenizes user queries for our project-defined phrase matcher.
    """
    try:
        return spacy.load("en_core_web_sm")
    except OSError as error:
        raise RuntimeError(
            "spaCy model 'en_core_web_sm' is not installed. "
            "Install requirements.txt before running text query extraction."
        ) from error


def build_player_matcher(nlp=None):
    """Teach spaCy which full player names to recognize."""
    nlp = nlp or load_nlp()
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    player_lookup = get_player_lookup()
    pattern_texts = set()
    for player in player_lookup.values():
        pattern_texts.add(player["full_name"])
        pattern_texts.add(normalize_name(player["full_name"]))
    patterns = [nlp.make_doc(pattern_text) for pattern_text in pattern_texts]
    matcher.add("PLAYER", patterns)
    return matcher, player_lookup


def build_team_matcher(nlp=None):
    """Teach spaCy which NBA team names and aliases to recognize."""
    nlp = nlp or load_nlp()
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    team_lookup = get_team_lookup()
    patterns = [nlp.make_doc(name) for name in team_lookup.keys()]
    matcher.add("TEAM", patterns)
    return matcher, team_lookup


@lru_cache(maxsize=1)
def get_default_matchers():
    nlp = load_nlp()
    player_matcher, player_lookup = build_player_matcher(nlp)
    team_matcher, team_lookup = build_team_matcher(nlp)
    return nlp, player_matcher, player_lookup, team_matcher, team_lookup


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

    if not player_matches:
        raise ValueError(f"No full player name found in query: '{query_text}'")

    match_id, start, end = max(player_matches, key=lambda match: match[2] - match[1])
    player_span = doc[start:end]
    player = player_lookup[normalize_name(player_span.text)]
    remove_ranges = [(player_span.start_char, player_span.end_char)]

    opponent_team = None
    team_matches = team_matcher(doc)
    if team_matches:
        team_match = max(team_matches, key=lambda match: match[2] - match[1])
        match_id, start, end = team_match
        team_span = doc[start:end]
        opponent_team = team_lookup[normalize_name(team_span.text)]
        remove_ranges.append((team_span.start_char, team_span.end_char))

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


def format_player_options(matches):
    return ", ".join(player["full_name"] for player in matches[:8])


def resolve_player(player_name):
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

    raise ValueError(f"No active NBA player found for '{player_name}'.")

"""Small text helpers shared by parsing and entity matching."""

from re import findall, finditer
from unicodedata import category, normalize


def normalize_name(value):
    """Lowercase and strip accents so NBA names compare consistently."""
    value = "".join(character for character in normalize("NFKD", value) if category(character) != "Mn")
    return " ".join(value.lower().split())


def tokenize_query(query_text):
    """Tokenize query text while preserving simple hyphenated terms."""
    return findall(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)?", query_text.lower())


def query_token_ranges(query_text):
    """Return lowercase query tokens with their source character ranges."""
    return [
        (match.group(0).lower(), match.start(), match.end())
        for match in finditer(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)?", query_text)
    ]


def remove_char_ranges(text, ranges):
    """Remove matched entity spans before parsing the remaining action text."""
    cleaned = text
    for start, end in sorted(ranges, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    return " ".join(cleaned.split())

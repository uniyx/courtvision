from re import findall
from unicodedata import category, normalize


def normalize_name(value):
    value = "".join(character for character in normalize("NFKD", value) if category(character) != "Mn")
    return " ".join(value.lower().split())


def tokenize_query(query_text):
    return findall(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)?", query_text.lower())


def remove_char_ranges(text, ranges):
    cleaned = text
    for start, end in sorted(ranges, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    return " ".join(cleaned.split())

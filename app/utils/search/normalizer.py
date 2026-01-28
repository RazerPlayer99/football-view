"""Query normalization for search."""

import re
from datetime import date, timedelta
from typing import Tuple

from .models.intent import TimeModifier


# Common abbreviations to expand
ABBREVIATIONS = {
    # Teams
    "man u": "manchester united",
    "man utd": "manchester united",
    "manu": "manchester united",
    "mufc": "manchester united",
    "man city": "manchester city",
    "mcfc": "manchester city",
    "spurs": "tottenham",
    "thfc": "tottenham",
    "arse": "arsenal",
    "afc": "arsenal",
    "lfc": "liverpool",
    "cfc": "chelsea",
    "nufc": "newcastle",
    "whu": "west ham",
    "avfc": "aston villa",
    "bhafc": "brighton",
    "nffc": "nottingham forest",
    "lufc": "leeds",
    "bcfc": "birmingham city",
    # Competitions
    "prem": "premier league",
    "epl": "premier league",
    "pl": "premier league",
    "ucl": "champions league",
    "cl": "champions league",
    "uel": "europa league",
    "el": "europa league",
    # Common terms
    "vs": "versus",
    "v": "versus",
    "vs.": "versus",
}

# Filler words to strip for matching (but preserve for context)
FILLER_WORDS = {
    "the", "a", "an", "show", "me", "tell", "about", "what", "is", "are",
    "how", "did", "do", "does", "can", "could", "would", "please", "i",
    "want", "to", "see", "get", "find", "give",
}

# Date patterns for relative date extraction
RELATIVE_DATES = {
    "today": 0,
    "tomorrow": 1,
    "yesterday": -1,
    "day after tomorrow": 2,
    "day before yesterday": -2,
}

# Weekend detection
WEEKEND_PATTERNS = [
    r"this\s+weekend",
    r"next\s+weekend",
    r"last\s+weekend",
]

# Week patterns
WEEK_PATTERNS = {
    r"this\s+week": "current_week",
    r"next\s+week": "next_week",
    r"last\s+week": "last_week",
}

# Month patterns
MONTH_PATTERNS = {
    r"this\s+month": "current_month",
    r"next\s+month": "next_month",
    r"last\s+month": "last_month",
}

# Season patterns
SEASON_PATTERNS = [
    r"this\s+season",
    r"current\s+season",
    r"last\s+season",
    r"(\d{4})[-/](\d{2,4})",  # 2024-25, 2024/2025
    r"(\d{4})\s+season",
]


def normalize(text: str) -> str:
    """
    Normalize query text for matching.

    Steps:
    1. Lowercase
    2. Strip whitespace
    3. Remove punctuation (except hyphens in names)
    4. Collapse multiple spaces
    """
    text = text.lower().strip()
    # Remove punctuation except hyphens and apostrophes (for names like O'Brien)
    text = re.sub(r"[^\w\s\-']", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def expand_abbreviations(text: str) -> str:
    """
    Expand common abbreviations in the query.

    Example: "man u vs chelsea" → "manchester united vs chelsea"
    """
    words = text.lower().split()
    result = []
    i = 0

    while i < len(words):
        # Check two-word abbreviations first
        if i < len(words) - 1:
            two_word = f"{words[i]} {words[i+1]}"
            if two_word in ABBREVIATIONS:
                result.append(ABBREVIATIONS[two_word])
                i += 2
                continue

        # Check single-word abbreviations
        word = words[i]
        if word in ABBREVIATIONS:
            result.append(ABBREVIATIONS[word])
        else:
            result.append(word)
        i += 1

    return " ".join(result)


def strip_filler_words(text: str) -> str:
    """
    Remove filler words for better entity matching.

    Example: "show me the arsenal stats" → "arsenal stats"
    """
    words = text.lower().split()
    return " ".join(w for w in words if w not in FILLER_WORDS)


def extract_time_modifier(text: str) -> Tuple[str, TimeModifier | None]:
    """
    Extract time modifier from query text.

    Returns:
        Tuple of (text with time reference removed, TimeModifier or None)
    """
    text_lower = text.lower()

    # Check for "last N" or "next N" patterns
    last_n_match = re.search(r"last\s+(\d+)\s*(?:games?|matches?|fixtures?)?", text_lower)
    if last_n_match:
        count = int(last_n_match.group(1))
        modified_text = text_lower[:last_n_match.start()] + text_lower[last_n_match.end():]
        return modified_text.strip(), TimeModifier(
            modifier_type="past",
            count=count,
            matched_text=last_n_match.group(0),
        )

    next_n_match = re.search(r"next\s+(\d+)\s*(?:games?|matches?|fixtures?)?", text_lower)
    if next_n_match:
        count = int(next_n_match.group(1))
        modified_text = text_lower[:next_n_match.start()] + text_lower[next_n_match.end():]
        return modified_text.strip(), TimeModifier(
            modifier_type="future",
            count=count,
            matched_text=next_n_match.group(0),
        )

    # Check for relative dates
    for pattern, days_offset in RELATIVE_DATES.items():
        if pattern in text_lower:
            target_date = date.today() + timedelta(days=days_offset)
            modified_text = text_lower.replace(pattern, "").strip()
            return modified_text, TimeModifier(
                modifier_type="relative",
                start_date=target_date,
                end_date=target_date,
                relative=pattern,
                matched_text=pattern,
            )

    # Check for weekend patterns
    for pattern in WEEKEND_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            # Calculate weekend dates
            today = date.today()
            days_to_saturday = (5 - today.weekday()) % 7
            if "last" in match.group(0):
                days_to_saturday -= 7
            elif "next" in match.group(0):
                days_to_saturday += 7

            saturday = today + timedelta(days=days_to_saturday)
            sunday = saturday + timedelta(days=1)

            modified_text = text_lower[:match.start()] + text_lower[match.end():]
            return modified_text.strip(), TimeModifier(
                modifier_type="range",
                start_date=saturday,
                end_date=sunday,
                relative="weekend",
                matched_text=match.group(0),
            )

    # Check for week patterns
    for pattern, relative in WEEK_PATTERNS.items():
        match = re.search(pattern, text_lower)
        if match:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)

            if relative == "last_week":
                monday -= timedelta(days=7)
                sunday -= timedelta(days=7)
            elif relative == "next_week":
                monday += timedelta(days=7)
                sunday += timedelta(days=7)

            modified_text = text_lower[:match.start()] + text_lower[match.end():]
            return modified_text.strip(), TimeModifier(
                modifier_type="range",
                start_date=monday,
                end_date=sunday,
                relative=relative,
                matched_text=match.group(0),
            )

    # Check for season patterns
    for pattern in SEASON_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            if "last" in match.group(0):
                # Last season = current year - 1
                season_year = date.today().year - 1
            elif match.groups():
                # Explicit year like 2024-25
                season_year = int(match.group(1))
            else:
                # This/current season
                today = date.today()
                season_year = today.year if today.month >= 8 else today.year - 1

            modified_text = text_lower[:match.start()] + text_lower[match.end():]
            return modified_text.strip(), TimeModifier(
                modifier_type="season",
                season_year=season_year,
                matched_text=match.group(0),
            )

    return text, None


def normalize_query(raw_query: str) -> Tuple[str, str, TimeModifier | None]:
    """
    Full normalization pipeline for a search query.

    Returns:
        Tuple of (normalized_query, query_for_matching, time_modifier)

    - normalized_query: cleaned but preserves structure for intent detection
    - query_for_matching: stripped of filler words for entity matching
    - time_modifier: extracted time reference if any
    """
    # Step 1: Basic normalization
    normalized = normalize(raw_query)

    # Step 2: Extract time modifier before abbreviation expansion
    normalized, time_modifier = extract_time_modifier(normalized)

    # Step 3: Expand abbreviations
    normalized = expand_abbreviations(normalized)

    # Step 4: Create matching version (stripped of filler words)
    for_matching = strip_filler_words(normalized)

    return normalized, for_matching, time_modifier

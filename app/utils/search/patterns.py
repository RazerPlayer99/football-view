"""Intent pattern matching for search."""

import re
from typing import List, Tuple, Optional

from .models.intent import IntentType, IntentResult


# Intent patterns with capture groups for entity extraction
# Patterns are tried in order; first match wins
INTENT_PATTERNS: dict[IntentType, List[str]] = {
    # Standings / League table
    IntentType.STANDINGS: [
        r"^(?:premier league|la liga|bundesliga|serie a|ligue 1|champions league|ucl)?\s*(?:table|standings?|league table)$",
        r"^standings?$",
        r"^table$",
        r"^show\s+(?:me\s+)?(?:the\s+)?(?:league\s+)?table$",
        r"^(?:premier league|la liga|bundesliga|serie a|ligue 1|champions league)\s*$",  # Just league name
    ],

    # Top scorers
    IntentType.TOP_SCORERS: [
        r"top\s*scorers?",
        r"golden\s*boot",
        r"(?:most|leading|top)\s+goals?",
        r"who\s+(?:has|scored)\s+(?:the\s+)?most\s+goals",
        r"goal\s*(?:scorers?|leaders?)",
        r"scoring\s+(?:chart|leaders?|list)",
    ],

    # Top assists
    IntentType.TOP_ASSISTS: [
        r"top\s*assists?",
        r"(?:most|leading|top)\s+assists?",
        r"assist\s*(?:leaders?|chart|list)",
        r"who\s+(?:has|made)\s+(?:the\s+)?most\s+assists?",
        r"playmakers?",
    ],

    # Schedule / Fixtures list
    IntentType.SCHEDULE: [
        r"(?:fixtures?|games?|matches?)\s+(?:this|next|last)\s+(?:week|weekend|month)",
        r"(?:today'?s?|tomorrow'?s?|yesterday'?s?)\s+(?:games?|fixtures?|matches?)",
        r"(?:games?|fixtures?|matches?)\s+(?:today|tomorrow|yesterday)",
        r"(?:upcoming|next)\s+(?:games?|fixtures?|matches?)",
        r"(?:recent|last|previous)\s+(?:games?|fixtures?|matches?)",
        r"(?:weekend|midweek)\s+(?:games?|fixtures?|matches?)",
        r"^fixtures?$",
        r"^schedule$",
        r"what\s+(?:games?|matches?)\s+(?:are\s+)?(?:on|today|tomorrow)",
    ],

    # Comparison (must have two entities with vs/compare)
    IntentType.COMPARISON: [
        r"compare\s+(.+?)\s+(?:to|and|with|versus?)\s+(.+)",
        r"(.+?)\s+(?:versus?|vs\.?)\s+(.+?)\s+(?:comparison|stats?|statistics)",
        r"(.+?)\s+(?:versus?|vs\.?)\s+(.+)",  # Simple "X vs Y" - check entity types later
        r"(.+?)\s+or\s+(.+?)\s*\?",  # "Salah or Haaland?"
        r"who\s*(?:'s|is)\s+better[,:]?\s+(.+?)\s+or\s+(.+)",
        r"(?:is\s+)?(.+?)\s+better\s+than\s+(.+)",  # "is Salah better than Haaland"
    ],

    # Match lookup (team vs team, or "X's game/match")
    IntentType.MATCH_LOOKUP: [
        r"(.+?)\s+(?:versus?|vs\.?|against|v)\s+(.+)",  # Team vs Team
        r"(?:next|upcoming)\s+(.+?)\s+(?:game|match|fixture)",
        r"(?:last|previous|recent)\s+(.+?)\s+(?:game|match|fixture)",
        r"(.+?)\s+(?:game|match|fixture)",
        r"(.+?)\s+(?:next|upcoming)\s+(?:game|match|fixture)",
        r"when\s+(?:do|does|is|are)\s+(.+?)\s+play(?:ing)?",
    ],

    # Chart request
    IntentType.CHART_REQUEST: [
        r"(?:chart|graph|plot|visuali[sz]e)\s+(.+)",
        r"(.+?)\s+(?:chart|graph|over\s+time|trend)",
        r"show\s+(?:me\s+)?(?:a\s+)?(?:graph|chart)\s+(?:of\s+)?(.+)",
    ],

    # Team lookup (single team reference)
    IntentType.TEAM_LOOKUP: [
        r"(?:tell\s+me\s+)?about\s+(.+)",
        r"(.+?)\s+(?:stats?|statistics|info|profile|squad|team)",
        r"(?:show|get)\s+(?:me\s+)?(.+?)\s+(?:stats?|info)",
        r"how\s+(?:is|are)\s+(.+?)\s+doing",
        r"(.+?)\s+form",
        r"(.+?)\s+standings?",  # Specific team's standing
    ],

    # Player lookup patterns are minimal - mainly detected by entity type
    IntentType.PLAYER_LOOKUP: [
        r"(.+?)\s+(?:goals?|assists?|stats?|statistics|profile)",
        r"how\s+(?:is|has)\s+(.+?)\s+(?:doing|performing|played)",
    ],
}

# Patterns that indicate unsupported/out-of-scope queries
UNSUPPORTED_PATTERNS = [
    r"who\s+(?:is|was)\s+(?:the\s+)?(?:best|greatest|goat)",  # Subjective
    r"will\s+.+\s+win",  # Predictions
    r"should\s+(?:I|we)\s+.+",  # Advice
    r"predict(?:ion)?",
    r"who\s+will\s+win",
    r"betting|odds|bet\s+on",
]


def match_intent(normalized_query: str) -> IntentResult:
    """
    Match a normalized query to an intent using regex patterns.

    Args:
        normalized_query: The normalized (lowercase, expanded) query string

    Returns:
        IntentResult with intent type, confidence, and any captured groups
    """
    # First check for unsupported patterns
    for pattern in UNSUPPORTED_PATTERNS:
        if re.search(pattern, normalized_query, re.IGNORECASE):
            return IntentResult(
                intent_type=IntentType.UNKNOWN,
                confidence=0.0,
                matched_pattern=pattern,
            )

    # Try each intent's patterns
    for intent_type, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, normalized_query, re.IGNORECASE)
            if match:
                # Calculate confidence based on match quality
                confidence = _calculate_confidence(normalized_query, match, pattern)

                # Extract capture groups
                captures = list(match.groups()) if match.groups() else []

                return IntentResult(
                    intent_type=intent_type,
                    confidence=confidence,
                    matched_pattern=pattern,
                    raw_captures=[c.strip() for c in captures if c],
                )

    # No pattern matched - check if it might be a simple entity lookup
    # This will be refined by entity extraction
    words = normalized_query.split()
    if len(words) <= 3:
        # Short query, likely a simple lookup
        return IntentResult(
            intent_type=IntentType.TEAM_LOOKUP,  # Default, may be changed to PLAYER_LOOKUP
            confidence=0.60,
            matched_pattern=None,
        )

    # Unknown intent
    return IntentResult(
        intent_type=IntentType.UNKNOWN,
        confidence=0.30,
        matched_pattern=None,
    )


def _calculate_confidence(query: str, match: re.Match, pattern: str) -> float:
    """
    Calculate confidence score for a pattern match.

    Factors:
    - Match coverage (how much of the query was matched)
    - Pattern specificity (more specific patterns = higher confidence)
    - Exact vs partial match
    """
    matched_text = match.group(0)
    coverage = len(matched_text) / len(query) if query else 0

    # Base confidence from coverage
    confidence = 0.5 + (coverage * 0.4)  # Range: 0.5 - 0.9

    # Boost for exact/near-exact matches
    if matched_text.strip() == query.strip():
        confidence += 0.10

    # Boost for patterns with specific keywords (not just wildcards)
    specific_keywords = ["table", "standings", "scorers", "assists", "versus", "compare",
                        "fixtures", "schedule", "chart", "graph"]
    if any(kw in pattern.lower() for kw in specific_keywords):
        confidence += 0.05

    return min(confidence, 0.98)  # Cap at 0.98


def extract_comparison_entities(query: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract the two entities being compared from a comparison query.

    Returns:
        Tuple of (entity1, entity2) or (None, None) if not a comparison
    """
    for pattern in INTENT_PATTERNS[IntentType.COMPARISON]:
        match = re.search(pattern, query, re.IGNORECASE)
        if match and len(match.groups()) >= 2:
            return match.group(1).strip(), match.group(2).strip()
    return None, None


def extract_match_teams(query: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract team names from a match lookup query.

    Returns:
        Tuple of (team1, team2) for vs queries, or (team1, None) for single team
    """
    # Check for vs pattern first
    vs_pattern = r"(.+?)\s+(?:versus?|vs\.?|against|v)\s+(.+)"
    match = re.search(vs_pattern, query, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # Check for single team game pattern
    for pattern in INTENT_PATTERNS[IntentType.MATCH_LOOKUP][1:]:  # Skip vs pattern
        match = re.search(pattern, query, re.IGNORECASE)
        if match and match.groups():
            return match.group(1).strip(), None

    return None, None

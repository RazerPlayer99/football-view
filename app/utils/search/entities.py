"""Entity extraction for search using alias matching and fuzzy matching."""

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

try:
    from Levenshtein import ratio as levenshtein_ratio
    HAS_LEVENSHTEIN = True
except ImportError:
    HAS_LEVENSHTEIN = False

from .models.entities import (
    EntityMatch,
    TeamEntity,
    PlayerEntity,
    CompetitionEntity,
    MetricEntity,
    PronounEntity,
    ExtractionResult,
)
from .models.session import SearchSession


# Confidence thresholds
TEAM_AUTO_RESOLVE_THRESHOLD = 0.85
TEAM_DISAMBIGUATE_THRESHOLD = 0.65
PLAYER_AUTO_RESOLVE_THRESHOLD = 0.88
PLAYER_DISAMBIGUATE_THRESHOLD = 0.70
COMPETITION_AUTO_RESOLVE_THRESHOLD = 0.90
COMPETITION_DISAMBIGUATE_THRESHOLD = 0.75

# Pronouns that reference players
PLAYER_PRONOUNS = {"he", "him", "his", "himself"}

# Pronouns that reference teams
TEAM_PRONOUNS = {"they", "them", "their", "themselves"}

# Match references
MATCH_REFERENCES = {"that game", "the match", "that match", "the game", "it"}

# League references
LEAGUE_REFERENCES = {"the league", "same league", "that league", "the competition"}

# Intent/filler words to skip during entity matching
SKIP_TOKENS = {
    "vs", "versus", "against", "v", "and",  # Comparison words
    "next", "last", "upcoming", "recent", "previous",  # Time words
    "show", "get", "find", "search", "lookup", "tell", "me", "about",  # Action words
    "the", "a", "an", "of", "for", "in", "on", "at", "to",  # Articles/prepositions
    "stats", "statistics", "info", "information", "details",  # Info words
    "goals", "assists", "standing", "standings", "table", "form",  # Metric words (handled separately)
    "how", "many", "what", "who", "when", "where", "is", "are", "was", "were",  # Question words
    "top", "scorers", "assists",  # Stats words (added for clarity)
}

# Multi-word phrases where skip tokens are part of the entity name
# These should be preserved during tokenization
PRESERVE_ENTITY_PHRASES = {
    "serie a": "serie_a",  # Italian league
    "ligue 1": "ligue_1",  # French league
}


def normalize_for_matching(text: str) -> str:
    """Normalize text for entity matching."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\-']", "", text)  # Keep hyphens and apostrophes
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_unicode(text: str) -> str:
    """
    Normalize unicode for matching - removes diacritics.

    Examples:
        "Šeško" -> "sesko"
        "Müller" -> "muller"
        "Mbappé" -> "mbappe"
    """
    import unicodedata
    if not text:
        return ""
    # NFKD decomposes characters, then we remove combining marks
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


# =============================================================================
# AUTO-GENERATED ALIASES
# Reduces need to manually add every player/team to aliases.json
# =============================================================================

def generate_person_aliases(full_name: str) -> set:
    """
    Auto-generate common aliases for a person's name.

    "Nick Woltemade" generates:
        - nick woltemade (full)
        - woltemade (last name)
        - n woltemade (initial + last)
        - n. woltemade (initial with dot)

    "Bruno Fernandes" generates:
        - bruno fernandes
        - fernandes
        - b fernandes / b. fernandes
        - bruno (first name - useful for unique first names)
    """
    name = normalize_unicode(full_name)
    name = re.sub(r"[^a-z\s]", "", name)  # Keep only letters and spaces
    parts = [p for p in name.split() if p]

    if not parts:
        return set()

    aliases = set()
    aliases.add(name)  # Full normalized name

    if len(parts) >= 2:
        first = parts[0]
        last = parts[-1]

        # Last name only (most common search pattern)
        aliases.add(last)

        # Initial + last name (API format: "B. Fernandes")
        aliases.add(f"{first[0]} {last}")
        aliases.add(f"{first[0]}. {last}")

        # First + last (skip middle names)
        if len(parts) > 2:
            aliases.add(f"{first} {last}")

    # Single name (e.g., just "Neymar", "Ronaldinho")
    if len(parts) == 1:
        aliases.add(parts[0])

    return aliases


def generate_team_aliases(team_name: str) -> set:
    """
    Auto-generate common aliases for a team name.

    "Manchester United" generates:
        - manchester united
        - manchester (without common suffixes)

    "FC Barcelona" generates:
        - fc barcelona
        - barcelona (without fc/cf/sc prefixes)

    Note: We deliberately DON'T generate short initials (MU, FCB)
    as they're too risky for false matches. Those should be manual aliases.
    """
    name = normalize_unicode(team_name)
    name = re.sub(r"[^a-z0-9\s]", "", name)
    parts = [p for p in name.split() if p]

    if not parts:
        return set()

    aliases = set()
    aliases.add(name)  # Full normalized name

    # Remove common club markers
    club_markers = {"fc", "cf", "sc", "ac", "cd", "afc", "fk", "sk"}
    core = [p for p in parts if p not in club_markers]

    if core and core != parts:
        aliases.add(" ".join(core))

    return aliases


def expand_api_name(api_name: str) -> set:
    """
    Expand API-style names (initial + last) to searchable forms.

    "N. Woltemade" -> {"n woltemade", "n. woltemade", "woltemade"}
    "B. Fernandes" -> {"b fernandes", "b. fernandes", "fernandes"}

    This helps match when we only have the API format, not full name.
    """
    name = normalize_unicode(api_name)
    parts = name.split()

    if not parts:
        return set()

    aliases = set()
    aliases.add(name.replace(".", "").strip())  # Without dots
    aliases.add(name)  # As-is

    # If first part looks like an initial (1-2 chars, possibly with dot)
    if len(parts) >= 2:
        first = parts[0].replace(".", "")
        if len(first) <= 2:
            last = parts[-1]
            aliases.add(last)  # Just last name
            aliases.add(f"{first} {last}")
            aliases.add(f"{first}. {last}")

    return aliases


# =============================================================================
# PREFIX MATCHING
# Allows "wolte" to match "woltemade" without manual alias
# =============================================================================

def prefix_match_score(token: str, word: str) -> float:
    """
    Score a prefix match. Only meaningful when token >= 4 chars.

    "wolte" against "woltemade" -> ~0.88
    "ferna" against "fernandes" -> ~0.88
    "sal" against "salah" -> 0 (too short)

    Returns 0 if not a valid prefix match.
    """
    if len(token) < 4:
        return 0.0

    token = normalize_unicode(token)
    word = normalize_unicode(word)

    if word.startswith(token):
        # Longer prefix = stronger match
        # 4 chars -> 0.82, 6 chars -> 0.88, 8+ chars -> 0.94
        coverage = len(token) / max(len(word), 1)
        return min(0.94, 0.78 + 0.16 * coverage)

    return 0.0


# =============================================================================
# TOKEN-BASED SEARCH SYSTEM
# Inspired by DSD Order System - forgiving, fast, deterministic
# =============================================================================

def tokenize_query(query: str) -> List[str]:
    """
    Split query into searchable tokens.

    Removes punctuation and normalizes whitespace.
    Example: "arsenal vs chelsea" → ["arsenal", "vs", "chelsea"]
    """
    normalized = normalize_for_matching(query)
    return [t for t in normalized.split() if len(t) > 0]


def classify_token(token: str) -> str:
    """
    Classify a token's type for smarter matching.

    Returns: "numeric", "skip", "comparison", "time", or "entity"
    """
    token_lower = token.lower()

    # Pure numbers - could be jersey, season, team ID
    if token_lower.isdigit():
        return "numeric"

    # Skip words (filler, articles, etc.)
    if token_lower in SKIP_TOKENS:
        return "skip"

    # Comparison indicators
    if token_lower in {"vs", "versus", "against", "v"}:
        return "comparison"

    # Time indicators
    if token_lower in {"next", "last", "upcoming", "recent", "previous", "today", "tomorrow", "weekend"}:
        return "time"

    # Likely an entity name
    return "entity"


def get_entity_tokens(query: str) -> List[str]:
    """
    Extract only the entity-relevant tokens from a query.

    Filters out skip words, keeping tokens that might be entity names.
    Example: "show me arsenal stats" → ["arsenal"]

    Preserves certain phrases where skip tokens are part of entity names.
    Example: "serie a top scorers" → ["serie a"] (not ["serie"])
    """
    query_lower = query.lower()

    # First, replace preserved phrases with placeholders
    preserved = {}
    for phrase, placeholder in PRESERVE_ENTITY_PHRASES.items():
        if phrase in query_lower:
            preserved[placeholder] = phrase
            query_lower = query_lower.replace(phrase, placeholder)

    tokens = tokenize_query(query_lower)
    entity_tokens = [t for t in tokens if classify_token(t) == "entity"]

    # Restore preserved phrases
    result = []
    for token in entity_tokens:
        if token in preserved:
            result.append(preserved[token])  # Restore original phrase
        else:
            result.append(token)

    return result


def token_match_score(token: str, target: str) -> float:
    """
    Calculate how well a single token matches a target string.

    Very forgiving - allows partial matches, prefixes, and typos.
    Returns score 0-1.

    Matching priority:
    1. Exact match -> 1.0
    2. Exact word match -> 0.95
    3. Prefix match (4+ chars) -> 0.82-0.94
    4. Substring match -> 0.70-0.95
    5. Fuzzy/Levenshtein -> 0.55-0.85
    """
    token_lower = normalize_unicode(token.strip())
    target_lower = normalize_unicode(target.strip())

    if not token_lower or not target_lower:
        return 0.0

    # Exact match
    if token_lower == target_lower:
        return 1.0

    # Split target into words for word-level matching
    target_words = target_lower.split()
    best_word_score = 0.0

    for word in target_words:
        # Exact word match
        if token_lower == word:
            return 0.95

        # PREFIX MATCHING (new) - "wolte" -> "woltemade"
        prefix_score = prefix_match_score(token_lower, word)
        if prefix_score > 0:
            best_word_score = max(best_word_score, prefix_score)

        # Word starts with token (partial typing, any length)
        if word.startswith(token_lower) and len(token_lower) >= 2:
            # Short prefix gets lower score than prefix_match_score
            if len(token_lower) < 4:
                best_word_score = max(best_word_score, 0.75)
            # Longer prefixes handled by prefix_match_score above

        # Token starts with same letters (typo tolerance)
        elif len(token_lower) >= 3 and word.startswith(token_lower[:3]):
            best_word_score = max(best_word_score, 0.70)

        # Fuzzy match against individual word (catches typos like "shw" -> "shaw")
        if len(token_lower) >= 2 and len(word) >= 2:
            if HAS_LEVENSHTEIN:
                word_lev = levenshtein_ratio(token_lower, word)
                if word_lev >= 0.65:
                    best_word_score = max(best_word_score, word_lev * 0.9)
            else:
                word_seq = SequenceMatcher(None, token_lower, word).ratio()
                if word_seq >= 0.65:
                    best_word_score = max(best_word_score, word_seq * 0.9)

    if best_word_score > 0:
        return best_word_score

    # Token is contained anywhere in target (e.g., "ars" in "arsenal")
    if token_lower in target_lower and len(token_lower) >= 3:
        return min(0.90, 0.65 + (len(token_lower) / len(target_lower)) * 0.25)

    # Fuzzy match against full target for longer queries
    if HAS_LEVENSHTEIN:
        lev_score = levenshtein_ratio(token_lower, target_lower)
        if lev_score >= 0.6:
            return lev_score * 0.85
    else:
        seq_score = SequenceMatcher(None, token_lower, target_lower).ratio()
        if seq_score >= 0.6:
            return seq_score * 0.85

    return 0.0


def multi_token_match_score(tokens: List[str], target: str, aliases: List[str] = None) -> float:
    """
    Calculate match score for multiple tokens against an entity.

    FORGIVING approach:
    - Best matching token gets highest weight
    - Additional matching tokens boost score
    - Non-matching tokens don't kill the match

    Args:
        tokens: List of search tokens
        target: Canonical entity name
        aliases: Optional list of aliases

    Returns:
        Score 0-1
    """
    if not tokens:
        return 0.0

    # Build list of all matchable strings
    matchable = [target]
    if aliases:
        matchable.extend(aliases)

    # Find best score across all matchable strings
    best_overall = 0.0

    for match_target in matchable:
        # Score each token against this target
        token_scores = []
        for token in tokens:
            score = token_match_score(token, match_target)
            token_scores.append(score)

        if not token_scores:
            continue

        # FORGIVING SCORING:
        # - Best token contributes 70% of score
        # - Other matching tokens contribute remaining 30%
        best_token = max(token_scores)
        other_scores = sorted([s for s in token_scores if s != best_token], reverse=True)

        # Calculate weighted score
        score = best_token * 0.7

        # Bonus for additional matching tokens (up to 0.3)
        if other_scores:
            # Average of other matching tokens (those > 0.5)
            other_matching = [s for s in other_scores if s > 0.5]
            if other_matching:
                other_avg = sum(other_matching) / len(other_matching)
                score += other_avg * 0.3
        else:
            # Single token query - give full weight to best match
            score = best_token

        best_overall = max(best_overall, score)

    return best_overall


def fuzzy_match(query: str, target: str) -> float:
    """
    Calculate fuzzy match ratio between two strings.

    Uses Levenshtein distance if available, otherwise SequenceMatcher.
    Also checks for last-name-only matches with priority for players.
    """
    query_lower = query.lower().strip()
    target_lower = target.lower().strip()

    # Exact match
    if query_lower == target_lower:
        return 1.0

    # Last-name-only match (e.g., "sesko" matches "Benjamin Sesko")
    target_parts = target_lower.split()
    if len(target_parts) > 1:
        last_name = target_parts[-1]
        if query_lower == last_name:
            return 0.95  # High confidence for exact last name match
        # Also check first name
        first_name = target_parts[0]
        if query_lower == first_name:
            return 0.90  # Slightly lower for first name only

        # Check if query matches abbreviated format (e.g., "shaw" matches "l. shaw")
        # Handle "X. Lastname" format common in API
        if target_parts[0].endswith('.') and len(target_parts) >= 2:
            api_last_name = target_parts[-1]
            if query_lower == api_last_name:
                return 0.95  # Exact last name match

    # Check if query is contained in target (partial match)
    if len(query_lower) >= 3 and query_lower in target_lower:
        # Give higher score for longer matches
        containment_ratio = len(query_lower) / len(target_lower)
        return max(0.80, containment_ratio)

    # Use Levenshtein if available, combined with SequenceMatcher
    seq_ratio = SequenceMatcher(None, query_lower, target_lower).ratio()

    if HAS_LEVENSHTEIN:
        lev_ratio = levenshtein_ratio(query_lower, target_lower)
        # Use weighted average - Levenshtein is better for typos
        return (lev_ratio * 0.6) + (seq_ratio * 0.4)

    return seq_ratio


def get_fuzzy_threshold(query: str) -> float:
    """
    Get fuzzy matching threshold based on query length.

    Shorter queries need lower thresholds since they match less text.
    """
    query_len = len(query.strip())
    if query_len <= 4:
        return 0.55  # Very short - be lenient
    elif query_len <= 6:
        return 0.60  # Short
    elif query_len <= 10:
        return 0.65  # Medium
    else:
        return 0.70  # Long queries - be stricter


class AliasDatabase:
    """Database of entity aliases for matching."""

    def __init__(self, aliases_path: Optional[str] = None):
        self.teams: Dict[str, Dict[str, Any]] = {}
        self.players: Dict[str, Dict[str, Any]] = {}
        self.competitions: Dict[str, Dict[str, Any]] = {}
        self.metrics: Dict[str, List[str]] = {}

        if aliases_path:
            self.load(aliases_path)
        else:
            # Try default path
            default_path = Path(__file__).parent.parent.parent.parent / "data" / "aliases.json"
            if default_path.exists():
                self.load(str(default_path))

    def load(self, path: str) -> None:
        """Load aliases from JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.teams = data.get("teams", {})
            self.players = data.get("players", {})
            self.competitions = data.get("competitions", {})
            self.metrics = data.get("metrics", {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # Use empty databases

    def match_team(self, query: str) -> List[EntityMatch]:
        """Match query against team aliases."""
        return self._match_entities(query, self.teams, entity_type="team")

    def match_player(self, query: str) -> List[EntityMatch]:
        """Match query against player aliases."""
        return self._match_entities(query, self.players, entity_type="player")

    def match_competition(self, query: str) -> List[EntityMatch]:
        """Match query against competition aliases."""
        return self._match_entities(query, self.competitions, entity_type="competition")

    def match_metric(self, query: str) -> Optional[MetricEntity]:
        """Match query against metric aliases."""
        query_normalized = normalize_for_matching(query)

        # Check for per-90 indicator
        per_90 = "per 90" in query_normalized or "per90" in query_normalized or "/90" in query_normalized

        for metric_id, aliases in self.metrics.items():
            for alias in aliases:
                if alias.lower() in query_normalized:
                    return MetricEntity(
                        metric_id=metric_id,
                        per_90=per_90,
                        matched_text=alias,
                    )

        return None

    def _match_entities(
        self,
        query: str,
        entities: Dict[str, Dict[str, Any]],
        entity_type: str = "unknown",
    ) -> List[EntityMatch]:
        """
        Match query against an entity database.

        Strategy (forgiving, token-based):
        1. Exact alias match (confidence = 1.0)
        2. Token-based matching with auto-generated aliases
        3. Prefix matching for 4+ char queries
        4. Legacy fuzzy match as fallback

        Args:
            query: The search query
            entities: Entity database dict
            entity_type: "player", "team", or "competition" - for auto-alias generation
        """
        query_normalized = normalize_for_matching(query)
        query_unicode_normalized = normalize_unicode(query_normalized)
        matches: List[EntityMatch] = []

        # Get dynamic threshold based on query length
        threshold = get_fuzzy_threshold(query_normalized)

        # Get entity tokens for matching (strips filler words like "standings")
        tokens = get_entity_tokens(query)
        # Combine tokens back for exact matching: "la liga standings" -> "la liga"
        tokens_combined = " ".join(tokens) if tokens else ""

        # Phase 1: Exact alias lookup (fast path)
        for entity_id, entity_data in entities.items():
            canonical = entity_data["canonical"]
            manual_aliases = [a.lower() for a in entity_data.get("aliases", [])]

            # Generate auto-aliases based on entity type
            if entity_type == "player":
                auto_aliases = generate_person_aliases(canonical)
                # Also expand API-format name if canonical looks like "N. Name"
                auto_aliases.update(expand_api_name(canonical))
            elif entity_type == "team":
                auto_aliases = generate_team_aliases(canonical)
            else:
                auto_aliases = set()

            # Combine manual + auto aliases
            all_aliases = set(manual_aliases) | auto_aliases

            # Check exact match against any alias (including tokens-only version)
            # This allows "la liga standings" to match "la liga" alias
            if (query_normalized in all_aliases or
                query_unicode_normalized in all_aliases or
                (tokens_combined and tokens_combined in all_aliases)):
                return [EntityMatch(
                    entity_id=entity_id,
                    name=canonical,
                    confidence=1.0,
                    match_method="alias_exact",
                    matched_text=query,
                )]

        # Phase 2: Token-based matching with auto-generated aliases (forgiving)
        tokens = get_entity_tokens(query)

        if tokens:
            for entity_id, entity_data in entities.items():
                canonical = entity_data["canonical"]
                manual_aliases = entity_data.get("aliases", [])

                # Generate auto-aliases
                if entity_type == "player":
                    auto_aliases = list(generate_person_aliases(canonical))
                    auto_aliases.extend(expand_api_name(canonical))
                elif entity_type == "team":
                    auto_aliases = list(generate_team_aliases(canonical))
                else:
                    auto_aliases = []

                # Combine all matchable strings
                all_aliases = list(set(manual_aliases + auto_aliases))

                # Multi-token matching - very forgiving
                score = multi_token_match_score(tokens, canonical, all_aliases)

                if score >= threshold:
                    matches.append(EntityMatch(
                        entity_id=entity_id,
                        name=canonical,
                        confidence=score,
                        match_method="token_match",
                        matched_text=query,
                    ))

        # Phase 3: Prefix matching for 4+ char single-token queries
        # This catches "wolte" -> "woltemade" even without fuzzy
        if not matches and len(tokens) == 1 and len(tokens[0]) >= 4:
            token = normalize_unicode(tokens[0])
            for entity_id, entity_data in entities.items():
                canonical = entity_data["canonical"]

                # Check prefix against each word in canonical name
                for word in normalize_unicode(canonical).split():
                    prefix_score = prefix_match_score(token, word)
                    if prefix_score > 0 and prefix_score >= threshold:
                        matches.append(EntityMatch(
                            entity_id=entity_id,
                            name=canonical,
                            confidence=prefix_score,
                            match_method="prefix_match",
                            matched_text=query,
                        ))
                        break  # Only one match per entity

        # Phase 4: Legacy fuzzy matching (if nothing found yet)
        if not matches:
            for entity_id, entity_data in entities.items():
                canonical = entity_data["canonical"]

                # Check canonical name (includes last-name matching)
                ratio = fuzzy_match(query_normalized, canonical)
                if ratio >= threshold:
                    matches.append(EntityMatch(
                        entity_id=entity_id,
                        name=canonical,
                        confidence=ratio,
                        match_method="fuzzy_canonical",
                        matched_text=query,
                    ))

                # Check manual aliases with slightly higher threshold
                alias_threshold = min(threshold + 0.05, 0.75)
                for alias in entity_data.get("aliases", []):
                    ratio = fuzzy_match(query_normalized, alias)
                    if ratio >= alias_threshold:
                        matches.append(EntityMatch(
                            entity_id=entity_id,
                            name=canonical,
                            confidence=ratio * 0.95,  # Slight penalty for alias match
                            match_method="fuzzy_alias",
                            matched_text=query,
                        ))

        # Deduplicate and sort by confidence
        seen = set()
        unique_matches = []
        for m in sorted(matches, key=lambda x: x.confidence, reverse=True):
            if m.entity_id not in seen:
                seen.add(m.entity_id)
                unique_matches.append(m)

        return unique_matches


def extract_pronouns(query: str) -> List[PronounEntity]:
    """Extract pronouns from query that may need session resolution."""
    pronouns = []
    query_lower = query.lower()

    # Check player pronouns
    for pronoun in PLAYER_PRONOUNS:
        if re.search(rf"\b{pronoun}\b", query_lower):
            pronouns.append(PronounEntity(pronoun=pronoun))

    # Check team pronouns
    for pronoun in TEAM_PRONOUNS:
        if re.search(rf"\b{pronoun}\b", query_lower):
            pronouns.append(PronounEntity(pronoun=pronoun))

    # Check match references
    for ref in MATCH_REFERENCES:
        if ref in query_lower:
            pronouns.append(PronounEntity(pronoun=ref))

    # Check league references
    for ref in LEAGUE_REFERENCES:
        if ref in query_lower:
            pronouns.append(PronounEntity(pronoun=ref))

    return pronouns


def resolve_pronouns(
    pronouns: List[PronounEntity],
    session: Optional[SearchSession],
) -> List[PronounEntity]:
    """Resolve pronouns using session context."""
    if not session:
        return pronouns

    resolved = []
    for pronoun in pronouns:
        entity_type, entity_id = session.resolve_pronoun(pronoun.pronoun)
        resolved.append(PronounEntity(
            pronoun=pronoun.pronoun,
            resolved_to=entity_type,
            resolved_id=entity_id,
        ))

    return resolved


def extract_entities(
    query: str,
    query_for_matching: str,
    alias_db: Optional[AliasDatabase] = None,
    session: Optional[SearchSession] = None,
) -> ExtractionResult:
    """
    Extract all entities from a search query.

    Args:
        query: Original normalized query
        query_for_matching: Query with filler words stripped
        alias_db: Optional alias database (uses default if not provided)
        session: Optional session for pronoun resolution

    Returns:
        ExtractionResult with all extracted entities
    """
    if alias_db is None:
        alias_db = AliasDatabase()

    # Extract pronouns first
    pronouns = extract_pronouns(query)
    pronouns = resolve_pronouns(pronouns, session)

    # Try to match entire query as entity first
    team_matches = alias_db.match_team(query_for_matching)
    player_matches = alias_db.match_player(query_for_matching)
    competition_matches = alias_db.match_competition(query_for_matching)

    # Always try word-by-word matching to catch multi-entity queries (e.g., "mbappe vs grimaldo")
    # This ensures we find multiple players/teams in comparison queries
    words = query_for_matching.split()
    if len(words) >= 2:  # Only for multi-word queries
        for i in range(len(words)):
            for j in range(i + 1, min(i + 4, len(words) + 1)):  # Up to 3 consecutive words
                phrase = " ".join(words[i:j])
                if len(phrase) >= 3:  # Skip very short phrases
                    team_matches.extend(alias_db.match_team(phrase))
                    player_matches.extend(alias_db.match_player(phrase))

    # Extract metric
    metric = alias_db.match_metric(query)
    metrics = [metric] if metric else []

    # Convert to entity objects
    teams = [
        TeamEntity.from_match(m, alias_db.teams.get(m.entity_id, {}).get("league_id"))
        for m in _dedupe_matches(team_matches)
    ]

    players = [
        PlayerEntity.from_match(m, alias_db.players.get(m.entity_id, {}).get("team_id"))
        for m in _dedupe_matches(player_matches)
    ]

    competitions = [
        CompetitionEntity.from_match(m)
        for m in _dedupe_matches(competition_matches)
    ]

    return ExtractionResult(
        teams=teams,
        players=players,
        competitions=competitions,
        metrics=metrics,
        pronouns=pronouns,
    )


def _dedupe_matches(matches: List[EntityMatch]) -> List[EntityMatch]:
    """Remove duplicate matches, keeping highest confidence."""
    seen = set()
    unique = []
    for m in sorted(matches, key=lambda x: x.confidence, reverse=True):
        if m.entity_id not in seen:
            seen.add(m.entity_id)
            unique.append(m)
    return unique


# Global alias database instance
_alias_db: Optional[AliasDatabase] = None


def get_alias_database() -> AliasDatabase:
    """Get the global alias database instance."""
    global _alias_db
    if _alias_db is None:
        _alias_db = AliasDatabase()
    return _alias_db


def reload_aliases(path: Optional[str] = None) -> None:
    """Reload the alias database from disk."""
    global _alias_db
    _alias_db = AliasDatabase(path)

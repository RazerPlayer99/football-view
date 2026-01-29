"""Entity extraction for search using alias matching and fuzzy matching."""

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Any

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


def normalize_for_matching(text: str) -> str:
    """Normalize text for entity matching."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\-']", "", text)  # Keep hyphens and apostrophes
    text = re.sub(r"\s+", " ", text)
    return text


def fuzzy_match(query: str, target: str) -> float:
    """
    Calculate fuzzy match ratio between two strings.

    Uses Levenshtein distance if available, otherwise SequenceMatcher.
    Also checks for last-name-only matches.
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
        return self._match_entities(query, self.teams)

    def match_player(self, query: str) -> List[EntityMatch]:
        """Match query against player aliases."""
        return self._match_entities(query, self.players)

    def match_competition(self, query: str) -> List[EntityMatch]:
        """Match query against competition aliases."""
        return self._match_entities(query, self.competitions)

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
    ) -> List[EntityMatch]:
        """
        Match query against an entity database.

        Strategy:
        1. Exact alias match (confidence = 1.0)
        2. Fuzzy match against canonical names (confidence = ratio)
        3. Fuzzy match against aliases (confidence = ratio * 0.95)
        """
        query_normalized = normalize_for_matching(query)
        matches: List[EntityMatch] = []

        # Get dynamic threshold based on query length
        threshold = get_fuzzy_threshold(query_normalized)

        # Phase 1: Exact alias lookup
        for entity_id, entity_data in entities.items():
            aliases = [a.lower() for a in entity_data.get("aliases", [])]
            if query_normalized in aliases:
                return [EntityMatch(
                    entity_id=entity_id,
                    name=entity_data["canonical"],
                    confidence=1.0,
                    match_method="alias_exact",
                    matched_text=query,
                )]

        # Phase 2: Fuzzy matching
        for entity_id, entity_data in entities.items():
            canonical = entity_data["canonical"]

            # Check canonical name (includes last-name matching now)
            ratio = fuzzy_match(query_normalized, canonical)
            if ratio >= threshold:
                matches.append(EntityMatch(
                    entity_id=entity_id,
                    name=canonical,
                    confidence=ratio,
                    match_method="fuzzy_canonical",
                    matched_text=query,
                ))

            # Check aliases with slightly higher threshold
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

    # If no full match, try word-by-word
    if not team_matches and not player_matches:
        words = query_for_matching.split()
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

"""
Legacy search utilities (deprecated).

Deprecated in favor of app.utils.search.entities and the unified search pipeline.
"""
import warnings
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from app.utils.search.entities import AliasDatabase, normalize_for_matching

# Legacy file kept for compatibility, now pointing to unified aliases
ALIASES_FILE = Path(__file__).parent.parent / "data" / "aliases.json"

_alias_db: Optional[AliasDatabase] = None


def _warn_deprecated() -> None:
    warnings.warn(
        "app.search_utils is deprecated. Use app.utils.search.entities instead.",
        DeprecationWarning,
        stacklevel=2,
    )


def _get_alias_db() -> AliasDatabase:
    """Load aliases from unified JSON file (cached)."""
    global _alias_db
    if _alias_db is None:
        _alias_db = AliasDatabase(str(ALIASES_FILE))
    return _alias_db


def normalize_text(text: str) -> str:
    """Normalize text for search matching (legacy wrapper)."""
    _warn_deprecated()
    return normalize_for_matching(text or "")


def resolve_team_alias(query: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Check if query matches a team alias.
    Returns (canonical_name, team_id) or (None, None) if no match.
    """
    _warn_deprecated()
    alias_db = _get_alias_db()
    matches = alias_db.match_team(query)
    if not matches:
        return None, None
    match = matches[0]
    return match.name, int(match.entity_id)


def resolve_player_alias(query: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Check if query matches a player alias.
    Returns (canonical_name, player_id) or (None, None) if no match.
    """
    _warn_deprecated()
    alias_db = _get_alias_db()
    matches = alias_db.match_player(query)
    if not matches:
        return None, None
    match = matches[0]
    return match.name, int(match.entity_id)


def resolve_alias(query: str) -> Dict[str, Any]:
    """
    Resolve a query against both team and player aliases.
    Returns dict with resolution info.
    """
    _warn_deprecated()
    normalized = normalize_text(query)

    # Check team aliases
    team_canonical, team_id = resolve_team_alias(query)
    if team_canonical:
        return {
            "type": "team",
            "original_query": query,
            "normalized_query": normalized,
            "canonical": team_canonical,
            "id": team_id,
            "matched": True
        }

    # Check player aliases
    player_canonical, player_id = resolve_player_alias(query)
    if player_canonical:
        return {
            "type": "player",
            "original_query": query,
            "normalized_query": normalized,
            "canonical": player_canonical,
            "id": player_id,
            "matched": True
        }

    # No alias match - return normalized query
    return {
        "type": "unknown",
        "original_query": query,
        "normalized_query": normalized,
        "canonical": None,
        "id": None,
        "matched": False
    }


def get_search_queries(query: str) -> List[str]:
    """
    Get list of queries to try for search.
    Returns [canonical_name] if alias matched, otherwise [original_query].
    """
    resolution = resolve_alias(query)

    if resolution["matched"] and resolution["canonical"]:
        # Return both canonical and original to maximize matches
        return [resolution["canonical"], query]

    return [query]


def is_ambiguous_query(query: str) -> bool:
    """
    Check if a query is potentially ambiguous (very short or common name).
    """
    normalized = normalize_text(query)

    # Very short queries are often ambiguous
    if len(normalized) <= 3:
        return True

    # Common ambiguous first names
    ambiguous_names = {
        "john", "james", "david", "michael", "chris", "christian",
        "daniel", "alex", "alexander", "martin", "marcus", "max",
        "ben", "jack", "joe", "sam", "matt", "luke", "ryan", "adam"
    }

    if normalized in ambiguous_names:
        return True

    return False


def score_player_match(player: Dict[str, Any], query: str) -> float:
    """
    Score how well a player matches the query.
    Higher score = better match.
    """
    normalized_query = normalize_text(query)
    player_name = normalize_text(player.get("name", ""))

    score = 0.0

    # Exact match
    if player_name == normalized_query:
        score += 100

    # Name starts with query
    elif player_name.startswith(normalized_query):
        score += 50

    # Query is in name
    elif normalized_query in player_name:
        score += 25

    # Bonus for more appearances (more notable player)
    appearances = player.get("appearances", 0) or 0
    score += min(appearances * 0.5, 20)  # Cap at 20 bonus points

    # Bonus for goals/assists (more notable)
    goals = player.get("goals", 0) or 0
    assists = player.get("assists", 0) or 0
    score += min((goals + assists) * 0.3, 15)  # Cap at 15 bonus points

    return score


def rank_players(players: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """
    Rank players by relevance to query.
    """
    scored = [(player, score_player_match(player, query)) for player in players]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [player for player, score in scored]

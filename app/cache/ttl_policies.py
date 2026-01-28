"""
TTL configuration and endpoint-to-category mapping.
"""
from typing import Dict, Optional, Tuple, Any
from datetime import datetime

from .core import DataCategory


# TTL Configuration by category (in seconds)
TTL_CONFIG: Dict[DataCategory, Dict[str, Any]] = {
    DataCategory.LIVE_MATCH: {
        "fresh_ttl": 5,           # 5 seconds
        "stale_ttl": 0,           # No stale serving for live data
        "allow_swr": False,       # No stale-while-revalidate
    },
    DataCategory.SEMI_VOLATILE: {
        "fresh_ttl": 45,          # 45 seconds
        "stale_ttl": 30,          # Can serve stale for 30s more
        "allow_swr": False,       # No background refresh
    },
    DataCategory.STANDINGS: {
        "fresh_ttl": 120,         # 2 minutes normally
        "fresh_ttl_live": 60,     # 1 minute during live matches
        "stale_ttl": 300,         # 5 minutes stale window
        "allow_swr": True,        # Background refresh allowed
    },
    DataCategory.PLAYER_SEASON_STATS: {
        "fresh_ttl": 900,         # 15 minutes
        "stale_ttl": 1800,        # 30 minutes more stale
        "allow_swr": True,
    },
    DataCategory.TEAM_SEASON_STATS: {
        "fresh_ttl": 900,         # 15 minutes
        "stale_ttl": 1800,        # 30 minutes more stale
        "allow_swr": True,
    },
    DataCategory.STABLE_METADATA: {
        "fresh_ttl": 21600,       # 6 hours
        "stale_ttl": 64800,       # 18 more hours stale
        "allow_swr": True,
    },
}


def get_ttl_for_category(
    category: DataCategory,
    is_live_match_window: bool = False,
) -> Tuple[int, int, bool]:
    """
    Get TTL configuration for a data category.

    Args:
        category: The data category
        is_live_match_window: True if there are currently live matches

    Returns:
        (fresh_ttl, stale_ttl, allow_swr)
    """
    config = TTL_CONFIG.get(category, TTL_CONFIG[DataCategory.SEMI_VOLATILE])

    # Use shorter TTL for standings during live matches
    if category == DataCategory.STANDINGS and is_live_match_window:
        fresh_ttl = config.get("fresh_ttl_live", config["fresh_ttl"])
    else:
        fresh_ttl = config["fresh_ttl"]

    return (
        fresh_ttl,
        config.get("stale_ttl", 0),
        config.get("allow_swr", False),
    )


def get_category_for_endpoint(
    endpoint: str,
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> DataCategory:
    """
    Determine the data category for an endpoint + params combination.

    Args:
        endpoint: API endpoint path (e.g., "standings", "fixtures")
        params: Query parameters
        context: Additional context (e.g., fixture_status for dynamic categorization)

    Returns:
        DataCategory for caching behavior
    """
    context = context or {}

    # Standings
    if endpoint == "standings":
        return DataCategory.STANDINGS

    # Teams
    if endpoint == "teams":
        if "id" in params and params.get("id"):
            # Single team by ID - very stable
            return DataCategory.STABLE_METADATA
        else:
            # League teams list
            return DataCategory.TEAM_SEASON_STATS

    # Fixtures
    if endpoint == "fixtures":
        if "id" in params and params.get("id"):
            # Single fixture - depends on status
            status = context.get("fixture_status", "").upper()
            if status in ("1H", "2H", "HT", "ET", "P", "LIVE", "BT"):
                return DataCategory.LIVE_MATCH
            elif status in ("FT", "AET", "PEN"):
                return DataCategory.STABLE_METADATA
            else:
                # Upcoming or unknown
                return DataCategory.SEMI_VOLATILE
        else:
            # Fixture list
            return DataCategory.SEMI_VOLATILE

    # Players
    if endpoint == "players":
        if "id" in params and params.get("id"):
            # Single player stats
            return DataCategory.PLAYER_SEASON_STATS
        elif "search" in params:
            # Search results
            return DataCategory.SEMI_VOLATILE
        elif "team" in params:
            # Team squad
            return DataCategory.PLAYER_SEASON_STATS
        else:
            return DataCategory.SEMI_VOLATILE

    # Top scorers / assists
    if endpoint in ("players/topscorers", "players/topassists"):
        return DataCategory.PLAYER_SEASON_STATS

    # Player fixtures (match log)
    if endpoint == "players/fixtures":
        return DataCategory.SEMI_VOLATILE

    # Fixture player stats
    if endpoint == "fixtures/players":
        return _get_match_data_category(context)

    # Match events (goals, cards, subs)
    if endpoint == "fixtures/events":
        return _get_match_data_category(context)

    # Match lineups
    if endpoint == "fixtures/lineups":
        return _get_match_data_category(context)

    # Match statistics (possession, shots, etc.)
    if endpoint == "fixtures/statistics":
        return _get_match_data_category(context)

    # Default to semi-volatile
    return DataCategory.SEMI_VOLATILE


def _get_match_data_category(context: Optional[Dict[str, Any]]) -> DataCategory:
    """
    Determine category for match-related data based on fixture status.

    Used for events, lineups, statistics, and player stats endpoints.
    """
    context = context or {}
    status = context.get("fixture_status", "").upper()

    if status in ("1H", "2H", "HT", "ET", "P", "LIVE", "BT"):
        return DataCategory.LIVE_MATCH  # 5s TTL
    elif status in ("FT", "AET", "PEN"):
        return DataCategory.STABLE_METADATA  # 6h TTL
    else:
        return DataCategory.SEMI_VOLATILE  # 45s for upcoming/unknown


# Lineup-specific TTL based on time to kickoff
LINEUP_TTL_SCHEDULE = [
    # (min_hours_before, max_hours_before, predicted_ttl, confirmed_ttl)
    (24, float('inf'), 3600, 3600),       # >24h before: 1 hour
    (1.5, 24, 300, 60),                   # 90min-24h: 5min predicted, 1min confirmed
    (0, 1.5, 30, 10),                     # <90min pre-kickoff: 30s/10s
    (-2, 0, 300, 60),                     # In-play (0-2h after start): 5min/1min
    (float('-inf'), -2, 21600, 21600),    # Post-match: 6 hours
]


def get_lineup_ttl(
    kickoff_time: datetime,
    is_confirmed: bool,
) -> Tuple[int, int]:
    """
    Calculate TTL for lineup data based on time to kickoff.

    Args:
        kickoff_time: Match kickoff datetime (UTC)
        is_confirmed: True if lineup is confirmed, False if predicted

    Returns:
        (fresh_ttl_seconds, stale_ttl_seconds)
    """
    now = datetime.utcnow()
    hours_until = (kickoff_time - now).total_seconds() / 3600

    for min_h, max_h, pred_ttl, conf_ttl in LINEUP_TTL_SCHEDULE:
        if min_h <= hours_until < max_h:
            base_ttl = conf_ttl if is_confirmed else pred_ttl
            # No stale serving close to kickoff
            stale_ttl = 0 if hours_until < 2 else base_ttl // 2
            return base_ttl, stale_ttl

    # Default fallback
    return 300, 60

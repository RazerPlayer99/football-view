"""
Live Match module for Match Center functionality.

Provides abstracted access to live match data, designed for future
Firebase real-time support while currently using REST + tiered cache.
"""
from .models import (
    LiveMatchData,
    MatchDelta,
    MatchEvent,
    TeamLineup,
    LineupPlayer,
    MatchStat,
    TeamInfo,
    EventType,
)
from .provider import (
    LiveMatchProvider,
    RESTLiveMatchProvider,
    get_live_match_provider,
)

__all__ = [
    # Models
    "LiveMatchData",
    "MatchDelta",
    "MatchEvent",
    "TeamLineup",
    "LineupPlayer",
    "MatchStat",
    "TeamInfo",
    "EventType",
    # Provider
    "LiveMatchProvider",
    "RESTLiveMatchProvider",
    "get_live_match_provider",
]

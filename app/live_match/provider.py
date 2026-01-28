"""
Live Match Provider interface and REST implementation.

The provider pattern allows swapping REST polling for Firebase subscriptions
in the future without changing the UI layer.
"""
from typing import Protocol, Optional, Iterator, List, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import logging

from .models import (
    LiveMatchData,
    MatchDelta,
    MatchEvent,
    TeamLineup,
    LineupPlayer,
    MatchStat,
    TeamInfo,
)

logger = logging.getLogger("live_match.provider")


class LiveMatchProvider(Protocol):
    """
    Interface for live match data providers.

    Implementations:
    - RESTLiveMatchProvider: Uses api_client + tiered cache (current)
    - FirebaseLiveMatchProvider: Uses Firebase subscriptions (future)
    """

    def get_match(self, match_id: int, force_refresh: bool = False) -> LiveMatchData:
        """
        Get a complete snapshot of match data.

        Args:
            match_id: The fixture ID
            force_refresh: Bypass cache and fetch fresh data

        Returns:
            LiveMatchData with all available information
        """
        ...

    def get_events(self, match_id: int, force_refresh: bool = False) -> List[MatchEvent]:
        """Get match events only."""
        ...

    def get_lineups(
        self, match_id: int, force_refresh: bool = False
    ) -> Tuple[Optional[TeamLineup], Optional[TeamLineup]]:
        """Get match lineups (home, away)."""
        ...

    def get_statistics(self, match_id: int, force_refresh: bool = False) -> List[MatchStat]:
        """Get match statistics."""
        ...

    def subscribe_to_match(self, match_id: int) -> Iterator[MatchDelta]:
        """
        Subscribe to live match updates (future Firebase implementation).

        Yields MatchDelta objects as changes occur.
        For REST implementation, this is not supported.
        """
        ...


class RESTLiveMatchProvider:
    """
    REST implementation using api_client + tiered cache.

    Uses the existing api_client functions which leverage
    the advanced caching system with tiered TTL.
    """

    def __init__(self):
        # Import here to avoid circular imports
        from app import api_client
        self._api = api_client

    def get_match(self, match_id: int, force_refresh: bool = False) -> LiveMatchData:
        """
        Get complete match snapshot from REST API.

        Fetches basic match data, events, lineups, and statistics,
        then assembles them into a LiveMatchData object.
        """
        logger.debug(f"Fetching match {match_id} (force_refresh={force_refresh})")

        # Get basic match info first to determine status
        match_data = self._api.get_match_by_id(match_id, force_refresh=force_refresh)
        if not match_data:
            raise ValueError(f"Match {match_id} not found")

        fixture_status = match_data.get("status_short", "")
        home_team_id = match_data.get("home_team", {}).get("id")

        # Fetch additional data in parallel for faster load times
        with ThreadPoolExecutor(max_workers=3) as executor:
            events_future = executor.submit(
                self.get_events, match_id, force_refresh, fixture_status, home_team_id
            )
            lineups_future = executor.submit(
                self.get_lineups, match_id, force_refresh, fixture_status
            )
            stats_future = executor.submit(
                self.get_statistics, match_id, force_refresh, fixture_status, home_team_id
            )
            events = events_future.result()
            home_lineup, away_lineup = lineups_future.result()
            statistics = stats_future.result()

        # Build the LiveMatchData object
        home_team = match_data.get("home_team", {})
        away_team = match_data.get("away_team", {})
        league = match_data.get("league", {})
        halftime = match_data.get("halftime") or {}

        return LiveMatchData(
            id=match_id,
            status=match_data.get("status", ""),
            status_short=fixture_status,
            elapsed=match_data.get("elapsed"),
            extra_time=match_data.get("extra_time"),
            is_live=match_data.get("is_live", False),
            is_finished=match_data.get("is_finished", False),
            date=match_data.get("date", ""),
            venue=match_data.get("venue"),
            referee=match_data.get("referee"),
            home_team=TeamInfo(
                id=home_team.get("id", 0),
                name=home_team.get("name", ""),
                logo=home_team.get("logo", ""),
            ),
            away_team=TeamInfo(
                id=away_team.get("id", 0),
                name=away_team.get("name", ""),
                logo=away_team.get("logo", ""),
            ),
            home_goals=match_data.get("home_goals") or 0,
            away_goals=match_data.get("away_goals") or 0,
            halftime_home=halftime.get("home"),
            halftime_away=halftime.get("away"),
            league_id=league.get("id"),
            league_name=league.get("name"),
            league_logo=league.get("logo"),
            match_round=league.get("round"),
            events=events,
            home_lineup=home_lineup,
            away_lineup=away_lineup,
            statistics=statistics,
            last_updated=datetime.utcnow().isoformat() + "Z",
            data_source="rest",
        )

    def get_events(
        self,
        match_id: int,
        force_refresh: bool = False,
        fixture_status: Optional[str] = None,
        home_team_id: Optional[int] = None,
    ) -> List[MatchEvent]:
        """Get match events from REST API."""
        try:
            data = self._api.get_match_events(
                match_id,
                force_refresh=force_refresh,
                fixture_status=fixture_status,
            )

            events = []
            for e in data.get("events", []):
                team_id = e.get("team_id")
                events.append(MatchEvent(
                    minute=e.get("minute") or 0,
                    extra_time=e.get("extra_time"),
                    event_type=e.get("event_type", ""),
                    detail=e.get("detail", ""),
                    team_id=team_id or 0,
                    team_name=e.get("team_name", ""),
                    is_home=(team_id == home_team_id) if home_team_id else False,
                    player_id=e.get("player_id") or 0,
                    player_name=e.get("player_name", ""),
                    assist_id=e.get("assist_id"),
                    assist_name=e.get("assist_name"),
                    comments=e.get("comments"),
                ))

            return events
        except Exception as ex:
            logger.warning(f"Failed to fetch events for match {match_id}: {ex}")
            return []

    def get_lineups(
        self,
        match_id: int,
        force_refresh: bool = False,
        fixture_status: Optional[str] = None,
    ) -> Tuple[Optional[TeamLineup], Optional[TeamLineup]]:
        """Get match lineups from REST API."""
        try:
            data = self._api.get_match_lineups(
                match_id,
                force_refresh=force_refresh,
                fixture_status=fixture_status,
            )

            lineups = data.get("lineups", [])
            if len(lineups) < 2:
                return (None, None)

            result = []
            for lineup in lineups[:2]:
                starting_xi = [
                    LineupPlayer(
                        id=p.get("id") or 0,
                        name=p.get("name", ""),
                        number=p.get("number"),
                        position=p.get("position", ""),
                        grid=p.get("grid"),
                    )
                    for p in lineup.get("starting_xi", [])
                ]

                substitutes = [
                    LineupPlayer(
                        id=p.get("id") or 0,
                        name=p.get("name", ""),
                        number=p.get("number"),
                        position=p.get("position", ""),
                    )
                    for p in lineup.get("substitutes", [])
                ]

                result.append(TeamLineup(
                    team_id=lineup.get("team_id") or 0,
                    team_name=lineup.get("team_name", ""),
                    team_logo=lineup.get("team_logo", ""),
                    formation=lineup.get("formation"),
                    coach_name=lineup.get("coach_name"),
                    coach_photo=lineup.get("coach_photo"),
                    starting_xi=starting_xi,
                    substitutes=substitutes,
                ))

            return (result[0], result[1])
        except Exception as ex:
            logger.warning(f"Failed to fetch lineups for match {match_id}: {ex}")
            return (None, None)

    def get_statistics(
        self,
        match_id: int,
        force_refresh: bool = False,
        fixture_status: Optional[str] = None,
        home_team_id: Optional[int] = None,
    ) -> List[MatchStat]:
        """Get match statistics from REST API."""
        try:
            data = self._api.get_match_statistics(
                match_id,
                force_refresh=force_refresh,
                fixture_status=fixture_status,
            )

            team_stats = data.get("team_statistics", [])
            if len(team_stats) < 2:
                return []

            # Determine which is home/away
            home_stats = team_stats[0]
            away_stats = team_stats[1]

            # If we know home_team_id, ensure correct ordering
            if home_team_id and team_stats[1].get("team_id") == home_team_id:
                home_stats, away_stats = away_stats, home_stats

            # Build stat comparisons
            home_dict = home_stats.get("statistics", {})
            away_dict = away_stats.get("statistics", {})

            # Combine all stat types from both teams
            all_stat_types = set(home_dict.keys()) | set(away_dict.keys())

            statistics = []
            for stat_type in all_stat_types:
                statistics.append(MatchStat(
                    stat_type=stat_type,
                    home_value=home_dict.get(stat_type),
                    away_value=away_dict.get(stat_type),
                ))

            return statistics
        except Exception as ex:
            logger.warning(f"Failed to fetch statistics for match {match_id}: {ex}")
            return []

    def subscribe_to_match(self, match_id: int) -> Iterator[MatchDelta]:
        """
        Not supported in REST implementation.

        For real-time updates with REST, use polling with get_match().
        """
        raise NotImplementedError(
            "subscribe_to_match is not supported in REST implementation. "
            "Use get_match() with polling instead, or switch to Firebase provider."
        )


# Singleton factory
_provider: Optional[LiveMatchProvider] = None


def get_live_match_provider() -> LiveMatchProvider:
    """
    Get the live match provider instance.

    Currently returns RESTLiveMatchProvider.
    In future, could return FirebaseLiveMatchProvider for live matches.
    """
    global _provider
    if _provider is None:
        _provider = RESTLiveMatchProvider()
    return _provider

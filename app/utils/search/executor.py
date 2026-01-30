"""Query execution - maps intents to API calls."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import date, timedelta

from .models.intent import IntentType, IntentResult
from .resolver import ResolvedQuery
from config.settings import settings


@dataclass
class ExecutionResult:
    """Result of query execution."""
    success: bool
    data: Dict[str, Any]
    sources_used: List[str] = field(default_factory=list)
    missing_capabilities: List[str] = field(default_factory=list)
    error: Optional[str] = None


class QueryExecutor:
    """
    Executes resolved queries by calling api_client functions.

    Maps each intent type to the appropriate API calls and
    tracks data sources used and missing capabilities.
    """

    def __init__(self, default_season: int = None):
        self.default_season = default_season or settings.current_season

    def execute(self, resolved: ResolvedQuery) -> ExecutionResult:
        """
        Execute a resolved query.

        Args:
            resolved: ResolvedQuery with intent, entities, and assumptions

        Returns:
            ExecutionResult with data and metadata
        """
        intent_type = resolved.intent.intent_type

        # Route to appropriate handler
        handlers = {
            IntentType.STANDINGS: self._execute_standings,
            IntentType.TOP_SCORERS: self._execute_top_scorers,
            IntentType.TOP_ASSISTS: self._execute_top_assists,
            IntentType.MATCH_LOOKUP: self._execute_match_lookup,
            IntentType.TEAM_LOOKUP: self._execute_team_lookup,
            IntentType.PLAYER_LOOKUP: self._execute_player_lookup,
            IntentType.SCHEDULE: self._execute_schedule,
            IntentType.COMPARISON: self._execute_comparison,
            IntentType.CHART_REQUEST: self._execute_chart_request,
        }

        handler = handlers.get(intent_type)
        if not handler:
            return ExecutionResult(
                success=False,
                data={},
                error=f"Unsupported intent type: {intent_type}",
            )

        try:
            return handler(resolved)
        except Exception as e:
            return ExecutionResult(
                success=False,
                data={},
                error=str(e),
            )

    def _get_season(self, resolved: ResolvedQuery) -> int:
        """Get season from time modifier or default."""
        if resolved.intent.time_modifier and resolved.intent.time_modifier.season_year:
            return resolved.intent.time_modifier.season_year
        return self.default_season

    def _execute_standings(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute standings query."""
        from app import api_client

        season = self._get_season(resolved)
        league_id = resolved.primary_competition.league_id if resolved.primary_competition else None
        if league_id is None:
            return ExecutionResult(
                success=False,
                data={},
                error="League required for standings. Try 'La Liga standings'.",
            )

        data = api_client.get_standings(season, league_id)

        return ExecutionResult(
            success=True,
            data={
                "standings": data.get("standings", []),
                "league_id": league_id,
                "season": season,
            },
            sources_used=["api_football:standings"],
        )

    def _execute_top_scorers(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute top scorers query."""
        from app import api_client

        season = self._get_season(resolved)
        league_id = resolved.primary_competition.league_id if resolved.primary_competition else None
        if league_id is None:
            return ExecutionResult(
                success=False,
                data={},
                error="League required for top scorers. Try 'Bundesliga top scorers'.",
            )

        data = api_client.get_top_scorers(season, league_id=league_id, limit=20)

        return ExecutionResult(
            success=True,
            data={
                "scorers": data.get("players", []),
                "league_id": league_id,
                "season": season,
            },
            sources_used=["api_football:players/topscorers"],
        )

    def _execute_top_assists(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute top assists query."""
        from app import api_client

        season = self._get_season(resolved)
        league_id = resolved.primary_competition.league_id if resolved.primary_competition else None
        if league_id is None:
            return ExecutionResult(
                success=False,
                data={},
                error="League required for top assists. Try 'Serie A top assists'.",
            )

        data = api_client.get_top_assists(season, league_id=league_id, limit=20)

        return ExecutionResult(
            success=True,
            data={
                "assists": data.get("players", []),
                "league_id": league_id,
                "season": season,
            },
            sources_used=["api_football:players/topassists"],
        )

    def _execute_match_lookup(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute match lookup query."""
        from app import api_client

        season = self._get_season(resolved)
        sources = []
        missing = []

        # Check if we have two teams (vs query)
        if resolved.primary_team and resolved.secondary_team:
            # Head-to-head lookup
            team1_id = resolved.primary_team.team_id
            team2_id = resolved.secondary_team.team_id

            # Get fixtures for team1 and filter for team2
            fixtures_data = api_client.get_matches(
                season,
                league_id=None,  # All leagues
                team_id=team1_id,
                limit=20,
            )
            sources.append("api_football:fixtures")

            fixtures = fixtures_data.get("matches", [])
            h2h_fixtures = [
                f for f in fixtures
                if f.get("home_team_id") == team2_id or f.get("away_team_id") == team2_id
            ]

            # Get next fixture between these teams
            upcoming = [f for f in h2h_fixtures if f.get("status") in ("NS", "TBD", "PST")]
            past = [f for f in h2h_fixtures if f.get("status") in ("FT", "AET", "PEN")]

            return ExecutionResult(
                success=True,
                data={
                    "h2h_fixtures": h2h_fixtures[:10],
                    "upcoming": upcoming[:1] if upcoming else None,
                    "recent": past[:5],
                    "team1": {
                        "id": team1_id,
                        "name": resolved.primary_team.name,
                    },
                    "team2": {
                        "id": team2_id,
                        "name": resolved.secondary_team.name,
                    },
                },
                sources_used=sources,
            )

        elif resolved.primary_team:
            # Single team's fixtures
            team_id = resolved.primary_team.team_id

            # Check time modifier
            time_mod = resolved.intent.time_modifier
            if time_mod and time_mod.modifier_type == "future":
                # Next N games
                limit = time_mod.count or 5
                fixtures_data = api_client.get_matches(
                    season, league_id=None, team_id=team_id, limit=limit * 2
                )
                fixtures = fixtures_data.get("matches", [])
                upcoming = [f for f in fixtures if f.get("status") in ("NS", "TBD", "PST")]
                data = {"upcoming": upcoming[:limit], "team_id": team_id}

            elif time_mod and time_mod.modifier_type == "past":
                # Last N games
                limit = time_mod.count or 5
                fixtures_data = api_client.get_matches(
                    season, league_id=None, team_id=team_id, limit=limit * 2
                )
                fixtures = fixtures_data.get("matches", [])
                past = [f for f in fixtures if f.get("status") in ("FT", "AET", "PEN")]
                data = {"recent": past[:limit], "team_id": team_id}

            else:
                # Default: next upcoming match
                fixtures_data = api_client.get_matches(
                    season, league_id=None, team_id=team_id, limit=10
                )
                fixtures = fixtures_data.get("matches", [])
                upcoming = [f for f in fixtures if f.get("status") in ("NS", "TBD", "PST")]
                data = {
                    "next_match": upcoming[0] if upcoming else None,
                    "upcoming": upcoming[:3],
                    "team_id": team_id,
                    "team_name": resolved.primary_team.name,
                }

            sources.append("api_football:fixtures")
            return ExecutionResult(success=True, data=data, sources_used=sources)

        return ExecutionResult(
            success=False,
            data={},
            error="No team specified for match lookup",
        )

    def _execute_team_lookup(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute team lookup query."""
        from app import api_client
        from app.api_client import SUPPORTED_LEAGUES
        from concurrent.futures import ThreadPoolExecutor

        if not resolved.primary_team:
            return ExecutionResult(
                success=False,
                data={},
                error="No team found",
            )

        team_id = resolved.primary_team.team_id
        season = self._get_season(resolved)
        sources = []
        missing = []

        # First get team info to determine league
        try:
            team_data = api_client.get_team_by_id(team_id)
            sources.append("api_football:teams")
        except Exception:
            team_data = {"team_id": team_id, "name": resolved.primary_team.name}

        # Determine which league this team plays in
        team_league_id = resolved.primary_team.league_id
        team_standing = None
        league_name = None

        # If we don't have league_id from alias, try to find team in supported leagues
        if not team_league_id:
            for league_id in SUPPORTED_LEAGUES.keys():
                try:
                    standings_data = api_client.get_standings(season, league_id)
                    standings = standings_data.get("standings", [])
                    team_standing = next(
                        (s for s in standings if s.get("team", {}).get("id") == team_id),
                        None
                    )
                    if team_standing:
                        team_league_id = league_id
                        league_name = SUPPORTED_LEAGUES.get(league_id)
                        sources.append("api_football:standings")
                        break
                except Exception:
                    continue
        else:
            # Fetch standings for the known league
            try:
                standings_data = api_client.get_standings(season, team_league_id)
                standings = standings_data.get("standings", [])
                team_standing = next(
                    (s for s in standings if s.get("team", {}).get("id") == team_id),
                    None
                )
                league_name = SUPPORTED_LEAGUES.get(team_league_id, f"League {team_league_id}")
                sources.append("api_football:standings")
            except Exception:
                team_standing = None

        # Parallel data fetching for remaining data
        with ThreadPoolExecutor(max_workers=2) as executor:
            fixtures_future = executor.submit(
                api_client.get_matches, season, league_id=None, team_id=team_id, limit=10
            )
            squad_future = executor.submit(api_client.get_team_players, team_id, season)

        try:
            fixtures_data = fixtures_future.result()
            fixtures = fixtures_data.get("matches", [])
            sources.append("api_football:fixtures")
        except Exception:
            fixtures = []

        try:
            squad_data = squad_future.result()
            # Sort players by goals to get actual top scorers
            players = squad_data.get("players", [])
            top_scorers = sorted(players, key=lambda p: p.get("goals", 0), reverse=True)[:5]
            sources.append("api_football:players")
        except Exception:
            top_scorers = []

        # Check for xG data (not yet implemented)
        missing.append("xG statistics not yet available")

        # Fixture status is the long form, not short codes
        finished_statuses = ("Match Finished", "After Extra Time", "Penalties")
        upcoming_statuses = ("Not Started", "Time to be defined", "TBD")

        return ExecutionResult(
            success=True,
            data={
                "team": team_data,
                "standing": team_standing,
                "league_id": team_league_id,
                "league_name": league_name,
                "recent_fixtures": [f for f in fixtures if f.get("status") in finished_statuses][:5],
                "upcoming_fixtures": [f for f in fixtures if f.get("status") in upcoming_statuses][:3],
                "top_players": top_scorers,
                "season": season,
            },
            sources_used=sources,
            missing_capabilities=missing,
        )

    def _execute_player_lookup(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute player lookup query."""
        from app import api_client

        if not resolved.primary_player:
            return ExecutionResult(
                success=False,
                data={},
                error="No player found",
            )

        player_id = resolved.primary_player.player_id
        season = self._get_season(resolved)
        sources = []
        missing = []

        try:
            player_data = api_client.get_player_by_id(player_id, season)
            sources.append("api_football:players")
        except Exception as e:
            return ExecutionResult(
                success=False,
                data={},
                error=f"Failed to fetch player: {e}",
            )

        # Try to get match log
        try:
            match_log = api_client.get_player_match_log(player_id, season, limit=5)
            sources.append("api_football:fixtures/players")
        except Exception:
            match_log = {"matches": []}

        # xG not available
        missing.append("Per-match xG not yet available")

        return ExecutionResult(
            success=True,
            data={
                "player": player_data,
                "recent_matches": match_log.get("matches", []),
                "season": season,
            },
            sources_used=sources,
            missing_capabilities=missing,
        )

    def _execute_schedule(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute schedule/fixtures query."""
        from app import api_client

        season = self._get_season(resolved)
        sources = []

        # Determine date range from time modifier
        time_mod = resolved.intent.time_modifier
        start_date = date.today()
        end_date = start_date + timedelta(days=7)

        if time_mod:
            if time_mod.start_date:
                start_date = time_mod.start_date
            if time_mod.end_date:
                end_date = time_mod.end_date
            elif time_mod.relative == "weekend":
                # This weekend
                days_to_saturday = (5 - start_date.weekday()) % 7
                start_date = start_date + timedelta(days=days_to_saturday)
                end_date = start_date + timedelta(days=1)

        # Fetch fixtures
        if resolved.primary_team:
            fixtures_data = api_client.get_matches(
                season,
                league_id=None,
                team_id=resolved.primary_team.team_id,
                limit=20,
            )
        else:
            # All fixtures in date range
            from app.api_client import get_matches_multi_league, SUPPORTED_LEAGUES
            fixtures_data = get_matches_multi_league(
                season,
                list(SUPPORTED_LEAGUES.keys()),
                from_date=start_date.isoformat(),
                to_date=end_date.isoformat(),
            )

        sources.append("api_football:fixtures")

        fixtures = fixtures_data.get("matches", [])

        return ExecutionResult(
            success=True,
            data={
                "fixtures": fixtures,
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "team_id": resolved.primary_team.team_id if resolved.primary_team else None,
            },
            sources_used=sources,
        )

    def _execute_comparison(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute comparison query."""
        from app import api_client
        from app.api_client import SUPPORTED_LEAGUES

        season = self._get_season(resolved)
        sources = []
        missing = []

        # Determine if team or player comparison
        if len(resolved.teams) >= 2:
            # Team comparison
            team1 = resolved.teams[0]
            team2 = resolved.teams[1]

            # Get standings for both teams - they may be in different leagues
            team1_standing = {}
            team2_standing = {}
            team1_league_name = None
            team2_league_name = None

            # Check team1's league first, then all supported leagues
            leagues_to_check = []
            if team1.league_id:
                leagues_to_check.append(team1.league_id)
            if team2.league_id and team2.league_id != team1.league_id:
                leagues_to_check.append(team2.league_id)
            leagues_to_check.extend([lid for lid in SUPPORTED_LEAGUES.keys()
                                    if lid not in leagues_to_check])

            for league_id in leagues_to_check:
                if team1_standing and team2_standing:
                    break  # Found both
                try:
                    standings_data = api_client.get_standings(season, league_id)
                    standings = standings_data.get("standings", [])
                    sources.append(f"api_football:standings:{league_id}")

                    if not team1_standing:
                        found = next((s for s in standings if s.get("team", {}).get("id") == team1.team_id), None)
                        if found:
                            team1_standing = found
                            team1_league_name = SUPPORTED_LEAGUES.get(league_id)

                    if not team2_standing:
                        found = next((s for s in standings if s.get("team", {}).get("id") == team2.team_id), None)
                        if found:
                            team2_standing = found
                            team2_league_name = SUPPORTED_LEAGUES.get(league_id)
                except Exception:
                    continue

            return ExecutionResult(
                success=True,
                data={
                    "comparison_type": "team",
                    "entities": [
                        {"team": {"id": team1.team_id, "name": team1.name, "league": team1_league_name}, "stats": team1_standing},
                        {"team": {"id": team2.team_id, "name": team2.name, "league": team2_league_name}, "stats": team2_standing},
                    ],
                    "cross_league": team1_league_name != team2_league_name if team1_league_name and team2_league_name else False,
                },
                sources_used=list(set(sources)),  # Dedupe sources
            )

        elif len(resolved.players) >= 2:
            # Player comparison
            player1 = resolved.players[0]
            player2 = resolved.players[1]

            try:
                p1_data = api_client.get_player_by_id(player1.player_id, season)
                p2_data = api_client.get_player_by_id(player2.player_id, season)
                sources.append("api_football:players")
            except Exception as e:
                return ExecutionResult(success=False, data={}, error=str(e))

            return ExecutionResult(
                success=True,
                data={
                    "comparison_type": "player",
                    "entities": [
                        {"player": p1_data},
                        {"player": p2_data},
                    ],
                },
                sources_used=sources,
                missing_capabilities=["xG comparison not yet available"],
            )

        return ExecutionResult(
            success=False,
            data={},
            error="Need two entities for comparison",
        )

    def _execute_chart_request(self, resolved: ResolvedQuery) -> ExecutionResult:
        """Execute chart request - returns chart spec for client rendering."""
        sources = []

        # Chart rendering is deferred to client
        # Return chart specification
        return ExecutionResult(
            success=True,
            data={
                "chart_spec": {
                    "chart_type": "bar",
                    "title": "Chart visualization",
                    "render_hint": "client_render",
                    "message": "Chart rendering coming in Phase 4",
                },
            },
            sources_used=sources,
            missing_capabilities=["Chart visualization deferred to Phase 4"],
        )


def execute_query(
    resolved: ResolvedQuery,
    default_season: int = None,
) -> ExecutionResult:
    """Convenience function to execute a query."""
    executor = QueryExecutor(default_season or settings.current_season)
    return executor.execute(resolved)

"""Response formatting for search results."""

from datetime import datetime
from typing import List, Optional

from .models.intent import IntentType
from .models.responses import (
    SearchResponse,
    TablePayload,
    MatchCardPayload,
    TeamCardPayload,
    PlayerCardPayload,
    ComparisonPayload,
    ComparisonMetric,
    ChartSpecPayload,
    ColumnDef,
    AxisSpec,
    SessionUpdate,
    QueryMeta,
    error_response,
    disambiguation_response,
)
from .resolver import ResolvedQuery
from .executor import ExecutionResult


class ResponseFormatter:
    """
    Formats execution results into SearchResponse envelopes.

    Selects appropriate response type based on intent and builds
    the complete response with metadata.
    """

    def format(
        self,
        resolved: ResolvedQuery,
        result: ExecutionResult,
        original_query: str,
        normalized_query: str,
        latency_ms: int,
    ) -> SearchResponse:
        """
        Format an execution result into a SearchResponse.

        Args:
            resolved: The resolved query
            result: Execution result from QueryExecutor
            original_query: Original user query
            normalized_query: Normalized query
            latency_ms: Query execution time

        Returns:
            Complete SearchResponse
        """
        if not result.success:
            return error_response(
                error_type="execution_error",
                message=result.error or "Query execution failed",
                suggestions=["Try a different search term"],
            )

        intent_type = resolved.intent.intent_type

        # Route to appropriate formatter
        formatters = {
            IntentType.STANDINGS: self._format_standings,
            IntentType.TOP_SCORERS: self._format_top_scorers,
            IntentType.TOP_ASSISTS: self._format_top_assists,
            IntentType.MATCH_LOOKUP: self._format_match_lookup,
            IntentType.TEAM_LOOKUP: self._format_team_lookup,
            IntentType.PLAYER_LOOKUP: self._format_player_lookup,
            IntentType.SCHEDULE: self._format_schedule,
            IntentType.COMPARISON: self._format_comparison,
            IntentType.CHART_REQUEST: self._format_chart,
        }

        formatter = formatters.get(intent_type)
        if not formatter:
            return error_response(
                error_type="unsupported_intent",
                message=f"Cannot format response for intent: {intent_type}",
            )

        response = formatter(result)

        # Attach metadata
        response.sources_used = result.sources_used
        response.assumptions = resolved.assumptions
        response.missing_capabilities = result.missing_capabilities
        response.session_update = resolved.session_update
        response._meta = QueryMeta(
            original_query=original_query,
            normalized_query=normalized_query,
            intent=intent_type.value,
            intent_confidence=resolved.intent.confidence,
            used_llm=resolved.intent.used_llm,
            latency_ms=latency_ms,
            entities=self._format_entities(resolved),
        )

        return response

    def _format_entities(self, resolved: ResolvedQuery) -> List[str]:
        """Format entities for metadata."""
        entities = []
        for team in resolved.teams:
            entities.append(f"team:{team.team_id}")
        for player in resolved.players:
            entities.append(f"player:{player.player_id}")
        for comp in resolved.competitions:
            entities.append(f"competition:{comp.league_id}")
        return entities

    def _format_standings(self, result: ExecutionResult) -> SearchResponse:
        """Format standings as table."""
        standings = result.data.get("standings", [])

        columns = [
            ColumnDef(key="position", label="Pos", align="center"),
            ColumnDef(key="team_name", label="Team", align="left"),
            ColumnDef(key="played", label="P", align="center"),
            ColumnDef(key="won", label="W", align="center"),
            ColumnDef(key="drawn", label="D", align="center"),
            ColumnDef(key="lost", label="L", align="center"),
            ColumnDef(key="goals_for", label="GF", align="center"),
            ColumnDef(key="goals_against", label="GA", align="center"),
            ColumnDef(key="goal_difference", label="GD", align="center"),
            ColumnDef(key="points", label="Pts", align="center", sortable=True),
        ]

        rows = [
            {
                "position": s.get("position"),
                "team_id": s.get("team_id"),
                "team_name": s.get("team_name"),
                "team_logo": s.get("team_logo"),
                "played": s.get("played"),
                "won": s.get("won"),
                "drawn": s.get("drawn"),
                "lost": s.get("lost"),
                "goals_for": s.get("goals_for"),
                "goals_against": s.get("goals_against"),
                "goal_difference": s.get("goal_difference"),
                "points": s.get("points"),
                "form": s.get("form"),
            }
            for s in standings
        ]

        return SearchResponse(
            type="table",
            data=TablePayload(
                title="League Standings",
                columns=columns,
                rows=rows,
                sort_by="position",
                sort_order="asc",
            ),
        )

    def _format_top_scorers(self, result: ExecutionResult) -> SearchResponse:
        """Format top scorers as table."""
        scorers = result.data.get("scorers", [])

        columns = [
            ColumnDef(key="rank", label="#", align="center"),
            ColumnDef(key="player_name", label="Player", align="left"),
            ColumnDef(key="team_name", label="Team", align="left"),
            ColumnDef(key="goals", label="Goals", align="center", sortable=True),
            ColumnDef(key="assists", label="Assists", align="center"),
            ColumnDef(key="appearances", label="Apps", align="center"),
        ]

        rows = [
            {
                "rank": i + 1,
                "player_id": s.get("id"),
                "player_name": s.get("name"),
                "team_id": s.get("team", {}).get("id"),
                "team_name": s.get("team", {}).get("name"),
                "goals": s.get("goals"),
                "assists": s.get("assists"),
                "appearances": s.get("appearances"),
            }
            for i, s in enumerate(scorers)
        ]

        return SearchResponse(
            type="table",
            data=TablePayload(
                title="Top Scorers",
                columns=columns,
                rows=rows,
                sort_by="goals",
                sort_order="desc",
            ),
        )

    def _format_top_assists(self, result: ExecutionResult) -> SearchResponse:
        """Format top assists as table."""
        assists = result.data.get("assists", [])

        columns = [
            ColumnDef(key="rank", label="#", align="center"),
            ColumnDef(key="player_name", label="Player", align="left"),
            ColumnDef(key="team_name", label="Team", align="left"),
            ColumnDef(key="assists", label="Assists", align="center", sortable=True),
            ColumnDef(key="goals", label="Goals", align="center"),
            ColumnDef(key="appearances", label="Apps", align="center"),
        ]

        rows = [
            {
                "rank": i + 1,
                "player_id": s.get("id"),
                "player_name": s.get("name"),
                "team_id": s.get("team", {}).get("id"),
                "team_name": s.get("team", {}).get("name"),
                "assists": s.get("assists"),
                "goals": s.get("goals"),
                "appearances": s.get("appearances"),
            }
            for i, s in enumerate(assists)
        ]

        return SearchResponse(
            type="table",
            data=TablePayload(
                title="Top Assists",
                columns=columns,
                rows=rows,
                sort_by="assists",
                sort_order="desc",
            ),
        )

    def _format_match_lookup(self, result: ExecutionResult) -> SearchResponse:
        """Format match lookup as match card."""
        data = result.data

        # Check what type of result we have
        if data.get("h2h_fixtures"):
            # H2H result
            fixtures = data.get("h2h_fixtures", [])
            upcoming = data.get("upcoming")
            recent = data.get("recent", [])

            primary_fixture = upcoming if upcoming else (recent[0] if recent else None)

            return SearchResponse(
                type="match_card",
                data=MatchCardPayload(
                    fixture=primary_fixture or {},
                    h2h_recent=recent[:5],
                    home_form=[],  # Would need additional data
                    away_form=[],
                ),
            )

        elif data.get("next_match"):
            # Single team's next match
            return SearchResponse(
                type="match_card",
                data=MatchCardPayload(
                    fixture=data.get("next_match", {}),
                    h2h_recent=[],
                    home_form=[],
                    away_form=[],
                ),
            )

        elif data.get("upcoming"):
            # List of upcoming matches
            upcoming = data.get("upcoming", [])
            return SearchResponse(
                type="table",
                data=TablePayload(
                    title=f"Upcoming Matches",
                    columns=[
                        ColumnDef(key="date", label="Date", align="left"),
                        ColumnDef(key="home_team", label="Home", align="left"),
                        ColumnDef(key="away_team", label="Away", align="left"),
                        ColumnDef(key="competition", label="Competition", align="left"),
                    ],
                    rows=[
                        {
                            "fixture_id": f.get("fixture_id"),
                            "date": f.get("date"),
                            "home_team": f.get("home_team_name"),
                            "away_team": f.get("away_team_name"),
                            "competition": f.get("league_name", ""),
                        }
                        for f in upcoming
                    ],
                ),
            )

        elif data.get("recent"):
            # List of recent matches
            recent = data.get("recent", [])
            return SearchResponse(
                type="table",
                data=TablePayload(
                    title=f"Recent Results",
                    columns=[
                        ColumnDef(key="date", label="Date", align="left"),
                        ColumnDef(key="result", label="Result", align="center"),
                        ColumnDef(key="competition", label="Competition", align="left"),
                    ],
                    rows=[
                        {
                            "fixture_id": f.get("fixture_id"),
                            "date": f.get("date"),
                            "result": f"{f.get('home_team_name')} {f.get('home_score', 0)}-{f.get('away_score', 0)} {f.get('away_team_name')}",
                            "competition": f.get("league_name", ""),
                        }
                        for f in recent
                    ],
                ),
            )

        return error_response(
            error_type="no_data",
            message="No match data found",
        )

    def _format_team_lookup(self, result: ExecutionResult) -> SearchResponse:
        """Format team lookup as team card."""
        data = result.data
        team = data.get("team", {})
        standing = data.get("standing", {})

        return SearchResponse(
            type="team_card",
            data=TeamCardPayload(
                team=team,
                standings_position=standing.get("position", 0) if standing else 0,
                recent_results=data.get("recent_fixtures", []),
                upcoming=data.get("upcoming_fixtures", []),
                top_scorer=data.get("top_players", [{}])[0] if data.get("top_players") else None,
            ),
        )

    def _format_player_lookup(self, result: ExecutionResult) -> SearchResponse:
        """Format player lookup as player card."""
        data = result.data
        player = data.get("player", {})

        # Stats are in season_totals, not at top level
        season_totals = player.get("season_totals", {})
        goals = season_totals.get("goals", 0)
        assists = season_totals.get("assists", 0)
        appearances = season_totals.get("appearances", 0)
        minutes = season_totals.get("minutes", 0)

        # Extract team info from premier_league or first competition
        pl_stats = player.get("premier_league") or {}
        competitions = player.get("competitions", [])
        first_comp = competitions[0] if competitions else {}

        team_name = pl_stats.get("team") or first_comp.get("team") or ""
        team_id = pl_stats.get("team_id") or first_comp.get("team_id")

        # Add team info to player dict for display
        player_with_team = dict(player)
        player_with_team["team"] = {"name": team_name, "id": team_id}

        # Extract per-90 stats if available
        per_90 = {}
        if minutes and minutes >= 450:
            per_90["goals_per90"] = round((goals / minutes) * 90, 2)
            per_90["assists_per90"] = round((assists / minutes) * 90, 2)

        return SearchResponse(
            type="player_card",
            data=PlayerCardPayload(
                player=player_with_team,
                season_stats={
                    "goals": goals,
                    "assists": assists,
                    "appearances": appearances,
                    "minutes": minutes,
                },
                recent_matches=data.get("recent_matches", []),
                per_90_stats=per_90,
            ),
        )

    def _format_schedule(self, result: ExecutionResult) -> SearchResponse:
        """Format schedule as table."""
        fixtures = result.data.get("fixtures", [])
        date_range = result.data.get("date_range", {})

        title = "Fixtures"
        if date_range:
            title = f"Fixtures: {date_range.get('start')} to {date_range.get('end')}"

        columns = [
            ColumnDef(key="date", label="Date", align="left"),
            ColumnDef(key="time", label="Time", align="center"),
            ColumnDef(key="home_team", label="Home", align="left"),
            ColumnDef(key="away_team", label="Away", align="left"),
            ColumnDef(key="competition", label="Competition", align="left"),
        ]

        rows = [
            {
                "fixture_id": f.get("fixture_id"),
                "date": f.get("date", "")[:10] if f.get("date") else "",
                "time": f.get("time", ""),
                "home_team": f.get("home_team_name"),
                "away_team": f.get("away_team_name"),
                "competition": f.get("league_name", ""),
            }
            for f in fixtures
        ]

        return SearchResponse(
            type="table",
            data=TablePayload(
                title=title,
                columns=columns,
                rows=rows,
            ),
        )

    def _format_comparison(self, result: ExecutionResult) -> SearchResponse:
        """Format comparison."""
        data = result.data
        comparison_type = data.get("comparison_type", "unknown")
        entities = data.get("entities", [])

        if comparison_type == "team":
            metrics = [
                ComparisonMetric(
                    metric_id="position",
                    label="League Position",
                    values=[e.get("stats", {}).get("position") for e in entities],
                    winner_index=0 if entities[0].get("stats", {}).get("position", 99) < entities[1].get("stats", {}).get("position", 99) else 1,
                ),
                ComparisonMetric(
                    metric_id="points",
                    label="Points",
                    values=[e.get("stats", {}).get("points") for e in entities],
                    winner_index=0 if (entities[0].get("stats", {}).get("points") or 0) > (entities[1].get("stats", {}).get("points") or 0) else 1,
                ),
                ComparisonMetric(
                    metric_id="goals_for",
                    label="Goals Scored",
                    values=[e.get("stats", {}).get("goals_for") for e in entities],
                    winner_index=0 if (entities[0].get("stats", {}).get("goals_for") or 0) > (entities[1].get("stats", {}).get("goals_for") or 0) else 1,
                ),
                ComparisonMetric(
                    metric_id="goals_against",
                    label="Goals Conceded",
                    values=[e.get("stats", {}).get("goals_against") for e in entities],
                    winner_index=0 if (entities[0].get("stats", {}).get("goals_against") or 99) < (entities[1].get("stats", {}).get("goals_against") or 99) else 1,
                ),
            ]
        else:
            # Player comparison - stats are in season_totals
            def get_player_stat(entity, stat):
                player = entity.get("player", {})
                # Stats can be in season_totals or directly on player
                totals = player.get("season_totals", {})
                return totals.get(stat) or player.get(stat)

            p1_goals = get_player_stat(entities[0], "goals") or 0
            p2_goals = get_player_stat(entities[1], "goals") or 0
            p1_assists = get_player_stat(entities[0], "assists") or 0
            p2_assists = get_player_stat(entities[1], "assists") or 0
            p1_apps = get_player_stat(entities[0], "appearances") or 0
            p2_apps = get_player_stat(entities[1], "appearances") or 0

            metrics = [
                ComparisonMetric(
                    metric_id="goals",
                    label="Goals",
                    values=[p1_goals, p2_goals],
                    winner_index=0 if p1_goals > p2_goals else (1 if p2_goals > p1_goals else None),
                ),
                ComparisonMetric(
                    metric_id="assists",
                    label="Assists",
                    values=[p1_assists, p2_assists],
                    winner_index=0 if p1_assists > p2_assists else (1 if p2_assists > p1_assists else None),
                ),
                ComparisonMetric(
                    metric_id="appearances",
                    label="Appearances",
                    values=[p1_apps, p2_apps],
                ),
            ]

        return SearchResponse(
            type="comparison",
            data=ComparisonPayload(
                entity_type=comparison_type,
                entities=entities,
                comparison_metrics=metrics,
            ),
        )

    def _format_chart(self, result: ExecutionResult) -> SearchResponse:
        """Format chart request."""
        chart_spec = result.data.get("chart_spec", {})

        return SearchResponse(
            type="chart_spec",
            data=ChartSpecPayload(
                chart_type=chart_spec.get("chart_type", "bar"),
                title=chart_spec.get("title", "Chart"),
                x_axis=AxisSpec(label="X", key="x"),
                y_axis=AxisSpec(label="Y", key="y"),
                series=[],
                data=[],
                render_hint="client_render",
            ),
        )


def format_response(
    resolved: ResolvedQuery,
    result: ExecutionResult,
    original_query: str,
    normalized_query: str,
    latency_ms: int,
) -> SearchResponse:
    """Convenience function to format a response."""
    formatter = ResponseFormatter()
    return formatter.format(resolved, result, original_query, normalized_query, latency_ms)

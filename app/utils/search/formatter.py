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
                # Handle both nested (API) and flat (transformed) formats
                "team_id": s.get("team", {}).get("id") or s.get("team_id"),
                "team_name": s.get("team", {}).get("name") or s.get("team_name"),
                "team_logo": s.get("team", {}).get("logo") or s.get("team_logo"),
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
                league_name=data.get("league_name"),
                league_id=data.get("league_id"),
                standing=standing,  # Include full standings data for stats display
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
            # Extract stats for easier access
            s1 = entities[0].get("stats", {}) if len(entities) > 0 else {}
            s2 = entities[1].get("stats", {}) if len(entities) > 1 else {}

            # Calculate additional metrics
            t1_gd = (s1.get("goals_for") or 0) - (s1.get("goals_against") or 0)
            t2_gd = (s2.get("goals_for") or 0) - (s2.get("goals_against") or 0)
            t1_played = s1.get("played") or 0
            t2_played = s2.get("played") or 0
            t1_won = s1.get("won") or 0
            t2_won = s2.get("won") or 0
            t1_drawn = s1.get("drawn") or 0
            t2_drawn = s2.get("drawn") or 0
            t1_lost = s1.get("lost") or 0
            t2_lost = s2.get("lost") or 0
            t1_win_pct = round(100 * t1_won / t1_played) if t1_played > 0 else 0
            t2_win_pct = round(100 * t2_won / t2_played) if t2_played > 0 else 0
            t1_gpg = round(s1.get("goals_for", 0) / t1_played, 2) if t1_played > 0 else 0
            t2_gpg = round(s2.get("goals_for", 0) / t2_played, 2) if t2_played > 0 else 0

            metrics = [
                ComparisonMetric(
                    metric_id="position",
                    label="League Position",
                    values=[s1.get("position"), s2.get("position")],
                    winner_index=0 if (s1.get("position") or 99) < (s2.get("position") or 99) else 1,
                ),
                ComparisonMetric(
                    metric_id="points",
                    label="Points",
                    values=[s1.get("points"), s2.get("points")],
                    winner_index=0 if (s1.get("points") or 0) > (s2.get("points") or 0) else 1,
                ),
                ComparisonMetric(
                    metric_id="played",
                    label="Played",
                    values=[t1_played, t2_played],
                ),
                ComparisonMetric(
                    metric_id="won",
                    label="Won",
                    values=[t1_won, t2_won],
                    winner_index=0 if t1_won > t2_won else (1 if t2_won > t1_won else None),
                ),
                ComparisonMetric(
                    metric_id="drawn",
                    label="Drawn",
                    values=[t1_drawn, t2_drawn],
                ),
                ComparisonMetric(
                    metric_id="lost",
                    label="Lost",
                    values=[t1_lost, t2_lost],
                    winner_index=0 if t1_lost < t2_lost else (1 if t2_lost < t1_lost else None),
                ),
                ComparisonMetric(
                    metric_id="win_pct",
                    label="Win %",
                    values=[f"{t1_win_pct}%", f"{t2_win_pct}%"],
                    winner_index=0 if t1_win_pct > t2_win_pct else (1 if t2_win_pct > t1_win_pct else None),
                ),
                ComparisonMetric(
                    metric_id="goals_for",
                    label="Goals Scored",
                    values=[s1.get("goals_for"), s2.get("goals_for")],
                    winner_index=0 if (s1.get("goals_for") or 0) > (s2.get("goals_for") or 0) else 1,
                ),
                ComparisonMetric(
                    metric_id="goals_against",
                    label="Goals Conceded",
                    values=[s1.get("goals_against"), s2.get("goals_against")],
                    winner_index=0 if (s1.get("goals_against") or 99) < (s2.get("goals_against") or 99) else 1,
                ),
                ComparisonMetric(
                    metric_id="goal_diff",
                    label="Goal Difference",
                    values=[t1_gd, t2_gd],
                    winner_index=0 if t1_gd > t2_gd else (1 if t2_gd > t1_gd else None),
                ),
                ComparisonMetric(
                    metric_id="goals_per_game",
                    label="Goals/Game",
                    values=[t1_gpg, t2_gpg],
                    winner_index=0 if t1_gpg > t2_gpg else (1 if t2_gpg > t1_gpg else None),
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
            p1_mins = get_player_stat(entities[0], "minutes") or 0
            p2_mins = get_player_stat(entities[1], "minutes") or 0

            # Calculate per-90 stats
            p1_g90 = round(p1_goals / (p1_mins / 90), 2) if p1_mins > 0 else 0
            p2_g90 = round(p2_goals / (p2_mins / 90), 2) if p2_mins > 0 else 0
            p1_a90 = round(p1_assists / (p1_mins / 90), 2) if p1_mins > 0 else 0
            p2_a90 = round(p2_assists / (p2_mins / 90), 2) if p2_mins > 0 else 0
            p1_ga = p1_goals + p1_assists
            p2_ga = p2_goals + p2_assists

            # Additional calculated stats
            p1_ga90 = round(p1_ga / (p1_mins / 90), 2) if p1_mins > 0 else 0
            p2_ga90 = round(p2_ga / (p2_mins / 90), 2) if p2_mins > 0 else 0
            p1_mins_per_goal = round(p1_mins / p1_goals) if p1_goals > 0 else 0
            p2_mins_per_goal = round(p2_mins / p2_goals) if p2_goals > 0 else 0
            p1_mins_per_ga = round(p1_mins / p1_ga) if p1_ga > 0 else 0
            p2_mins_per_ga = round(p2_mins / p2_ga) if p2_ga > 0 else 0
            p1_mins_per_app = round(p1_mins / p1_apps) if p1_apps > 0 else 0
            p2_mins_per_app = round(p2_mins / p2_apps) if p2_apps > 0 else 0

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
                    metric_id="goal_contributions",
                    label="G+A",
                    values=[p1_ga, p2_ga],
                    winner_index=0 if p1_ga > p2_ga else (1 if p2_ga > p1_ga else None),
                ),
                ComparisonMetric(
                    metric_id="appearances",
                    label="Appearances",
                    values=[p1_apps, p2_apps],
                ),
                ComparisonMetric(
                    metric_id="minutes",
                    label="Minutes",
                    values=[p1_mins, p2_mins],
                    winner_index=0 if p1_mins > p2_mins else (1 if p2_mins > p1_mins else None),
                ),
                ComparisonMetric(
                    metric_id="mins_per_app",
                    label="Mins/Game",
                    values=[p1_mins_per_app, p2_mins_per_app],
                    winner_index=0 if p1_mins_per_app > p2_mins_per_app else (1 if p2_mins_per_app > p1_mins_per_app else None),
                ),
                ComparisonMetric(
                    metric_id="goals_per_90",
                    label="Goals/90",
                    values=[p1_g90, p2_g90],
                    winner_index=0 if p1_g90 > p2_g90 else (1 if p2_g90 > p1_g90 else None),
                ),
                ComparisonMetric(
                    metric_id="assists_per_90",
                    label="Assists/90",
                    values=[p1_a90, p2_a90],
                    winner_index=0 if p1_a90 > p2_a90 else (1 if p2_a90 > p1_a90 else None),
                ),
                ComparisonMetric(
                    metric_id="ga_per_90",
                    label="G+A/90",
                    values=[p1_ga90, p2_ga90],
                    winner_index=0 if p1_ga90 > p2_ga90 else (1 if p2_ga90 > p1_ga90 else None),
                ),
                ComparisonMetric(
                    metric_id="mins_per_goal",
                    label="Mins/Goal",
                    values=[p1_mins_per_goal or '-', p2_mins_per_goal or '-'],
                    winner_index=0 if (p1_mins_per_goal and p2_mins_per_goal and p1_mins_per_goal < p2_mins_per_goal) else (1 if (p1_mins_per_goal and p2_mins_per_goal and p2_mins_per_goal < p1_mins_per_goal) else None),
                ),
                ComparisonMetric(
                    metric_id="mins_per_ga",
                    label="Mins/G+A",
                    values=[p1_mins_per_ga or '-', p2_mins_per_ga or '-'],
                    winner_index=0 if (p1_mins_per_ga and p2_mins_per_ga and p1_mins_per_ga < p2_mins_per_ga) else (1 if (p1_mins_per_ga and p2_mins_per_ga and p2_mins_per_ga < p1_mins_per_ga) else None),
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

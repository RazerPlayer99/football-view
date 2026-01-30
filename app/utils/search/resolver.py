"""Query resolution and disambiguation for search."""

from typing import List, Optional, Tuple

from .models.intent import IntentType, IntentResult
from .models.entities import (
    ExtractionResult,
    TeamEntity,
    PlayerEntity,
    CompetitionEntity,
    PronounEntity,
)
from .entities import get_alias_database
from .models.responses import (
    DisambiguationPayload,
    DisambiguationOption,
    SessionUpdate,
)
from .models.session import SearchSession
from config.settings import settings


# Confidence thresholds for auto-resolution
TEAM_AUTO_THRESHOLD = 0.85
TEAM_DISAMBIGUATE_THRESHOLD = 0.65
PLAYER_AUTO_THRESHOLD = 0.88
PLAYER_DISAMBIGUATE_THRESHOLD = 0.70
COMPETITION_AUTO_THRESHOLD = 0.90


class ResolvedQuery:
    """Result of query resolution - ready for execution."""

    def __init__(
        self,
        intent: IntentResult,
        teams: List[TeamEntity],
        players: List[PlayerEntity],
        competitions: List[CompetitionEntity],
        assumptions: List[str],
        session_update: SessionUpdate,
    ):
        self.intent = intent
        self.teams = teams
        self.players = players
        self.competitions = competitions
        self.assumptions = assumptions
        self.session_update = session_update

    @property
    def primary_team(self) -> Optional[TeamEntity]:
        """Get the primary (highest confidence) team."""
        return self.teams[0] if self.teams else None

    @property
    def secondary_team(self) -> Optional[TeamEntity]:
        """Get the secondary team (for vs queries)."""
        return self.teams[1] if len(self.teams) > 1 else None

    @property
    def primary_player(self) -> Optional[PlayerEntity]:
        """Get the primary player."""
        return self.players[0] if self.players else None

    @property
    def primary_competition(self) -> Optional[CompetitionEntity]:
        """Get the primary competition."""
        return self.competitions[0] if self.competitions else None


class Resolver:
    """
    Resolves extracted entities and handles disambiguation.

    Responsibilities:
    - Check entity confidence thresholds
    - Resolve pronouns using session context
    - Generate disambiguation when multiple matches
    - Apply sensible defaults with explicit assumptions
    """

    def __init__(self, default_league_id: int = None, default_season: int = None):
        self.default_league_id = default_league_id or settings.premier_league_id
        self.default_season = default_season or settings.current_season

    def resolve(
        self,
        intent: IntentResult,
        entities: ExtractionResult,
        session: Optional[SearchSession] = None,
    ) -> Tuple[Optional[ResolvedQuery], Optional[DisambiguationPayload]]:
        """
        Resolve entities for query execution.

        Args:
            intent: Classified intent
            entities: Extracted entities
            session: Optional session for context

        Returns:
            Tuple of (ResolvedQuery, None) if resolved successfully,
            or (None, DisambiguationPayload) if disambiguation needed.
        """
        assumptions = []
        session_update = SessionUpdate()

        # Resolve pronouns first
        resolved_entities = self._resolve_pronouns(entities, session, assumptions)

        # Check for disambiguation needs
        disambiguation = self._check_disambiguation(intent, resolved_entities)
        if disambiguation:
            return None, disambiguation

        # Filter to high-confidence entities
        is_comparison = intent.intent_type == IntentType.COMPARISON
        teams = self._filter_teams(resolved_entities.teams, assumptions, for_comparison=is_comparison)
        players = self._filter_players(resolved_entities.players, assumptions, for_comparison=is_comparison)
        competitions = self._filter_competitions(resolved_entities.competitions, assumptions)

        # Apply defaults based on intent
        teams, players, competitions, assumptions = self._apply_defaults(
            intent, teams, players, competitions, assumptions, session
        )

        # Build session update
        if teams:
            session_update.last_team_id = teams[0].team_id
        if players:
            session_update.last_player_id = players[0].player_id
        if competitions:
            session_update.last_league_id = competitions[0].league_id
        session_update.last_intent = intent.intent_type.value

        resolved = ResolvedQuery(
            intent=intent,
            teams=teams,
            players=players,
            competitions=competitions,
            assumptions=assumptions,
            session_update=session_update,
        )

        return resolved, None

    def _resolve_pronouns(
        self,
        entities: ExtractionResult,
        session: Optional[SearchSession],
        assumptions: List[str],
    ) -> ExtractionResult:
        """Resolve pronouns using session context."""
        if not session or not entities.pronouns:
            return entities

        resolved_teams = list(entities.teams)
        resolved_players = list(entities.players)

        for pronoun in entities.pronouns:
            if pronoun.resolved_to == "player" and pronoun.resolved_id:
                # Add resolved player
                resolved_players.append(PlayerEntity(
                    player_id=pronoun.resolved_id,
                    name=f"Player #{pronoun.resolved_id}",  # Will be enriched by executor
                    confidence=0.90,
                    matched_text=pronoun.pronoun,
                    match_method="session_pronoun",
                ))
                assumptions.append(f"Resolved '{pronoun.pronoun}' from previous query")

            elif pronoun.resolved_to == "team" and pronoun.resolved_id:
                resolved_teams.append(TeamEntity(
                    team_id=pronoun.resolved_id,
                    name=f"Team #{pronoun.resolved_id}",
                    confidence=0.90,
                    matched_text=pronoun.pronoun,
                    match_method="session_pronoun",
                ))
                assumptions.append(f"Resolved '{pronoun.pronoun}' from previous query")

        return ExtractionResult(
            teams=resolved_teams,
            players=resolved_players,
            competitions=entities.competitions,
            metrics=entities.metrics,
            pronouns=[],  # Pronouns are now resolved
        )

    def _check_disambiguation(
        self,
        intent: IntentResult,
        entities: ExtractionResult,
    ) -> Optional[DisambiguationPayload]:
        """Check if disambiguation is needed."""
        # COMPARISON intent expects multiple entities - don't disambiguate
        if intent.intent_type == IntentType.COMPARISON:
            return None

        # For league-focused intents (standings, top scorers, etc.),
        # if we have a high-confidence competition match, skip player/team disambiguation
        # This prevents "la liga standings" from triggering player disambiguation
        league_focused_intents = {
            IntentType.STANDINGS,
            IntentType.TOP_SCORERS,
            IntentType.TOP_ASSISTS,
            IntentType.SCHEDULE,
        }
        if intent.intent_type in league_focused_intents:
            # Check if we have a competition match
            if entities.competitions:
                top_comp = max(entities.competitions, key=lambda c: c.confidence)
                if top_comp.confidence >= COMPETITION_AUTO_THRESHOLD:
                    # High confidence competition - proceed without disambiguation
                    return None

        # Check for ambiguous teams
        if entities.has_ambiguous_teams:
            teams = sorted(entities.teams, key=lambda t: t.confidence, reverse=True)
            top_teams = [t for t in teams if t.confidence >= TEAM_DISAMBIGUATE_THRESHOLD][:4]

            if len(top_teams) > 1:
                return DisambiguationPayload(
                    question="Which team did you mean?",
                    options=[
                        DisambiguationOption(
                            label=t.name,
                            value=t.name,
                            entity_type="team",
                            entity_id=t.team_id,
                        )
                        for t in top_teams
                    ],
                )

        # Check for ambiguous players
        if entities.has_ambiguous_players:
            players = sorted(entities.players, key=lambda p: p.confidence, reverse=True)
            top_players = [p for p in players if p.confidence >= PLAYER_DISAMBIGUATE_THRESHOLD][:4]

            if len(top_players) > 1:
                return DisambiguationPayload(
                    question="Which player did you mean?",
                    options=[
                        DisambiguationOption(
                            label=p.name,
                            value=p.name,
                            entity_type="player",
                            entity_id=p.player_id,
                        )
                        for p in top_players
                    ],
                )

        # Check for unresolved pronouns
        if entities.has_unresolved_pronouns:
            unresolved = [p for p in entities.pronouns if p.resolved_id is None]
            if unresolved:
                pronoun = unresolved[0].pronoun
                return DisambiguationPayload(
                    question=f"I'm not sure who '{pronoun}' refers to. Could you be more specific?",
                    options=[
                        DisambiguationOption(
                            label="Search for a team",
                            value="team",
                            entity_type="prompt",
                            entity_id=0,
                        ),
                        DisambiguationOption(
                            label="Search for a player",
                            value="player",
                            entity_type="prompt",
                            entity_id=0,
                        ),
                    ],
                )

        return None

    def _filter_teams(
        self,
        teams: List[TeamEntity],
        assumptions: List[str],
        for_comparison: bool = False,
    ) -> List[TeamEntity]:
        """Filter teams to high-confidence matches."""
        # Sort by confidence
        sorted_teams = sorted(teams, key=lambda t: t.confidence, reverse=True)

        # For comparisons, keep multiple teams above disambiguate threshold
        if for_comparison:
            result = [t for t in sorted_teams if t.confidence >= TEAM_DISAMBIGUATE_THRESHOLD][:2]
            if result:
                return result

        # Take top team if above threshold, or top 2 for vs queries
        result = []
        for team in sorted_teams:
            if team.confidence >= TEAM_AUTO_THRESHOLD or len(result) == 0:
                result.append(team)
            if len(result) >= 2:
                break

        return result

    def _filter_players(
        self,
        players: List[PlayerEntity],
        assumptions: List[str],
        for_comparison: bool = False,
    ) -> List[PlayerEntity]:
        """Filter players to high-confidence matches."""
        sorted_players = sorted(players, key=lambda p: p.confidence, reverse=True)

        # For comparisons, keep multiple players above disambiguate threshold
        if for_comparison:
            result = [p for p in sorted_players if p.confidence >= PLAYER_DISAMBIGUATE_THRESHOLD][:2]
            if result:
                return result

        result = []
        for player in sorted_players:
            if player.confidence >= PLAYER_AUTO_THRESHOLD or len(result) == 0:
                result.append(player)
            if len(result) >= 2:
                break

        return result

    def _filter_competitions(
        self,
        competitions: List[CompetitionEntity],
        assumptions: List[str],
    ) -> List[CompetitionEntity]:
        """Filter competitions to high-confidence matches."""
        sorted_comps = sorted(competitions, key=lambda c: c.confidence, reverse=True)

        if sorted_comps and sorted_comps[0].confidence >= COMPETITION_AUTO_THRESHOLD:
            return [sorted_comps[0]]
        return []

    def _apply_defaults(
        self,
        intent: IntentResult,
        teams: List[TeamEntity],
        players: List[PlayerEntity],
        competitions: List[CompetitionEntity],
        assumptions: List[str],
        session: Optional[SearchSession],
    ) -> Tuple[List[TeamEntity], List[PlayerEntity], List[CompetitionEntity], List[str]]:
        """Apply sensible defaults based on intent type."""
        alias_db = get_alias_database()

        # Default competition for standings, top scorers, etc.
        if intent.intent_type in (
            IntentType.STANDINGS,
            IntentType.TOP_SCORERS,
            IntentType.TOP_ASSISTS,
            IntentType.SCHEDULE,
        ):
            if not competitions:
                # Use session league or default
                league_id = session.last_league_id if session else None
                if not league_id and self.default_league_id is not None:
                    league_id = self.default_league_id
                    league_name = alias_db.competitions.get(str(league_id), {}).get(
                        "canonical",
                        f"League {league_id}",
                    )
                    assumptions.append(f"Showing {league_name} (default)")

                if league_id:
                    league_name = alias_db.competitions.get(str(league_id), {}).get(
                        "canonical",
                        f"League {league_id}",
                    )
                    competitions = [CompetitionEntity(
                        league_id=league_id,
                        name=league_name,
                        confidence=0.80,
                        matched_text="default",
                        match_method="default",
                    )]

        # Default season
        if intent.time_modifier and intent.time_modifier.season_year:
            pass  # Season specified in query
        elif session and session.last_season:
            assumptions.append(f"Using season {session.last_season} from context")
        else:
            assumptions.append(f"Showing current season {settings.current_season}-{str(settings.current_season + 1)[-2:]}")

        return teams, players, competitions, assumptions


def resolve_query(
    intent: IntentResult,
    entities: ExtractionResult,
    session: Optional[SearchSession] = None,
    default_league_id: int = None,
    default_season: int = None,
) -> Tuple[Optional[ResolvedQuery], Optional[DisambiguationPayload]]:
    """
    Convenience function to resolve a query.

    Returns:
        Tuple of (ResolvedQuery, None) or (None, DisambiguationPayload)
    """
    resolver = Resolver(
        default_league_id,
        default_season or settings.current_season
    )
    return resolver.resolve(intent, entities, session)

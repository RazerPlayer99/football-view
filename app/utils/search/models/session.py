"""Session management models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Optional


@dataclass
class SearchSession:
    """
    Session state for contextual search queries.

    Tracks recent entities for pronoun resolution:
    - "him" / "his" / "he" → last_player_id
    - "them" / "their" / "they" → last_team_id
    - "that game" / "the match" → last_fixture_id
    - "the league" / "same league" → last_league_id
    """
    session_id: str
    last_team_id: Optional[int] = None
    last_player_id: Optional[int] = None
    last_fixture_id: Optional[int] = None
    last_league_id: Optional[int] = None
    last_season: Optional[int] = None
    last_intent: Optional[str] = None
    last_query_time: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    SESSION_TTL_SECONDS: ClassVar[int] = 1800  # 30 minutes

    def is_expired(self) -> bool:
        """Check if session has expired due to inactivity."""
        if self.last_query_time is None:
            return False
        elapsed = (datetime.utcnow() - self.last_query_time).total_seconds()
        return elapsed > self.SESSION_TTL_SECONDS

    def touch(self) -> None:
        """Update last query time."""
        self.last_query_time = datetime.utcnow()

    def update_from_entities(
        self,
        team_id: Optional[int] = None,
        player_id: Optional[int] = None,
        fixture_id: Optional[int] = None,
        league_id: Optional[int] = None,
        season: Optional[int] = None,
        intent: Optional[str] = None,
    ) -> None:
        """Update session with new entity context."""
        if team_id is not None:
            self.last_team_id = team_id
        if player_id is not None:
            self.last_player_id = player_id
        if fixture_id is not None:
            self.last_fixture_id = fixture_id
        if league_id is not None:
            self.last_league_id = league_id
        if season is not None:
            self.last_season = season
        if intent is not None:
            self.last_intent = intent
        self.touch()

    def resolve_pronoun(self, pronoun: str) -> tuple[Optional[str], Optional[int]]:
        """
        Resolve a pronoun to entity type and ID.

        Returns:
            Tuple of (entity_type, entity_id) or (None, None) if unresolvable.
        """
        pronoun_lower = pronoun.lower()

        # Player pronouns
        if pronoun_lower in ("he", "him", "his"):
            if self.last_player_id:
                return ("player", self.last_player_id)

        # Team pronouns
        if pronoun_lower in ("they", "them", "their"):
            if self.last_team_id:
                return ("team", self.last_team_id)

        # Match references
        if pronoun_lower in ("that game", "the match", "that match", "the game"):
            if self.last_fixture_id:
                return ("fixture", self.last_fixture_id)

        # League references
        if pronoun_lower in ("the league", "same league", "that league"):
            if self.last_league_id:
                return ("competition", self.last_league_id)

        return (None, None)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "last_team_id": self.last_team_id,
            "last_player_id": self.last_player_id,
            "last_fixture_id": self.last_fixture_id,
            "last_league_id": self.last_league_id,
            "last_season": self.last_season,
            "last_intent": self.last_intent,
        }

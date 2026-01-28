"""Entity models for search."""

from dataclasses import dataclass
from typing import Optional, Literal, List


@dataclass
class EntityMatch:
    """Base result from entity matching."""
    entity_id: str  # String to handle different ID types
    name: str
    confidence: float  # 0.0 - 1.0
    match_method: str  # "alias_exact", "alias_fuzzy", "fuzzy_canonical"
    matched_text: str  # Original query text that matched


@dataclass
class TeamEntity:
    """Extracted team entity."""
    entity_type: Literal["team"] = "team"
    team_id: int = 0
    name: str = ""
    confidence: float = 0.0
    matched_text: str = ""
    match_method: str = ""
    league_id: Optional[int] = None

    @classmethod
    def from_match(cls, match: EntityMatch, league_id: Optional[int] = None) -> "TeamEntity":
        return cls(
            team_id=int(match.entity_id),
            name=match.name,
            confidence=match.confidence,
            matched_text=match.matched_text,
            match_method=match.match_method,
            league_id=league_id,
        )


@dataclass
class PlayerEntity:
    """Extracted player entity."""
    entity_type: Literal["player"] = "player"
    player_id: int = 0
    name: str = ""
    confidence: float = 0.0
    matched_text: str = ""
    match_method: str = ""
    team_id: Optional[int] = None

    @classmethod
    def from_match(cls, match: EntityMatch, team_id: Optional[int] = None) -> "PlayerEntity":
        return cls(
            player_id=int(match.entity_id),
            name=match.name,
            confidence=match.confidence,
            matched_text=match.matched_text,
            match_method=match.match_method,
            team_id=team_id,
        )


@dataclass
class CompetitionEntity:
    """Extracted competition/league entity."""
    entity_type: Literal["competition"] = "competition"
    league_id: int = 0
    name: str = ""
    confidence: float = 0.0
    matched_text: str = ""
    match_method: str = ""

    @classmethod
    def from_match(cls, match: EntityMatch) -> "CompetitionEntity":
        return cls(
            league_id=int(match.entity_id),
            name=match.name,
            confidence=match.confidence,
            matched_text=match.matched_text,
            match_method=match.match_method,
        )


@dataclass
class MetricEntity:
    """Extracted metric entity (goals, assists, xg, etc.)."""
    entity_type: Literal["metric"] = "metric"
    metric_id: str = ""  # "goals", "assists", "xg", "possession", etc.
    per_90: bool = False
    matched_text: str = ""


@dataclass
class PronounEntity:
    """Placeholder for pronouns that need session resolution."""
    entity_type: Literal["pronoun"] = "pronoun"
    pronoun: str = ""  # "he", "him", "they", "them", etc.
    resolved_to: Optional[str] = None  # "player", "team"
    resolved_id: Optional[int] = None


# Type alias for any entity
Entity = TeamEntity | PlayerEntity | CompetitionEntity | MetricEntity | PronounEntity


@dataclass
class ExtractionResult:
    """Result of entity extraction from a query."""
    teams: List[TeamEntity]
    players: List[PlayerEntity]
    competitions: List[CompetitionEntity]
    metrics: List[MetricEntity]
    pronouns: List[PronounEntity]

    @property
    def all_entities(self) -> List[Entity]:
        return self.teams + self.players + self.competitions + self.metrics + self.pronouns

    @property
    def has_ambiguous_teams(self) -> bool:
        """Check if there are multiple teams with similar confidence."""
        if len(self.teams) < 2:
            return False
        # Check if top 2 teams are within 0.15 confidence of each other
        sorted_teams = sorted(self.teams, key=lambda t: t.confidence, reverse=True)
        return sorted_teams[0].confidence - sorted_teams[1].confidence < 0.15

    @property
    def has_ambiguous_players(self) -> bool:
        """Check if there are multiple players with similar confidence."""
        if len(self.players) < 2:
            return False
        sorted_players = sorted(self.players, key=lambda p: p.confidence, reverse=True)
        return sorted_players[0].confidence - sorted_players[1].confidence < 0.15

    @property
    def needs_disambiguation(self) -> bool:
        return self.has_ambiguous_teams or self.has_ambiguous_players

    @property
    def has_unresolved_pronouns(self) -> bool:
        return any(p.resolved_id is None for p in self.pronouns)

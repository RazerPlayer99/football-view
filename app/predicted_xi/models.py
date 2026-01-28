"""
Data models for Predicted XI engine.

Defines the structures for predictions, features, weights, and accuracy tracking.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


# Current model version - increment when algorithm changes significantly
MODEL_VERSION = "1.1.0"


class CompetitionType(Enum):
    """Types of competitions for context-aware predictions."""
    LEAGUE = "league"
    CUP = "cup"
    CHAMPIONS_LEAGUE = "champions_league"
    EUROPA_LEAGUE = "europa_league"
    FRIENDLY = "friendly"
    OTHER = "other"


@dataclass
class MatchContext:
    """
    Context for a specific match that influences predictions.

    Used to adjust feature weights and player selection based on
    match circumstances.
    """
    competition: str = "league"  # league, cup, champions_league, etc.
    home_away: str = "home"  # home, away, neutral
    days_rest: Optional[int] = None  # Days since last match
    opponent_strength: Optional[str] = None  # top_6, mid_table, relegation
    is_derby: bool = False
    is_knockout: bool = False  # Cup knockout vs group stage
    fixture_congestion: bool = False  # Multiple matches in short period

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "competition": self.competition,
            "home_away": self.home_away,
            "days_rest": self.days_rest,
            "opponent_strength": self.opponent_strength,
            "is_derby": self.is_derby,
            "is_knockout": self.is_knockout,
            "fixture_congestion": self.fixture_congestion,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MatchContext":
        """Create from dictionary."""
        return cls(
            competition=data.get("competition", "league"),
            home_away=data.get("home_away", data.get("homeAway", "home")),
            days_rest=data.get("days_rest", data.get("daysRest")),
            opponent_strength=data.get("opponent_strength"),
            is_derby=data.get("is_derby", False),
            is_knockout=data.get("is_knockout", False),
            fixture_congestion=data.get("fixture_congestion", False),
        )

    @property
    def is_high_priority(self) -> bool:
        """Check if this is a high-priority match (less rotation expected)."""
        if self.is_knockout:
            return True
        if self.competition in ("champions_league", "europa_league"):
            return True
        if self.is_derby:
            return True
        if self.opponent_strength == "top_6":
            return True
        return False

    @property
    def rotation_likelihood(self) -> float:
        """
        Get rotation likelihood based on context (0-1).

        Higher = more rotation expected.
        """
        likelihood = 0.3  # Base rotation likelihood

        # Low rest days = more rotation
        if self.days_rest is not None:
            if self.days_rest <= 3:
                likelihood += 0.3
            elif self.days_rest <= 5:
                likelihood += 0.1

        # Fixture congestion
        if self.fixture_congestion:
            likelihood += 0.2

        # Cup matches (non-knockout) often see rotation
        if self.competition == "cup" and not self.is_knockout:
            likelihood += 0.2

        # High priority matches = less rotation
        if self.is_high_priority:
            likelihood -= 0.2

        return max(0.0, min(1.0, likelihood))


class WeightScope(Enum):
    """Scope levels for weight configurations."""
    GLOBAL = "global"
    TEAM = "team"
    COACH = "coach"


# Default feature weights
DEFAULT_WEIGHTS: Dict[str, float] = {
    "recent_starts": 0.35,      # Starts in last N matches (highest signal)
    "minutes_trend": 0.20,      # Minutes played trend
    "position_fit": 0.15,       # How often played this position
    "formation_consistency": 0.10,  # Team's formation patterns
    "rotation_signal": 0.10,    # Fixture congestion/rest needs
    "availability": 0.10,       # Not suspended, recently played
}


@dataclass
class PlayerFeatures:
    """
    Extracted features for a single player used in prediction scoring.

    Each feature is normalized to 0-1 range for consistent weighting.
    """
    player_id: int
    player_name: str
    primary_position: str  # G, D, M, F
    squad_number: Optional[int] = None

    # Feature values (all normalized 0-1)
    recent_starts: float = 0.0       # % of last N matches started
    minutes_trend: float = 0.0       # Minutes trend (1.0 = increasing, 0.0 = decreasing)
    position_fit: float = 0.0        # % of appearances at target position
    formation_consistency: float = 0.0  # How well player fits team's preferred formation
    rotation_signal: float = 0.0     # 1.0 = well rested, 0.0 = needs rest
    availability: float = 1.0        # 1.0 = available, lower = suspension risk etc.

    # Raw data for explanations
    starts_last_n: int = 0
    total_matches_last_n: int = 0
    minutes_last_n: int = 0
    positions_played: Dict[str, int] = field(default_factory=dict)  # position -> count
    days_since_last_match: Optional[int] = None
    consecutive_starts: int = 0
    yellow_cards_season: int = 0

    def get_feature_dict(self) -> Dict[str, float]:
        """Get all features as a dictionary."""
        return {
            "recent_starts": self.recent_starts,
            "minutes_trend": self.minutes_trend,
            "position_fit": self.position_fit,
            "formation_consistency": self.formation_consistency,
            "rotation_signal": self.rotation_signal,
            "availability": self.availability,
        }


@dataclass
class FeatureContribution:
    """Tracks how much each feature contributed to a player's score."""
    feature_name: str
    weight: float
    feature_value: float
    contribution: float  # weight * feature_value

    @property
    def percentage(self) -> float:
        """Contribution as percentage of total possible."""
        return self.contribution * 100


@dataclass
class PredictedPlayer:
    """
    A player predicted for the lineup with confidence and explanations.
    """
    player_id: int
    player_name: str
    position: str  # Predicted position to play
    grid_position: Optional[str] = None  # Formation grid e.g., "2:3"
    squad_number: Optional[int] = None

    # Prediction confidence
    confidence: float = 0.0  # 0-1 scale
    total_score: float = 0.0  # Raw weighted score

    # Explainability
    explanations: List[str] = field(default_factory=list)  # Top 2-3 reasons
    feature_contributions: Dict[str, float] = field(default_factory=dict)  # feature -> contribution

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "position": self.position,
            "grid_position": self.grid_position,
            "squad_number": self.squad_number,
            "confidence": round(self.confidence, 3),
            "explanations": self.explanations,
            "feature_contributions": {
                k: round(v, 4) for k, v in self.feature_contributions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PredictedPlayer":
        """Create from dictionary."""
        return cls(
            player_id=data["player_id"],
            player_name=data["player_name"],
            position=data["position"],
            grid_position=data.get("grid_position"),
            squad_number=data.get("squad_number"),
            confidence=data.get("confidence", 0.0),
            explanations=data.get("explanations", []),
            feature_contributions=data.get("feature_contributions", {}),
        )


@dataclass
class FormationPrediction:
    """Predicted formation with confidence."""
    formation: str  # e.g., "4-3-3"
    confidence: float
    usage_count: int  # Times used in historical data
    total_matches: int


@dataclass
class PredictedLineup:
    """
    Complete predicted lineup for a match.

    This is the main output of the prediction engine.
    """
    match_id: int
    team_id: int
    team_name: str
    squad_type: str = "predicted"  # Always "predicted" for this

    # Season tracking
    season: Optional[int] = None  # e.g., 2024 for 2024-25 season
    competition: Optional[str] = None  # e.g., "league", "cup", "champions_league"

    # Versioning
    model_version: str = MODEL_VERSION
    weights_version: str = "1"

    # Timestamps
    generated_at: str = ""  # ISO timestamp
    superseded_at: Optional[str] = None  # Set when confirmed lineup arrives

    # Formation
    formation: str = ""
    formation_confidence: float = 0.0
    alternative_formations: List[FormationPrediction] = field(default_factory=list)

    # Lineup
    starting_xi: List[PredictedPlayer] = field(default_factory=list)
    bench: List[PredictedPlayer] = field(default_factory=list)

    # Overall metrics
    overall_confidence: float = 0.0
    key_uncertainties: List[str] = field(default_factory=list)

    # Match context
    context: Optional["MatchContext"] = None

    # Training data info
    based_on_matches: int = 0

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "match_id": self.match_id,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "squad_type": self.squad_type,
            "season": self.season,
            "competition": self.competition,
            "model_version": self.model_version,
            "weights_version": self.weights_version,
            "generated_at": self.generated_at,
            "superseded_at": self.superseded_at,
            "formation": self.formation,
            "formation_confidence": round(self.formation_confidence, 3),
            "starting_xi": [p.to_dict() for p in self.starting_xi],
            "bench": [p.to_dict() for p in self.bench],
            "overall_confidence": round(self.overall_confidence, 3),
            "key_uncertainties": self.key_uncertainties,
            "based_on_matches": self.based_on_matches,
        }
        if self.context:
            result["context"] = self.context.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PredictedLineup":
        """Create from dictionary."""
        context = None
        if "context" in data and data["context"]:
            context = MatchContext.from_dict(data["context"])

        return cls(
            match_id=data["match_id"],
            team_id=data["team_id"],
            team_name=data.get("team_name", ""),
            squad_type=data.get("squad_type", "predicted"),
            season=data.get("season"),
            competition=data.get("competition"),
            model_version=data.get("model_version", MODEL_VERSION),
            weights_version=data.get("weights_version", "1"),
            generated_at=data.get("generated_at", ""),
            superseded_at=data.get("superseded_at"),
            formation=data.get("formation", ""),
            formation_confidence=data.get("formation_confidence", 0.0),
            starting_xi=[PredictedPlayer.from_dict(p) for p in data.get("starting_xi", [])],
            bench=[PredictedPlayer.from_dict(p) for p in data.get("bench", [])],
            overall_confidence=data.get("overall_confidence", 0.0),
            key_uncertainties=data.get("key_uncertainties", []),
            based_on_matches=data.get("based_on_matches", 0),
            context=context,
        )


@dataclass
class WeightConfig:
    """
    Weight configuration at a specific scope level.
    """
    scope: WeightScope
    scope_id: Optional[int]  # team_id or coach_id, None for global
    weights: Dict[str, float]
    version: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "weights": self.weights,
            "version": self.version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeightConfig":
        """Create from dictionary."""
        return cls(
            scope=WeightScope(data["scope"]),
            scope_id=data.get("scope_id"),
            weights=data["weights"],
            version=data["version"],
            updated_at=data["updated_at"],
        )

    @classmethod
    def default_global(cls) -> "WeightConfig":
        """Create default global weights."""
        return cls(
            scope=WeightScope.GLOBAL,
            scope_id=None,
            weights=DEFAULT_WEIGHTS.copy(),
            version="1",
            updated_at=datetime.utcnow().isoformat() + "Z",
        )


@dataclass
class AccuracyRecord:
    """
    Record of prediction accuracy after comparing to actual lineup.
    """
    id: Optional[int] = None
    prediction_id: Optional[int] = None
    match_id: int = 0
    team_id: int = 0

    # Accuracy metrics
    correct_starters: int = 0  # Out of 11
    correct_positions: int = 0  # Correct player AND position
    formation_correct: bool = False

    # Detailed breakdown
    error_breakdown: Dict[str, Any] = field(default_factory=dict)
    # Structure: {
    #   "missed_players": [{"id": 123, "name": "...", "predicted_instead": {...}}],
    #   "wrong_positions": [{"player_id": 123, "predicted": "D", "actual": "M"}],
    #   "feature_analysis": {"recent_starts": {"correct_avg": 0.8, "wrong_avg": 0.3}}
    # }

    evaluated_at: str = ""

    def __post_init__(self):
        if not self.evaluated_at:
            self.evaluated_at = datetime.utcnow().isoformat() + "Z"

    @property
    def starter_accuracy(self) -> float:
        """Accuracy as percentage."""
        return self.correct_starters / 11.0

    @property
    def position_accuracy(self) -> float:
        """Position accuracy as percentage."""
        return self.correct_positions / 11.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "prediction_id": self.prediction_id,
            "match_id": self.match_id,
            "team_id": self.team_id,
            "correct_starters": self.correct_starters,
            "correct_positions": self.correct_positions,
            "formation_correct": self.formation_correct,
            "starter_accuracy": round(self.starter_accuracy, 3),
            "position_accuracy": round(self.position_accuracy, 3),
            "error_breakdown": self.error_breakdown,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class ConfirmedLineup:
    """
    Actual confirmed lineup from the match (for comparison).
    """
    match_id: int
    team_id: int
    formation: Optional[str]
    starting_xi: List[int]  # Player IDs
    recorded_at: str = ""

    def __post_init__(self):
        if not self.recorded_at:
            self.recorded_at = datetime.utcnow().isoformat() + "Z"


@dataclass
class SeasonAccuracySummary:
    """
    Season-level accuracy summary for Predicted XI.

    Used to track and display prediction accuracy over time.
    """
    season: int
    competition: Optional[str] = None  # None = all competitions

    # Core metrics
    matches_evaluated: int = 0
    total_correct_xi: int = 0  # Sum of correct starters across all matches
    perfect_xi_count: int = 0  # Matches with 11/11 correct

    # Computed metrics
    @property
    def avg_correct_xi(self) -> float:
        """Average correct starters per match."""
        if self.matches_evaluated == 0:
            return 0.0
        return self.total_correct_xi / self.matches_evaluated

    @property
    def avg_accuracy(self) -> float:
        """Average accuracy as percentage (0-1)."""
        return self.avg_correct_xi / 11.0

    @property
    def perfect_xi_rate(self) -> float:
        """Percentage of matches with 11/11 correct."""
        if self.matches_evaluated == 0:
            return 0.0
        return self.perfect_xi_count / self.matches_evaluated

    # Optional breakdown
    team_breakdown: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    # Structure: {team_id: {"team_name": str, "matches": int, "avg_correct": float}}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "season": self.season,
            "competition": self.competition,
            "matches_evaluated": self.matches_evaluated,
            "total_correct_xi": self.total_correct_xi,
            "perfect_xi_count": self.perfect_xi_count,
            "avg_correct_xi": round(self.avg_correct_xi, 2),
            "avg_accuracy": round(self.avg_accuracy, 3),
            "perfect_xi_rate": round(self.perfect_xi_rate, 3),
            "team_breakdown": self.team_breakdown,
        }

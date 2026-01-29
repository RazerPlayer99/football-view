"""
Data models for Live Match Center.

These dataclasses represent the canonical shape of match data,
independent of whether it comes from REST or Firebase.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

from app.utils.helpers import safe_lower


class EventType(Enum):
    """Types of match events."""
    GOAL = "goal"
    CARD = "card"
    SUBSTITUTION = "substitution"
    VAR = "var"
    PENALTY_MISSED = "penalty_missed"


@dataclass
class MatchEvent:
    """A single match event (goal, card, substitution, etc.)."""
    minute: int
    extra_time: Optional[int]
    event_type: str
    detail: str  # "Normal Goal", "Yellow Card", "Red Card", "Substitution 1", etc.
    team_id: int
    team_name: str
    is_home: bool
    player_id: int
    player_name: str
    assist_id: Optional[int] = None
    assist_name: Optional[str] = None
    comments: Optional[str] = None

    @property
    def time_display(self) -> str:
        """Format time as '45+2' or '67'."""
        if self.extra_time:
            return f"{self.minute}+{self.extra_time}"
        return str(self.minute)

    @property
    def is_goal(self) -> bool:
        return safe_lower(self.event_type) == "goal"

    @property
    def is_card(self) -> bool:
        return safe_lower(self.event_type) == "card"

    @property
    def is_yellow(self) -> bool:
        return self.is_card and "yellow" in safe_lower(self.detail)

    @property
    def is_red(self) -> bool:
        return self.is_card and "red" in safe_lower(self.detail)

    @property
    def is_substitution(self) -> bool:
        return safe_lower(self.event_type) == "subst"


@dataclass
class LineupPlayer:
    """A player in a lineup."""
    id: int
    name: str
    number: Optional[int]
    position: str  # "G", "D", "M", "F"
    grid: Optional[str] = None  # Formation grid position e.g., "1:1"

    @property
    def position_name(self) -> str:
        """Full position name."""
        return {
            "G": "Goalkeeper",
            "D": "Defender",
            "M": "Midfielder",
            "F": "Forward",
        }.get(self.position, self.position)


@dataclass
class TeamLineup:
    """A team's lineup including formation and players."""
    team_id: int
    team_name: str
    team_logo: str
    formation: Optional[str]
    coach_name: Optional[str]
    coach_photo: Optional[str]
    starting_xi: List[LineupPlayer]
    substitutes: List[LineupPlayer]


@dataclass
class MatchStat:
    """A single statistic comparison between teams."""
    stat_type: str  # "Ball Possession", "Total Shots", etc.
    home_value: Any  # Could be int, str ("58%"), or None
    away_value: Any

    @property
    def stat_label(self) -> str:
        """Human-readable label."""
        # Clean up API naming
        labels = {
            "Ball Possession": "Possession",
            "Total Shots": "Total Shots",
            "Shots on Goal": "Shots on Target",
            "Shots off Goal": "Shots off Target",
            "Blocked Shots": "Blocked Shots",
            "Corner Kicks": "Corners",
            "Fouls": "Fouls",
            "Yellow Cards": "Yellow Cards",
            "Red Cards": "Red Cards",
            "Passes total": "Total Passes",
            "Passes accurate": "Accurate Passes",
            "expected_goals": "xG",
        }
        return labels.get(self.stat_type, self.stat_type)

    @property
    def home_numeric(self) -> float:
        """Parse home value as number."""
        return self._parse_numeric(self.home_value)

    @property
    def away_numeric(self) -> float:
        """Parse away value as number."""
        return self._parse_numeric(self.away_value)

    def _parse_numeric(self, val: Any) -> float:
        """Parse a stat value to numeric."""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            # Handle percentage strings like "58%"
            clean = val.replace("%", "").strip()
            try:
                return float(clean)
            except ValueError:
                return 0.0
        return 0.0

    @property
    def home_percentage(self) -> float:
        """Home value as percentage of total (for bar charts)."""
        total = self.home_numeric + self.away_numeric
        if total == 0:
            return 50.0
        return (self.home_numeric / total) * 100

    @property
    def away_percentage(self) -> float:
        """Away value as percentage of total."""
        return 100 - self.home_percentage


@dataclass
class TeamInfo:
    """Basic team information."""
    id: int
    name: str
    logo: str


@dataclass
class LiveMatchData:
    """
    Complete snapshot of a match at a point in time.

    This is the canonical data structure returned by LiveMatchProvider.
    Contains all data needed to render the Match Center UI.
    """
    # Identifiers
    id: int

    # Status
    status: str  # "Match Finished", "First Half", etc.
    status_short: str  # "FT", "1H", "HT", "NS", etc.
    elapsed: Optional[int]  # Current minute if live
    extra_time: Optional[int]
    is_live: bool
    is_finished: bool

    # Match info
    date: str  # ISO datetime string
    venue: Optional[str]
    referee: Optional[str]

    # Teams
    home_team: TeamInfo
    away_team: TeamInfo

    # Score
    home_goals: int
    away_goals: int
    halftime_home: Optional[int]
    halftime_away: Optional[int]

    # League context
    league_id: Optional[int]
    league_name: Optional[str]
    league_logo: Optional[str]
    match_round: Optional[str]

    # Nested data
    events: List[MatchEvent] = field(default_factory=list)
    home_lineup: Optional[TeamLineup] = None
    away_lineup: Optional[TeamLineup] = None
    statistics: List[MatchStat] = field(default_factory=list)

    # Metadata
    last_updated: str = ""  # ISO timestamp
    data_source: str = "rest"  # "rest" or "firebase"

    @property
    def score_display(self) -> str:
        """Format score as 'X - Y'."""
        h = self.home_goals if self.home_goals is not None else "-"
        a = self.away_goals if self.away_goals is not None else "-"
        return f"{h} - {a}"

    @property
    def halftime_display(self) -> Optional[str]:
        """Format halftime score as '(X - Y)'."""
        if self.halftime_home is not None and self.halftime_away is not None:
            return f"({self.halftime_home} - {self.halftime_away})"
        return None

    @property
    def elapsed_display(self) -> str:
        """Format elapsed time for display."""
        if not self.is_live:
            return ""
        if self.elapsed is None:
            return ""
        if self.extra_time:
            return f"{self.elapsed}+{self.extra_time}'"
        return f"{self.elapsed}'"

    @property
    def has_lineups(self) -> bool:
        """Check if lineup data is available."""
        return self.home_lineup is not None and self.away_lineup is not None

    @property
    def has_statistics(self) -> bool:
        """Check if statistics data is available."""
        return len(self.statistics) > 0

    @property
    def has_events(self) -> bool:
        """Check if events data is available."""
        return len(self.events) > 0


@dataclass
class MatchDelta:
    """
    Represents a change to match state (for future Firebase streaming).

    When using Firebase subscriptions, deltas represent incremental updates
    rather than full snapshots. This reduces data transfer for live matches.
    """
    match_id: int
    timestamp: str
    delta_type: str  # "score", "event", "status", "statistic"

    # Score update
    new_home_goals: Optional[int] = None
    new_away_goals: Optional[int] = None

    # Status update
    new_status: Optional[str] = None
    new_elapsed: Optional[int] = None

    # New event
    new_event: Optional[MatchEvent] = None

    # Statistic update
    stat_type: Optional[str] = None
    new_home_value: Optional[Any] = None
    new_away_value: Optional[Any] = None

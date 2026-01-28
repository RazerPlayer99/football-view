"""Intent classification models."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, List


class IntentType(str, Enum):
    """Supported search intent types."""
    STANDINGS = "STANDINGS"
    TOP_SCORERS = "TOP_SCORERS"
    TOP_ASSISTS = "TOP_ASSISTS"
    MATCH_LOOKUP = "MATCH_LOOKUP"
    TEAM_LOOKUP = "TEAM_LOOKUP"
    PLAYER_LOOKUP = "PLAYER_LOOKUP"
    SCHEDULE = "SCHEDULE"
    COMPARISON = "COMPARISON"
    CHART_REQUEST = "CHART_REQUEST"
    UNKNOWN = "UNKNOWN"


@dataclass
class TimeModifier:
    """
    Time-based modifier that can apply to any intent.

    Examples:
    - "Arsenal last 5 games" → modifier_type="past", count=5
    - "games tomorrow" → modifier_type="relative", relative="tomorrow"
    - "Arsenal vs Chelsea last season" → modifier_type="season", season_year=2023
    """
    modifier_type: str  # "past", "future", "range", "season", "relative"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    count: Optional[int] = None  # For "last 5", "next 3"
    relative: Optional[str] = None  # "today", "tomorrow", "this_weekend", etc.
    season_year: Optional[int] = None  # For "last season", "2023-24"
    matched_text: str = ""  # Original text that triggered this modifier


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent_type: IntentType
    confidence: float  # 0.0 - 1.0
    time_modifier: Optional[TimeModifier] = None
    used_llm: bool = False
    matched_pattern: Optional[str] = None  # Which pattern matched (for debugging)
    raw_captures: List[str] = field(default_factory=list)  # Captured groups from regex

    @property
    def needs_disambiguation(self) -> bool:
        """Check if confidence is too low for auto-resolution."""
        return self.confidence < 0.70

    @property
    def needs_llm_fallback(self) -> bool:
        """Check if LLM fallback should be triggered."""
        return self.confidence < 0.70 or self.intent_type == IntentType.UNKNOWN

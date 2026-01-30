"""Response models for search - single envelope contract."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union


@dataclass
class ColumnDef:
    """Column definition for table responses."""
    key: str
    label: str
    sortable: bool = True
    align: str = "left"  # "left", "center", "right"


@dataclass
class TablePayload:
    """Payload for table response type."""
    title: str
    columns: List[ColumnDef]
    rows: List[Dict[str, Any]]
    total_count: int = 0
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None  # "asc" | "desc"

    def __post_init__(self):
        if self.total_count == 0:
            self.total_count = len(self.rows)


@dataclass
class MatchCardPayload:
    """Payload for match card response type."""
    fixture: Dict[str, Any]  # MatchCardView as dict
    h2h_recent: List[Dict[str, Any]] = field(default_factory=list)
    home_form: List[str] = field(default_factory=list)  # ["W", "W", "D", "L", "W"]
    away_form: List[str] = field(default_factory=list)


@dataclass
class TeamCardPayload:
    """Payload for team card response type."""
    team: Dict[str, Any]  # TeamDashboardView as dict
    standings_position: int = 0
    league_name: Optional[str] = None
    league_id: Optional[int] = None
    recent_results: List[Dict[str, Any]] = field(default_factory=list)
    upcoming: List[Dict[str, Any]] = field(default_factory=list)
    top_scorer: Optional[Dict[str, Any]] = None


@dataclass
class PlayerCardPayload:
    """Payload for player card response type."""
    player: Dict[str, Any]  # PlayerView as dict
    season_stats: Dict[str, Any] = field(default_factory=dict)
    recent_matches: List[Dict[str, Any]] = field(default_factory=list)
    per_90_stats: Dict[str, float] = field(default_factory=dict)


@dataclass
class ComparisonMetric:
    """Single metric in a comparison."""
    metric_id: str
    label: str
    values: List[Any]  # One per entity
    winner_index: Optional[int] = None  # Index of "better" value, or None if tie


@dataclass
class ComparisonPayload:
    """Payload for comparison response type."""
    entity_type: str  # "team" | "player"
    entities: List[Union[TeamCardPayload, PlayerCardPayload]]
    comparison_metrics: List[ComparisonMetric] = field(default_factory=list)


@dataclass
class AxisSpec:
    """Axis specification for charts."""
    label: str
    key: str
    type: str = "category"  # "category", "value", "time"


@dataclass
class SeriesSpec:
    """Series specification for charts."""
    name: str
    key: str
    color: Optional[str] = None


@dataclass
class ChartSpecPayload:
    """Payload for chart spec response type (deferred render)."""
    chart_type: str  # "bar", "line", "scatter", "pie"
    title: str
    x_axis: AxisSpec
    y_axis: AxisSpec
    series: List[SeriesSpec] = field(default_factory=list)
    data: List[Dict[str, Any]] = field(default_factory=list)
    render_hint: str = "client_render"


@dataclass
class DisambiguationOption:
    """Single option in a disambiguation response."""
    label: str  # Display text
    value: str  # Query to re-submit
    entity_type: str  # "team", "player", etc.
    entity_id: int


@dataclass
class DisambiguationPayload:
    """Payload for disambiguation response type."""
    question: str
    options: List[DisambiguationOption]


@dataclass
class ErrorPayload:
    """Payload for error response type."""
    error_type: str  # "no_results", "unsupported_query", "rate_limited", "internal"
    message: str
    suggestions: List[str] = field(default_factory=list)
    suggested_query: Optional[str] = None
    retry_after_seconds: Optional[int] = None  # For rate limiting


@dataclass
class SessionUpdate:
    """Session context to persist after a query."""
    last_team_id: Optional[int] = None
    last_player_id: Optional[int] = None
    last_fixture_id: Optional[int] = None
    last_league_id: Optional[int] = None
    last_season: Optional[int] = None
    last_intent: Optional[str] = None


@dataclass
class QueryMeta:
    """Debugging/analytics metadata for a query."""
    original_query: str
    normalized_query: str
    intent: str
    intent_confidence: float
    used_llm: bool
    latency_ms: int
    entities: List[str]  # ["team:42", "player:306"]


# Type alias for all payload types
Payload = Union[
    TablePayload,
    MatchCardPayload,
    TeamCardPayload,
    PlayerCardPayload,
    ComparisonPayload,
    ChartSpecPayload,
    DisambiguationPayload,
    ErrorPayload,
]


@dataclass
class SearchResponse:
    """
    Unified response envelope for all search queries.

    This is the SINGLE contract that all search responses use.
    """
    # Core fields
    type: str  # "table", "match_card", "team_card", "player_card", "comparison",
               # "chart_spec", "disambiguation", "error"
    data: Payload

    # Provenance
    as_of: str = ""  # ISO timestamp of data freshness
    sources_used: List[str] = field(default_factory=list)  # ["api_football:standings"]

    # Transparency
    assumptions: List[str] = field(default_factory=list)  # ["Assumed current season"]
    missing_capabilities: List[str] = field(default_factory=list)  # ["xG not available"]

    # Session management
    session_update: Optional[SessionUpdate] = None

    # Debugging (omitted in production if SEARCH_LOGGING=0)
    _meta: Optional[QueryMeta] = None

    def __post_init__(self):
        if not self.as_of:
            self.as_of = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "type": self.type,
            "data": self._payload_to_dict(self.data),
            "as_of": self.as_of,
            "sources_used": self.sources_used,
            "assumptions": self.assumptions,
            "missing_capabilities": self.missing_capabilities,
        }

        if self.session_update:
            result["session_update"] = {
                k: v for k, v in self.session_update.__dict__.items() if v is not None
            }

        if self._meta:
            result["_meta"] = self._meta.__dict__

        return result

    def _payload_to_dict(self, payload: Payload) -> Dict[str, Any]:
        """Convert payload dataclass to dict."""
        if hasattr(payload, "__dict__"):
            return {k: self._serialize_value(v) for k, v in payload.__dict__.items()}
        return payload

    def _serialize_value(self, value: Any) -> Any:
        """Recursively serialize values."""
        if hasattr(value, "__dict__"):
            return {k: self._serialize_value(v) for k, v in value.__dict__.items()}
        if isinstance(value, list):
            return [self._serialize_value(v) for v in value]
        return value


# Factory functions for common responses
def error_response(
    error_type: str,
    message: str,
    suggestions: List[str] = None,
    suggested_query: str = None,
    retry_after: int = None,
) -> SearchResponse:
    """Create an error response."""
    return SearchResponse(
        type="error",
        data=ErrorPayload(
            error_type=error_type,
            message=message,
            suggestions=suggestions or [],
            suggested_query=suggested_query,
            retry_after_seconds=retry_after,
        ),
    )


def disambiguation_response(
    question: str,
    options: List[DisambiguationOption],
) -> SearchResponse:
    """Create a disambiguation response."""
    return SearchResponse(
        type="disambiguation",
        data=DisambiguationPayload(
            question=question,
            options=options,
        ),
    )

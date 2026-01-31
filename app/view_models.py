"""
View Models for UI Rendering
Strict mapping layer that converts API responses into presentation-ready models.
Validates that only expected fields are used.
"""
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from app.utils.helpers import safe_lower, safe_str


# =============================================================================
# PAYLOAD CONTRACTS (UI-Stable View Models)
# =============================================================================
# These contracts define the EXACT shape the UI expects. The UI should ONLY
# consume these payloads, never raw API responses. This shields the UI from
# API structure changes.


@dataclass
class TeamPayload:
    """Stable team payload for UI consumption."""
    id: int
    name: str
    logo: str
    score: Optional[int] = None  # Only present for match context


@dataclass
class CompetitionPayload:
    """Stable competition payload."""
    id: int
    name: str
    round: Optional[str] = None
    logo: Optional[str] = None


@dataclass
class MatchCardPayload:
    """
    Stable payload for match cards on landing/dashboard.
    UI relies on these exact field names.
    """
    id: int
    status: str  # "upcoming" | "live" | "finished"
    kickoff_utc: str  # ISO string
    kickoff_local: str  # Formatted for display
    competition: CompetitionPayload
    home: TeamPayload
    away: TeamPayload

    @classmethod
    def from_raw_match(cls, raw: Dict[str, Any]) -> "MatchCardPayload":
        """Map raw API match data to stable payload."""
        # Normalize status
        raw_status = (raw.get("status") or "").lower()
        if raw_status in ("not started", "ns", "tbd", "pst"):
            status = "upcoming"
        elif raw_status in ("1h", "2h", "ht", "et", "p", "live", "bt"):
            status = "live"
        elif raw_status in ("ft", "aet", "pen", "match finished", "finished"):
            status = "finished"
        else:
            status = "upcoming"

        # Format kickoff time
        kickoff_utc = raw.get("date", "")
        kickoff_local = ""
        if kickoff_utc:
            try:
                dt = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
                kickoff_local = dt.strftime("%a %b %d • %H:%M")
            except:
                kickoff_local = kickoff_utc[:16] if len(kickoff_utc) > 16 else kickoff_utc

        # Extract team data
        home_team = raw.get("home_team", {}) or {}
        away_team = raw.get("away_team", {}) or {}

        return cls(
            id=raw.get("id", 0),
            status=status,
            kickoff_utc=kickoff_utc,
            kickoff_local=kickoff_local,
            competition=CompetitionPayload(
                id=raw.get("league_id", 0),
                name=raw.get("competition", ""),
                round=raw.get("round"),
                logo=raw.get("league_logo"),
            ),
            home=TeamPayload(
                id=home_team.get("id", 0),
                name=home_team.get("name", "Home"),
                logo=home_team.get("logo", ""),
                score=raw.get("home_goals"),
            ),
            away=TeamPayload(
                id=away_team.get("id", 0),
                name=away_team.get("name", "Away"),
                logo=away_team.get("logo", ""),
                score=raw.get("away_goals"),
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "id": self.id,
            "status": self.status,
            "kickoff_utc": self.kickoff_utc,
            "kickoff_local": self.kickoff_local,
            "competition": {
                "id": self.competition.id,
                "name": self.competition.name,
                "round": self.competition.round,
                "logo": self.competition.logo,
            },
            "home": {
                "id": self.home.id,
                "name": self.home.name,
                "logo": self.home.logo,
                "score": self.home.score,
            },
            "away": {
                "id": self.away.id,
                "name": self.away.name,
                "logo": self.away.logo,
                "score": self.away.score,
            },
        }


@dataclass
class H2HPayload:
    """Head-to-head summary payload."""
    total_matches: int
    home_wins: int  # Wins by the "home" team in current match context
    away_wins: int  # Wins by the "away" team in current match context
    draws: int
    recent_matches: List[Dict[str, Any]]  # Last 5 H2H fixtures

    @classmethod
    def aggregate(
        cls,
        raw_matches: List[Dict[str, Any]],
        team1_id: int,
        team2_id: int,
    ) -> "H2HPayload":
        """
        Aggregate H2H from raw match list.
        Counts wins by team_id regardless of home/away position in each match.
        Ignores matches with null scores.
        """
        team1_wins = 0
        team2_wins = 0
        draws = 0
        recent = []

        for m in raw_matches:
            home = m.get("home_team", {}) or {}
            away = m.get("away_team", {}) or {}
            h_goals = m.get("home_goals")
            a_goals = m.get("away_goals")

            # Skip null scores
            if h_goals is None or a_goals is None:
                continue

            home_id = home.get("id", 0)
            away_id = away.get("id", 0)

            # Determine winner by team_id, not by home/away position
            if h_goals > a_goals:
                winner_id = home_id
            elif a_goals > h_goals:
                winner_id = away_id
            else:
                winner_id = None  # Draw

            if winner_id == team1_id:
                team1_wins += 1
            elif winner_id == team2_id:
                team2_wins += 1
            elif winner_id is None:
                draws += 1

            recent.append({
                "date": m.get("date"),
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "home_goals": h_goals,
                "away_goals": a_goals,
            })

        return cls(
            total_matches=len(recent),
            home_wins=team1_wins,
            away_wins=team2_wins,
            draws=draws,
            recent_matches=recent[:5],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_matches": self.total_matches,
            "home_wins": self.home_wins,
            "away_wins": self.away_wins,
            "draws": self.draws,
            "recent_matches": self.recent_matches,
        }


@dataclass
class SeasonStatsPayload:
    """Basic season stats from standings."""
    rank: Optional[int]
    points: Optional[int]
    played: Optional[int]
    won: Optional[int]
    drawn: Optional[int]
    lost: Optional[int]
    goals_for: Optional[int]
    goals_against: Optional[int]
    goal_diff: Optional[int]

    @classmethod
    def from_standings_row(cls, row: Dict[str, Any]) -> "SeasonStatsPayload":
        return cls(
            rank=row.get("rank") or row.get("position"),
            points=row.get("points"),
            played=row.get("played"),
            won=row.get("won"),
            drawn=row.get("drawn"),
            lost=row.get("lost"),
            goals_for=row.get("goals_for"),
            goals_against=row.get("goals_against"),
            goal_diff=row.get("goal_diff") or row.get("goal_difference"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "points": self.points,
            "played": self.played,
            "won": self.won,
            "drawn": self.drawn,
            "lost": self.lost,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "goal_diff": self.goal_diff,
        }


@dataclass
class LineupPlayerPayload:
    """Player in a lineup."""
    name: str
    position: str
    player_id: Optional[int] = None
    number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "player_id": self.player_id,
            "number": self.number,
        }


@dataclass
class LineupPayload:
    """Team lineup payload."""
    formation: Optional[str]
    players: List[LineupPlayerPayload]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formation": self.formation,
            "players": [p.to_dict() for p in self.players],
        }


@dataclass
class PreMatchTeamPayload:
    """Team payload for pre-match view with form and stats."""
    id: int
    name: str
    logo: str
    form: List[str]  # ["W", "D", "L", "W", "W"]
    season_stats: Optional[SeasonStatsPayload]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "logo": self.logo,
            "form": self.form,
            "season_stats": self.season_stats.to_dict() if self.season_stats else None,
        }


@dataclass
class PreMatchPayload:
    """
    Complete pre-match payload for upcoming match overlay.
    This is THE contract the UI relies on.
    """
    match: Dict[str, Any]  # Basic match info
    home_team: PreMatchTeamPayload
    away_team: PreMatchTeamPayload
    h2h: H2HPayload
    lineups: Dict[str, Optional[LineupPayload]]  # {"home": ..., "away": ...}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match": self.match,
            "home_team": self.home_team.to_dict(),
            "away_team": self.away_team.to_dict(),
            "h2h": self.h2h.to_dict(),
            "lineups": {
                "home": self.lineups.get("home").to_dict() if self.lineups.get("home") else None,
                "away": self.lineups.get("away").to_dict() if self.lineups.get("away") else None,
            },
        }


# =============================================================================
# MAPPER FUNCTIONS
# =============================================================================

def map_fixtures_to_match_cards(raw_matches: List[Dict[str, Any]]) -> List[MatchCardPayload]:
    """Convert raw API matches to stable MatchCardPayload list."""
    return [MatchCardPayload.from_raw_match(m) for m in raw_matches]


def get_team_form(team_id: int, past_matches: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    """
    Extract team form (W/D/L) from past matches.
    """
    form = []
    for m in past_matches[:limit]:
        home = m.get("home_team", {}) or {}
        away = m.get("away_team", {}) or {}
        h_goals = m.get("home_goals")
        a_goals = m.get("away_goals")

        if h_goals is None or a_goals is None:
            continue

        is_home = home.get("id") == team_id
        team_goals = h_goals if is_home else a_goals
        opp_goals = a_goals if is_home else h_goals

        if team_goals > opp_goals:
            form.append("W")
        elif team_goals < opp_goals:
            form.append("L")
        else:
            form.append("D")

    return form


def find_team_in_standings(
    standings: List[Dict[str, Any]],
    team_id: int,
) -> Optional[SeasonStatsPayload]:
    """Find team in standings and return stats payload."""
    for row in standings:
        row_team_id = row.get("team_id") or row.get("team", {}).get("id")
        if row_team_id == team_id:
            return SeasonStatsPayload.from_standings_row(row)
    return None

# Timezone for display (CST = UTC-6)
CST = timezone(timedelta(hours=-6))


def convert_utc_to_cst(dt: datetime) -> datetime:
    """Convert UTC datetime to CST for display."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST)

logger = logging.getLogger("view_models")

# ===== ALLOWED FIELD DEFINITIONS =====

TEAM_VIEW_FIELDS = {"id", "name", "logo", "venue", "city", "country", "founded"}
STANDING_ROW_FIELDS = {"position", "team", "played", "won", "drawn", "lost",
                        "goals_for", "goals_against", "goal_difference", "points", "form"}
MATCH_CARD_FIELDS = {"id", "date", "venue", "referee", "status", "home_team", "away_team",
                      "home_goals", "away_goals", "result", "halftime", "fulltime", "competition",
                      "league_id", "league_logo", "round"}
PLAYER_VIEW_FIELDS = {"id", "name", "photo", "nationality", "age", "team", "position",
                       "goals", "assists", "appearances", "minutes", "minutes_played",
                       "yellow_cards", "red_cards"}


def _validate_fields(data: Dict[str, Any], allowed: set, context: str) -> List[str]:
    """
    Validate that data only contains allowed fields.
    Returns list of unknown fields found.
    """
    if not isinstance(data, dict):
        return []

    unknown = []
    for key in data.keys():
        if key not in allowed:
            # Nested objects are OK (like team.id, team.name)
            if not isinstance(data[key], dict):
                unknown.append(key)

    if unknown:
        logger.warning(f"[{context}] Unknown fields in API response: {unknown}")

    return unknown


@dataclass
class TeamView:
    """View model for team display."""
    id: int
    name: str
    logo: str = ""
    venue: str = ""
    city: str = ""
    country: str = ""
    founded: Optional[int] = None

    # Validation tracking
    unknown_fields: List[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "TeamView":
        """Create TeamView from API response with validation."""
        unknown = _validate_fields(data, TEAM_VIEW_FIELDS, "TeamView")

        return cls(
            id=data.get("id", 0),
            name=data.get("name", "Unknown"),
            logo=data.get("logo", ""),
            venue=data.get("venue", ""),
            city=data.get("city", ""),
            country=data.get("country", ""),
            founded=data.get("founded"),
            unknown_fields=unknown,
        )

    def to_html_header(self) -> str:
        """Render team as HTML header card."""
        return f"""
        <div class="team-header">
            <img src="{self.logo}" alt="{self.name}" class="team-logo">
            <div class="team-info">
                <h1>{self.name}</h1>
                <p class="team-details">{self.venue} | {self.city}</p>
                {f'<p class="team-founded">Founded: {self.founded}</p>' if self.founded else ''}
            </div>
        </div>
        """

    def to_html_card(self) -> str:
        """Render team as compact card."""
        return f"""
        <div class="team-card">
            <img src="{self.logo}" alt="{self.name}">
            <span class="team-name">{self.name}</span>
        </div>
        """


@dataclass
class StandingRowView:
    """View model for standings table row."""
    position: int
    team_id: int
    team_name: str
    team_logo: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    form: str = ""

    unknown_fields: List[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "StandingRowView":
        """Create StandingRowView from API response with validation."""
        unknown = _validate_fields(data, STANDING_ROW_FIELDS, "StandingRowView")

        team = data.get("team", {})

        return cls(
            position=data.get("position", 0),
            team_id=team.get("id", 0),
            team_name=team.get("name", "Unknown"),
            team_logo=team.get("logo", ""),
            played=data.get("played", 0),
            won=data.get("won", 0),
            drawn=data.get("drawn", 0),
            lost=data.get("lost", 0),
            goals_for=data.get("goals_for", 0),
            goals_against=data.get("goals_against", 0),
            goal_difference=data.get("goal_difference", 0),
            points=data.get("points", 0),
            form=data.get("form", ""),
            unknown_fields=unknown,
        )

    def to_html_row(self) -> str:
        """Render as HTML table row."""
        # Position styling
        pos_class = ""
        if self.position <= 4:
            pos_class = "pos-ucl"  # Champions League
        elif self.position == 5:
            pos_class = "pos-uel"  # Europa League
        elif self.position >= 18:
            pos_class = "pos-rel"  # Relegation

        # Form badges
        form_html = ""
        for char in self.form[-5:]:  # Last 5 results
            if char == "W":
                form_html += '<span class="form-badge form-win">W</span>'
            elif char == "D":
                form_html += '<span class="form-badge form-draw">D</span>'
            elif char == "L":
                form_html += '<span class="form-badge form-loss">L</span>'

        return f"""
        <tr class="{pos_class}">
            <td class="pos-cell">{self.position}</td>
            <td class="team-cell">
                <img src="{self.team_logo}" alt="" class="team-mini-logo">
                <a href="/ui/teams/{self.team_id}">{self.team_name}</a>
            </td>
            <td>{self.played}</td>
            <td>{self.won}</td>
            <td>{self.drawn}</td>
            <td>{self.lost}</td>
            <td>{self.goals_for}</td>
            <td>{self.goals_against}</td>
            <td class="gd-cell">{'+' if self.goal_difference > 0 else ''}{self.goal_difference}</td>
            <td class="pts-cell"><strong>{self.points}</strong></td>
            <td class="form-cell">{form_html}</td>
        </tr>
        """


@dataclass
class MatchCardView:
    """View model for match display."""
    id: int
    date: str
    date_formatted: str
    time_formatted: str
    venue: str
    referee: str
    status: str
    home_team_id: int
    home_team_name: str
    home_team_logo: str
    away_team_id: int
    away_team_name: str
    away_team_logo: str
    home_goals: int
    away_goals: int
    result: str  # H, D, A
    competition: str = "Unknown League"
    league_id: Optional[int] = None
    league_logo: str = ""
    match_round: str = ""

    unknown_fields: List[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "MatchCardView":
        """Create MatchCardView from API response with validation."""
        unknown = _validate_fields(data, MATCH_CARD_FIELDS, "MatchCardView")

        home_team = data.get("home_team", {})
        away_team = data.get("away_team", {})

        # Parse date and convert to CST
        date_str = data.get("date", "")
        date_formatted = ""
        time_formatted = ""
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                dt_cst = convert_utc_to_cst(dt)
                date_formatted = dt_cst.strftime("%a, %b %d")
                time_formatted = dt_cst.strftime("%H:%M CST")
            except:
                date_formatted = date_str[:10] if len(date_str) > 10 else date_str
                time_formatted = ""

        return cls(
            id=data.get("id", 0),
            date=date_str,
            date_formatted=date_formatted,
            time_formatted=time_formatted,
            venue=data.get("venue", ""),
            referee=data.get("referee", ""),
            status=data.get("status", ""),
            home_team_id=home_team.get("id", 0),
            home_team_name=home_team.get("name", "Unknown"),
            home_team_logo=home_team.get("logo", ""),
            away_team_id=away_team.get("id", 0),
            away_team_name=away_team.get("name", "Unknown"),
            away_team_logo=away_team.get("logo", ""),
            home_goals=data.get("home_goals", 0),
            away_goals=data.get("away_goals", 0),
            result=data.get("result", ""),
            competition=data.get("competition", "Unknown League"),
            league_id=data.get("league_id"),
            league_logo=data.get("league_logo", ""),
            match_round=data.get("round", ""),
            unknown_fields=unknown,
        )

    @property
    def score_display(self) -> str:
        """Get formatted score display."""
        if self.status == "Match Finished" or "FT" in self.status:
            return f"{self.home_goals} - {self.away_goals}"
        elif self.status in ("Not Started", "NS"):
            return "vs"
        else:
            return f"{self.home_goals} - {self.away_goals}"

    @property
    def is_finished(self) -> bool:
        return self.status == "Match Finished" or "FT" in self.status

    def to_html_card(self) -> str:
        """Render as HTML match card."""
        # Determine winner styling
        home_class = "team-winner" if self.result == "H" else ""
        away_class = "team-winner" if self.result == "A" else ""

        status_class = "status-finished" if self.is_finished else "status-upcoming"

        return f"""
        <a href="/ui/matches/{self.id}" class="match-card-link">
            <div class="match-card">
                <div class="match-header">
                    <span class="match-date">{self.date_formatted}</span>
                    <span class="match-time">{self.time_formatted}</span>
                </div>
                <div class="match-teams">
                    <div class="match-team {home_class}">
                        <img src="{self.home_team_logo}" alt="">
                        <span class="team-name">{self.home_team_name}</span>
                    </div>
                    <div class="match-score">
                        <span class="score-display">{self.score_display}</span>
                        <span class="match-status {status_class}">{self.status}</span>
                    </div>
                    <div class="match-team {away_class}">
                        <img src="{self.away_team_logo}" alt="">
                        <span class="team-name">{self.away_team_name}</span>
                    </div>
                </div>
                <div class="match-footer">
                    <span class="match-venue">{self.venue}</span>
                    {f'<span class="match-referee">Ref: {self.referee}</span>' if self.referee else ''}
                </div>
            </div>
        </a>
        """

    def to_html_row(self) -> str:
        """Render as HTML table row."""
        home_class = "team-winner" if self.result == "H" else ""
        away_class = "team-winner" if self.result == "A" else ""

        return f"""
        <tr>
            <td class="date-cell">{self.date_formatted}</td>
            <td class="team-cell {home_class}">
                <img src="{self.home_team_logo}" alt="" class="team-mini-logo">
                <a href="/ui/teams/{self.home_team_id}">{self.home_team_name}</a>
            </td>
            <td class="score-cell">{self.score_display}</td>
            <td class="team-cell {away_class}">
                <img src="{self.away_team_logo}" alt="" class="team-mini-logo">
                <a href="/ui/teams/{self.away_team_id}">{self.away_team_name}</a>
            </td>
            <td class="venue-cell">{self.venue}</td>
        </tr>
        """


@dataclass
class PlayerView:
    """View model for player display in search/list."""
    id: int
    name: str
    photo: str
    nationality: str
    team_id: int
    team_name: str
    position: str
    goals: int
    assists: int
    appearances: int
    minutes: int = 0

    unknown_fields: List[str] = field(default_factory=list)

    # Minimum minutes threshold for per-90 stats to be considered valid
    PER90_MIN_MINUTES = 450  # ~5 full matches

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "PlayerView":
        """Create PlayerView from API response with validation."""
        unknown = _validate_fields(data, PLAYER_VIEW_FIELDS, "PlayerView")

        team = data.get("team", {})

        return cls(
            id=data.get("id", 0),
            name=data.get("name", "Unknown"),
            photo=data.get("photo", ""),
            nationality=data.get("nationality", ""),
            team_id=team.get("id", 0) if isinstance(team, dict) else 0,
            team_name=team.get("name", "") if isinstance(team, dict) else str(team),
            position=data.get("position", ""),
            goals=data.get("goals", 0) or 0,
            assists=data.get("assists", 0) or 0,
            appearances=data.get("appearances", 0) or 0,
            minutes=data.get("minutes_played", 0) or data.get("minutes", 0) or 0,
            unknown_fields=unknown,
        )

    @property
    def has_enough_minutes(self) -> bool:
        """Check if player has enough minutes for valid per-90 stats."""
        return self.minutes >= self.PER90_MIN_MINUTES

    @property
    def goals_per90(self) -> Optional[float]:
        """Goals per 90 minutes. Returns None if below minutes threshold."""
        if not self.has_enough_minutes or self.minutes == 0:
            return None
        return round((self.goals / self.minutes) * 90, 2)

    @property
    def assists_per90(self) -> Optional[float]:
        """Assists per 90 minutes. Returns None if below minutes threshold."""
        if not self.has_enough_minutes or self.minutes == 0:
            return None
        return round((self.assists / self.minutes) * 90, 2)

    @property
    def goal_contributions_per90(self) -> Optional[float]:
        """Goals + Assists per 90 minutes. Returns None if below minutes threshold."""
        if not self.has_enough_minutes or self.minutes == 0:
            return None
        return round(((self.goals + self.assists) / self.minutes) * 90, 2)

    @property
    def minutes_per_goal(self) -> Optional[float]:
        """Minutes per goal. Returns None if no goals."""
        if self.goals == 0:
            return None
        return round(self.minutes / self.goals, 0)

    def per90_display(self, stat: str) -> str:
        """Get displayable per-90 stat with fallback."""
        value = getattr(self, f"{stat}_per90", None)
        if value is None:
            return "—"
        return f"{value:.2f}"

    def to_html_row(self) -> str:
        """Render as HTML table row."""
        return f"""
        <tr>
            <td class="player-cell">
                <img src="{self.photo}" alt="" class="player-mini-photo">
                <a href="/ui/players/{self.id}">{self.name}</a>
            </td>
            <td>{self.position}</td>
            <td><a href="/ui/teams/{self.team_id}">{self.team_name}</a></td>
            <td class="stat-cell">{self.goals}</td>
            <td class="stat-cell">{self.assists}</td>
            <td class="stat-cell">{self.appearances}</td>
        </tr>
        """


# ===== HELPER FUNCTIONS =====

def standings_to_view_models(standings: List[Dict]) -> List[StandingRowView]:
    """Convert API standings list to view models."""
    return [StandingRowView.from_api(s) for s in standings]


def matches_to_view_models(matches: List[Dict]) -> List[MatchCardView]:
    """Convert API matches list to view models."""
    return [MatchCardView.from_api(m) for m in matches]


def players_to_view_models(players: List[Dict]) -> List[PlayerView]:
    """Convert API players list to view models."""
    return [PlayerView.from_api(p) for p in players]


def check_unknown_fields(view_models: List) -> bool:
    """Check if any view models have unknown fields. Returns True if all clean."""
    has_unknown = False
    for vm in view_models:
        if hasattr(vm, 'unknown_fields') and vm.unknown_fields:
            has_unknown = True
    return not has_unknown


# ===== MATCH CENTER VIEW MODELS =====

@dataclass
class MatchEventView:
    """View model for match events (goals, cards, substitutions)."""
    minute: int
    extra_time: Optional[int]
    event_type: str
    detail: str
    team_id: int
    team_name: str
    is_home: bool
    player_name: str
    player_id: int
    assist_name: Optional[str] = None

    @property
    def time_display(self) -> str:
        """Format time as '45+2' or '67'."""
        if self.extra_time:
            return f"{self.minute}+{self.extra_time}'"
        return f"{self.minute}'"

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

    @property
    def icon_html(self) -> str:
        """Get HTML icon for event type."""
        detail_lower = safe_lower(self.detail)
        if self.is_goal:
            if "own" in detail_lower:
                return '<span class="event-icon event-own-goal">OG</span>'
            elif "penalty" in detail_lower:
                return '<span class="event-icon event-goal">P</span>'
            return '<span class="event-icon event-goal">G</span>'
        elif self.is_yellow:
            return '<span class="event-icon event-yellow"></span>'
        elif self.is_red:
            return '<span class="event-icon event-red"></span>'
        elif self.is_substitution:
            return '<span class="event-icon event-sub">S</span>'
        return '<span class="event-icon"></span>'

    def to_timeline_html(self) -> str:
        """Render as timeline event."""
        side_class = "event-home" if self.is_home else "event-away"
        align_class = "event-align-left" if self.is_home else "event-align-right"

        # Build player display based on event type
        if self.is_goal:
            # Goals: show team abbreviation, scorer, and assist (if different player)
            team_abbr = safe_str(self.team_name)[:3].upper() if self.team_name else ""
            assist_text = ""
            if self.assist_name and self.assist_name != self.player_name:
                assist_text = f' <span class="assist">(assist: {self.assist_name})</span>'
            player_html = f'<span class="team-abbr">[{team_abbr}]</span> <a href="/ui/players/{self.player_id}">{self.player_name}</a>{assist_text}'
        elif self.is_substitution:
            # Substitutions: assist_name is the player coming IN, player_name is going OUT
            player_out = self.player_name or "Unknown"
            player_in = self.assist_name or "Unknown"
            player_html = f'<span class="sub-out">{player_out}</span> ↔ <span class="sub-in">{player_in}</span>'
        else:
            # Cards and other events: just show player name
            player_html = f'<a href="/ui/players/{self.player_id}">{self.player_name}</a>'

        return f"""
        <div class="timeline-event {side_class} {align_class}">
            <span class="event-time">{self.time_display}</span>
            {self.icon_html}
            <span class="event-player">
                {player_html}
            </span>
        </div>
        """


@dataclass
class LineupPlayerView:
    """View model for a player in lineup."""
    id: int
    name: str
    number: Optional[int]
    position: str
    grid: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Name with number."""
        if self.number:
            return f"{self.number}. {self.name}"
        return self.name

    def to_html(self) -> str:
        """Render as lineup list item."""
        pos_class = f"pos-{safe_lower(self.position)}" if self.position else ""
        return f"""
        <div class="lineup-player {pos_class}">
            <span class="player-number">{self.number or ''}</span>
            <a href="/ui/players/{self.id}" class="player-name">{self.name}</a>
            <span class="player-position">{self.position or ''}</span>
        </div>
        """


@dataclass
class TeamLineupView:
    """View model for team lineup."""
    team_id: int
    team_name: str
    team_logo: str
    formation: Optional[str]
    coach_name: Optional[str]
    starting_xi: List[LineupPlayerView]
    substitutes: List[LineupPlayerView]
    is_predicted: bool = False  # Whether this is a predicted lineup
    prediction_confidence: Optional[float] = None

    def to_html(self) -> str:
        """Render team lineup section."""
        xi_html = "\n".join(p.to_html() for p in self.starting_xi)
        subs_html = "\n".join(p.to_html() for p in self.substitutes)

        # Add prediction indicator if applicable
        prediction_badge = ""
        if self.is_predicted:
            confidence_pct = int((self.prediction_confidence or 0) * 100)
            prediction_badge = f'<span class="prediction-badge">Predicted ({confidence_pct}% confidence)</span>'

        return f"""
        <div class="team-lineup {'predicted-lineup' if self.is_predicted else ''}">
            <div class="lineup-header">
                <img src="{self.team_logo}" alt="" class="lineup-team-logo">
                <div class="lineup-team-info">
                    <h4>{self.team_name}</h4>
                    <span class="formation">{self.formation or 'N/A'}</span>
                    {prediction_badge}
                </div>
            </div>
            <div class="starting-xi">
                <h5>Starting XI</h5>
                {xi_html}
            </div>
            <div class="substitutes">
                <h5>{'Bench (Predicted)' if self.is_predicted else 'Substitutes'}</h5>
                {subs_html}
            </div>
            {f'<div class="coach">Coach: {self.coach_name}</div>' if self.coach_name else ''}
        </div>
        """


@dataclass
class MatchStatView:
    """View model for match statistic comparison."""
    stat_type: str
    home_value: Any
    away_value: Any

    @property
    def label(self) -> str:
        """Human-readable label."""
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
    def home_display(self) -> str:
        """Format home value for display."""
        if self.home_value is None:
            return "0"
        return str(self.home_value)

    @property
    def away_display(self) -> str:
        """Format away value for display."""
        if self.away_value is None:
            return "0"
        return str(self.away_value)

    def _parse_numeric(self, val: Any) -> float:
        """Parse value to numeric."""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            clean = val.replace("%", "").strip()
            try:
                return float(clean)
            except ValueError:
                return 0.0
        return 0.0

    @property
    def home_percent(self) -> float:
        """Home percentage for bar chart."""
        h = self._parse_numeric(self.home_value)
        a = self._parse_numeric(self.away_value)
        total = h + a
        if total == 0:
            return 50.0
        return (h / total) * 100

    @property
    def away_percent(self) -> float:
        """Away percentage for bar chart."""
        return 100 - self.home_percent

    def to_stat_bar_html(self) -> str:
        """Render as comparison bar with label above."""
        return f"""
        <div class="stat-item">
            <div class="stat-label">{self.label}</div>
            <div class="stat-row">
                <span class="stat-value stat-home">{self.home_display}</span>
                <div class="stat-bar-container">
                    <div class="stat-bar stat-bar-home" style="width: {self.home_percent}%"></div>
                    <div class="stat-bar stat-bar-away" style="width: {self.away_percent}%"></div>
                </div>
                <span class="stat-value stat-away">{self.away_display}</span>
            </div>
        </div>
        """


@dataclass
class MatchDetailView:
    """Full view model for Match Center page."""
    # Basic info
    id: int
    date: str
    date_formatted: str
    time_formatted: str
    venue: Optional[str]
    referee: Optional[str]

    # Status
    status: str
    status_short: str
    elapsed: Optional[int]
    is_live: bool
    is_finished: bool

    # Teams
    home_team_id: int
    home_team_name: str
    home_team_logo: str
    away_team_id: int
    away_team_name: str
    away_team_logo: str

    # Score
    home_goals: int
    away_goals: int
    halftime_home: Optional[int]
    halftime_away: Optional[int]

    # League
    league_name: Optional[str]
    league_logo: Optional[str]
    match_round: Optional[str]

    # Nested data
    events: List[MatchEventView] = field(default_factory=list)
    home_lineup: Optional[TeamLineupView] = None
    away_lineup: Optional[TeamLineupView] = None
    statistics: List[MatchStatView] = field(default_factory=list)

    # Metadata
    last_updated: str = ""

    @classmethod
    def from_live_match_data(cls, data) -> "MatchDetailView":
        """Create from LiveMatchData object."""
        # Parse date and convert to CST
        date_str = data.date or ""
        date_formatted = ""
        time_formatted = ""
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                dt_cst = convert_utc_to_cst(dt)
                date_formatted = dt_cst.strftime("%a, %b %d, %Y")
                time_formatted = dt_cst.strftime("%H:%M CST")
            except:
                date_formatted = date_str[:10] if len(date_str) > 10 else date_str

        # Convert events
        events = []
        for e in data.events:
            events.append(MatchEventView(
                minute=e.minute,
                extra_time=e.extra_time,
                event_type=e.event_type,
                detail=e.detail,
                team_id=e.team_id,
                team_name=e.team_name,
                is_home=e.is_home,
                player_name=e.player_name,
                player_id=e.player_id,
                assist_name=e.assist_name,
            ))

        # Convert lineups
        home_lineup = None
        away_lineup = None
        if data.home_lineup:
            home_lineup = TeamLineupView(
                team_id=data.home_lineup.team_id,
                team_name=data.home_lineup.team_name,
                team_logo=data.home_lineup.team_logo,
                formation=data.home_lineup.formation,
                coach_name=data.home_lineup.coach_name,
                starting_xi=[
                    LineupPlayerView(
                        id=p.id, name=p.name, number=p.number,
                        position=p.position, grid=p.grid
                    ) for p in data.home_lineup.starting_xi
                ],
                substitutes=[
                    LineupPlayerView(
                        id=p.id, name=p.name, number=p.number, position=p.position
                    ) for p in data.home_lineup.substitutes
                ],
            )
        if data.away_lineup:
            away_lineup = TeamLineupView(
                team_id=data.away_lineup.team_id,
                team_name=data.away_lineup.team_name,
                team_logo=data.away_lineup.team_logo,
                formation=data.away_lineup.formation,
                coach_name=data.away_lineup.coach_name,
                starting_xi=[
                    LineupPlayerView(
                        id=p.id, name=p.name, number=p.number,
                        position=p.position, grid=p.grid
                    ) for p in data.away_lineup.starting_xi
                ],
                substitutes=[
                    LineupPlayerView(
                        id=p.id, name=p.name, number=p.number, position=p.position
                    ) for p in data.away_lineup.substitutes
                ],
            )

        # Convert statistics
        statistics = [
            MatchStatView(
                stat_type=s.stat_type,
                home_value=s.home_value,
                away_value=s.away_value,
            ) for s in data.statistics
        ]

        return cls(
            id=data.id,
            date=data.date,
            date_formatted=date_formatted,
            time_formatted=time_formatted,
            venue=data.venue,
            referee=data.referee,
            status=data.status,
            status_short=data.status_short,
            elapsed=data.elapsed,
            is_live=data.is_live,
            is_finished=data.is_finished,
            home_team_id=data.home_team.id,
            home_team_name=data.home_team.name,
            home_team_logo=data.home_team.logo,
            away_team_id=data.away_team.id,
            away_team_name=data.away_team.name,
            away_team_logo=data.away_team.logo,
            home_goals=data.home_goals,
            away_goals=data.away_goals,
            halftime_home=data.halftime_home,
            halftime_away=data.halftime_away,
            league_name=data.league_name,
            league_logo=data.league_logo,
            match_round=data.match_round,
            events=events,
            home_lineup=home_lineup,
            away_lineup=away_lineup,
            statistics=statistics,
            last_updated=data.last_updated,
        )

    @property
    def score_display(self) -> str:
        """Format score as 'X - Y'."""
        h = self.home_goals if self.home_goals is not None else "-"
        a = self.away_goals if self.away_goals is not None else "-"
        return f"{h} - {a}"

    @property
    def halftime_display(self) -> Optional[str]:
        """Format halftime score."""
        if self.halftime_home is not None and self.halftime_away is not None:
            return f"HT: {self.halftime_home} - {self.halftime_away}"
        return None

    @property
    def elapsed_display(self) -> str:
        """Format elapsed time."""
        if not self.is_live or self.elapsed is None:
            return ""
        return f"{self.elapsed}'"

    @property
    def status_badge_html(self) -> str:
        """Status badge HTML with live clock for live matches."""
        if self.is_live:
            # Live clock shows mm:ss format, updated by JavaScript
            elapsed = self.elapsed if self.elapsed is not None else 0
            return f'<span class="status-badge status-live"><span id="live-clock" data-elapsed="{elapsed}">{elapsed}:00</span></span>'
        elif self.is_finished:
            return '<span class="status-badge status-finished">FT</span>'
        else:
            return f'<span class="status-badge status-upcoming">{self.time_formatted}</span>'

    @property
    def has_events(self) -> bool:
        return len(self.events) > 0

    @property
    def has_lineups(self) -> bool:
        return self.home_lineup is not None and self.away_lineup is not None

    @property
    def has_statistics(self) -> bool:
        return len(self.statistics) > 0

    def to_scoreboard_html(self) -> str:
        """Render scoreboard header."""
        halftime_html = f'<div class="halftime">{self.halftime_display}</div>' if self.halftime_display else ''

        return f"""
        <div class="match-scoreboard">
            <div class="scoreboard-header">
                {f'<img src="{self.league_logo}" class="league-logo">' if self.league_logo else ''}
                <span class="league-info">{self.league_name or 'Unknown League'} - {self.match_round or ''}</span>
            </div>
            <div class="scoreboard-main">
                <div class="scoreboard-team scoreboard-home">
                    <img src="{self.home_team_logo}" alt="" class="team-logo-large">
                    <a href="/ui/teams/{self.home_team_id}" class="team-name">{self.home_team_name}</a>
                </div>
                <div class="scoreboard-score">
                    <div class="score-main">{self.score_display}</div>
                    {halftime_html}
                    {self.status_badge_html}
                </div>
                <div class="scoreboard-team scoreboard-away">
                    <img src="{self.away_team_logo}" alt="" class="team-logo-large">
                    <a href="/ui/teams/{self.away_team_id}" class="team-name">{self.away_team_name}</a>
                </div>
            </div>
            <div class="scoreboard-meta">
                <span class="match-venue">{self.venue or ''}</span>
                <span class="match-date">{self.date_formatted}</span>
                {f'<span class="match-referee">Referee: {self.referee}</span>' if self.referee else ''}
            </div>
        </div>
        """


def predicted_lineup_to_view(
    prediction: "PredictedLineup",
    team_logo: str = "",
) -> TeamLineupView:
    """
    Convert a PredictedLineup to TeamLineupView for display.

    Args:
        prediction: The predicted lineup from predicted_xi module
        team_logo: URL to team logo

    Returns:
        TeamLineupView ready for HTML rendering
    """
    from app.predicted_xi import PredictedLineup

    starting_xi = [
        LineupPlayerView(
            id=p.player_id,
            name=p.player_name,
            number=p.squad_number,
            position=p.position,
            grid=p.grid_position,
        )
        for p in prediction.starting_xi
    ]

    bench = [
        LineupPlayerView(
            id=p.player_id,
            name=p.player_name,
            number=p.squad_number,
            position=p.position,
            grid=None,
        )
        for p in prediction.bench[:7]  # Limit bench display to 7
    ]

    return TeamLineupView(
        team_id=prediction.team_id,
        team_name=prediction.team_name,
        team_logo=team_logo,
        formation=prediction.formation,
        coach_name=None,
        starting_xi=starting_xi,
        substitutes=bench,
        is_predicted=True,
        prediction_confidence=prediction.overall_confidence,
    )


# ===== TEAM DASHBOARD VIEW MODELS =====

@dataclass
class TeamDashboardView:
    """View model for team dashboard page."""
    # Basic info
    id: int
    name: str
    logo: str
    venue: str
    city: str
    founded: Optional[int]

    # League context
    league_position: Optional[int]
    form: str  # "WWDWL" style
    points: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int

    # Home/Away splits
    home_played: int
    home_won: int
    home_drawn: int
    home_lost: int
    home_goals_for: int
    home_goals_against: int
    away_played: int
    away_won: int
    away_drawn: int
    away_lost: int
    away_goals_for: int
    away_goals_against: int

    # Fixtures
    next_fixture: Optional[MatchCardView]
    last_5_results: List[MatchCardView]

    # Squad grouped by position
    squad_by_position: Dict[str, List[Dict[str, Any]]]

    # Top contributors
    top_scorers: List[Dict[str, Any]]
    top_assists: List[Dict[str, Any]]

    # Injuries
    injured_player_ids: List[int] = field(default_factory=list)
    injury_count: int = 0

    @classmethod
    def from_data(
        cls,
        team_info: Dict[str, Any],
        standings_data: Optional[Dict[str, Any]],
        fixtures_data: Dict[str, Any],
        squad_data: Dict[str, Any],
        top_scorers: List[Dict[str, Any]],
        top_assists: List[Dict[str, Any]],
        injuries_data: Optional[Dict[str, Any]] = None,
    ) -> "TeamDashboardView":
        """Build TeamDashboardView from API data."""
        # Extract league position info
        league_position = None
        form = ""
        points = 0
        played = won = drawn = lost = goals_for = goals_against = 0
        # Home/away splits
        home_played = home_won = home_drawn = home_lost = home_gf = home_ga = 0
        away_played = away_won = away_drawn = away_lost = away_gf = away_ga = 0

        if standings_data:
            for row in standings_data.get("standings", []):
                if row.get("team", {}).get("id") == team_info.get("id"):
                    league_position = row.get("position")
                    form = row.get("form", "") or ""
                    points = row.get("points", 0)
                    played = row.get("played", 0)
                    won = row.get("won", 0)
                    drawn = row.get("drawn", 0)
                    lost = row.get("lost", 0)
                    goals_for = row.get("goals_for", 0)
                    goals_against = row.get("goals_against", 0)
                    # Home/away splits
                    home = row.get("home", {})
                    away = row.get("away", {})
                    home_played = home.get("played", 0)
                    home_won = home.get("won", 0)
                    home_drawn = home.get("drawn", 0)
                    home_lost = home.get("lost", 0)
                    home_gf = home.get("goals_for", 0)
                    home_ga = home.get("goals_against", 0)
                    away_played = away.get("played", 0)
                    away_won = away.get("won", 0)
                    away_drawn = away.get("drawn", 0)
                    away_lost = away.get("lost", 0)
                    away_gf = away.get("goals_for", 0)
                    away_ga = away.get("goals_against", 0)
                    break

        # Extract injury info
        injured_player_ids = []
        injury_count = 0
        if injuries_data:
            injured_player_ids = injuries_data.get("injured_player_ids", [])
            injury_count = injuries_data.get("count", 0)

        # Convert fixtures to MatchCardView
        last_5 = [
            MatchCardView.from_api(m)
            for m in fixtures_data.get("last_5", [])
        ]

        next_fix = fixtures_data.get("next_fixture")
        next_fixture = MatchCardView.from_api(next_fix) if next_fix else None

        # Group squad by position
        squad_by_position = {
            "Goalkeepers": [],
            "Defenders": [],
            "Midfielders": [],
            "Forwards": [],
            "Other": [],
        }

        for player in squad_data.get("players", []):
            pos = player.get("position", "") or ""
            if "Goal" in pos:
                squad_by_position["Goalkeepers"].append(player)
            elif "Defend" in pos or pos == "Defender":
                squad_by_position["Defenders"].append(player)
            elif "Mid" in pos or pos == "Midfielder":
                squad_by_position["Midfielders"].append(player)
            elif "Att" in pos or "Forward" in pos or pos == "Attacker":
                squad_by_position["Forwards"].append(player)
            else:
                squad_by_position["Other"].append(player)

        # Remove empty position groups
        squad_by_position = {k: v for k, v in squad_by_position.items() if v}

        return cls(
            id=team_info.get("id", 0),
            name=team_info.get("name", "Unknown"),
            logo=team_info.get("logo", ""),
            venue=team_info.get("venue", ""),
            city=team_info.get("city", ""),
            founded=team_info.get("founded"),
            league_position=league_position,
            form=form,
            points=points,
            played=played,
            won=won,
            drawn=drawn,
            lost=lost,
            goals_for=goals_for,
            goals_against=goals_against,
            # Home/away splits
            home_played=home_played,
            home_won=home_won,
            home_drawn=home_drawn,
            home_lost=home_lost,
            home_goals_for=home_gf,
            home_goals_against=home_ga,
            away_played=away_played,
            away_won=away_won,
            away_drawn=away_drawn,
            away_lost=away_lost,
            away_goals_for=away_gf,
            away_goals_against=away_ga,
            # Fixtures
            next_fixture=next_fixture,
            last_5_results=last_5,
            squad_by_position=squad_by_position,
            top_scorers=top_scorers,
            top_assists=top_assists,
            # Injuries
            injured_player_ids=injured_player_ids,
            injury_count=injury_count,
        )

    @property
    def form_display(self) -> str:
        """Format form string with spacing."""
        return " ".join(list(self.form)) if self.form else "—"

    @property
    def position_suffix(self) -> str:
        """Get ordinal suffix for position."""
        if not self.league_position:
            return ""
        pos = self.league_position
        if 10 <= pos % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(pos % 10, "th")
        return f"{pos}{suffix}"

    @property
    def goal_difference(self) -> int:
        """Calculate goal difference."""
        return self.goals_for - self.goals_against

    @property
    def home_record_display(self) -> str:
        """Format home record as W-D-L."""
        return f"W{self.home_won} D{self.home_drawn} L{self.home_lost}"

    @property
    def away_record_display(self) -> str:
        """Format away record as W-D-L."""
        return f"W{self.away_won} D{self.away_drawn} L{self.away_lost}"

    @property
    def home_ppg(self) -> float:
        """Points per game at home."""
        if self.home_played == 0:
            return 0.0
        points = (self.home_won * 3) + self.home_drawn
        return round(points / self.home_played, 2)

    @property
    def away_ppg(self) -> float:
        """Points per game away."""
        if self.away_played == 0:
            return 0.0
        points = (self.away_won * 3) + self.away_drawn
        return round(points / self.away_played, 2)

    @property
    def home_goal_difference(self) -> int:
        """Home goal difference."""
        return self.home_goals_for - self.home_goals_against

    @property
    def away_goal_difference(self) -> int:
        """Away goal difference."""
        return self.away_goals_for - self.away_goals_against

    def is_player_injured(self, player_id: int) -> bool:
        """Check if a player is in the injured list."""
        return player_id in self.injured_player_ids

"""
Pydantic schemas for API request/response models
Phase 3: Define response structures for API endpoints
"""
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


# ===== TEAM SCHEMAS =====

class TeamBase(BaseModel):
    """Base team schema"""
    name: str

    class Config:
        from_attributes = True


class Team(TeamBase):
    """Team response with ID"""
    id: int


class TeamDetail(Team):
    """Detailed team info (for future expansion)"""
    pass


# ===== STANDING SCHEMAS =====

class StandingBase(BaseModel):
    """Base standing schema"""
    season: str
    position: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    form: Optional[str] = None
    source: str

    class Config:
        from_attributes = True


class Standing(StandingBase):
    """Standing response with ID and team info"""
    id: int
    team_id: int
    team: Team


class StandingsList(BaseModel):
    """List of standings with metadata"""
    season: str
    count: int
    standings: list[Standing]


# ===== MATCH SCHEMAS =====

class MatchBase(BaseModel):
    """Base match schema"""
    date: date
    season: str
    home_goals: int
    away_goals: int
    result: str
    home_goals_ht: Optional[int] = None
    away_goals_ht: Optional[int] = None
    home_shots: Optional[int] = None
    away_shots: Optional[int] = None
    home_shots_on_target: Optional[int] = None
    away_shots_on_target: Optional[int] = None
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    home_fouls: Optional[int] = None
    away_fouls: Optional[int] = None
    home_yellow_cards: Optional[int] = None
    away_yellow_cards: Optional[int] = None
    home_red_cards: Optional[int] = None
    away_red_cards: Optional[int] = None
    referee: Optional[str] = None
    venue: Optional[str] = None
    attendance: Optional[int] = None
    source: str

    class Config:
        from_attributes = True


class Match(MatchBase):
    """Match response with ID and team info"""
    id: int
    home_team_id: int
    away_team_id: int
    home_team: Team
    away_team: Team


# ===== PLAYER SCHEMAS =====

class PlayerBase(BaseModel):
    """Base player schema"""
    name: str
    season: str
    position: str
    nationality: Optional[str] = None
    age: Optional[int] = None
    appearances: int
    minutes_played: int
    starts: Optional[int] = None
    goals: int
    assists: int
    penalties_scored: Optional[int] = None
    penalties_missed: Optional[int] = None
    yellow_cards: Optional[int] = None
    red_cards: Optional[int] = None
    shots: Optional[int] = None
    shots_on_target: Optional[int] = None
    passes: Optional[int] = None
    key_passes: Optional[int] = None
    dribbles: Optional[int] = None
    tackles: Optional[int] = None
    interceptions: Optional[int] = None
    source: str

    class Config:
        from_attributes = True


class Player(PlayerBase):
    """Player response with ID and team info"""
    id: int
    team_id: int
    team: Team


# ===== SEARCH SCHEMAS =====

class SearchResult(BaseModel):
    """Combined search results for teams and players"""
    query: str
    teams: list[Team]
    players: list[Player]
    team_count: int
    player_count: int

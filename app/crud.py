"""
CRUD operations (Create, Read, Update, Delete)
Phase 3: Database query functions for teams, matches, players, standings
"""
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from app.models import Team, Standing, Match, Player
from typing import Optional, List


# ===== TEAMS =====

def get_teams(db: Session, skip: int = 0, limit: int = 100) -> List[Team]:
    """
    Get all teams with pagination
    """
    return db.query(Team).offset(skip).limit(limit).all()


def get_team_by_id(db: Session, team_id: int) -> Optional[Team]:
    """
    Get a specific team by ID
    """
    return db.query(Team).filter(Team.id == team_id).first()


def get_team_by_name(db: Session, name: str) -> Optional[Team]:
    """
    Get a team by name (case-insensitive)
    """
    return db.query(Team).filter(Team.name.ilike(name)).first()


# ===== STANDINGS =====

def get_standings(
    db: Session,
    season: str,
    skip: int = 0,
    limit: int = 100
) -> List[Standing]:
    """
    Get standings for a season, ordered by position
    """
    return (
        db.query(Standing)
        .options(joinedload(Standing.team))
        .filter(Standing.season == season)
        .order_by(Standing.position)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_team_standing(
    db: Session,
    team_id: int,
    season: str
) -> Optional[Standing]:
    """
    Get a specific team's standing for a season
    """
    return (
        db.query(Standing)
        .options(joinedload(Standing.team))
        .filter(Standing.team_id == team_id, Standing.season == season)
        .first()
    )


# ===== MATCHES =====

def get_matches(
    db: Session,
    season: Optional[str] = None,
    team_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Match]:
    """
    Get matches with optional filters
    - season: filter by season (e.g., "2024-25")
    - team_id: filter matches where team is home or away
    """
    query = (
        db.query(Match)
        .options(joinedload(Match.home_team), joinedload(Match.away_team))
        .order_by(desc(Match.date))
    )

    if season:
        query = query.filter(Match.season == season)

    if team_id:
        query = query.filter(
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id)
        )

    return query.offset(skip).limit(limit).all()


def get_match_by_id(db: Session, match_id: int) -> Optional[Match]:
    """
    Get a specific match by ID
    """
    return (
        db.query(Match)
        .options(joinedload(Match.home_team), joinedload(Match.away_team))
        .filter(Match.id == match_id)
        .first()
    )


# ===== PLAYERS =====

def get_players(
    db: Session,
    season: Optional[str] = None,
    team_id: Optional[int] = None,
    position: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Player]:
    """
    Get players with optional filters
    - season: filter by season
    - team_id: filter by team
    - position: filter by position
    """
    query = (
        db.query(Player)
        .options(joinedload(Player.team))
        .order_by(desc(Player.goals))
    )

    if season:
        query = query.filter(Player.season == season)

    if team_id:
        query = query.filter(Player.team_id == team_id)

    if position:
        query = query.filter(Player.position.ilike(f"%{position}%"))

    return query.offset(skip).limit(limit).all()


def get_top_scorers(
    db: Session,
    season: str,
    limit: int = 20
) -> List[Player]:
    """
    Get top scorers for a season
    """
    return (
        db.query(Player)
        .options(joinedload(Player.team))
        .filter(Player.season == season)
        .order_by(desc(Player.goals))
        .limit(limit)
        .all()
    )


def get_player_by_id(db: Session, player_id: int) -> Optional[Player]:
    """
    Get a specific player by ID
    """
    return (
        db.query(Player)
        .options(joinedload(Player.team))
        .filter(Player.id == player_id)
        .first()
    )


def get_players_by_team(db: Session, team_id: int, limit: int = 100) -> List[Player]:
    """
    Get all players for a specific team (for roster view)
    """
    return (
        db.query(Player)
        .options(joinedload(Player.team))
        .filter(Player.team_id == team_id)
        .order_by(desc(Player.goals))
        .limit(limit)
        .all()
    )


# ===== SEARCH =====

def search_teams(db: Session, query: str, limit: int = 20) -> List[Team]:
    """
    Search teams by name (case-insensitive partial match)
    """
    return (
        db.query(Team)
        .filter(Team.name.ilike(f"%{query}%"))
        .limit(limit)
        .all()
    )


def search_players(db: Session, query: str, limit: int = 20) -> List[Player]:
    """
    Search players by name (case-insensitive partial match)
    Returns players ordered by goals (best performers first)
    """
    return (
        db.query(Player)
        .options(joinedload(Player.team))
        .filter(Player.name.ilike(f"%{query}%"))
        .order_by(desc(Player.goals))
        .limit(limit)
        .all()
    )

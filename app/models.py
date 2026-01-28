"""
Database models for Baby Futmob v0
SQLAlchemy ORM models for teams, standings, matches, and players
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Team(Base):
    """
    Team entity - unique team identities (e.g., Liverpool, Arsenal)
    One record per team, referenced by standings/matches/players
    """
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False, index=True)

    # Relationships
    standings = relationship("Standing", back_populates="team")
    home_matches = relationship("Match", foreign_keys="Match.home_team_id", back_populates="home_team")
    away_matches = relationship("Match", foreign_keys="Match.away_team_id", back_populates="away_team")
    players = relationship("Player", back_populates="team")

    def __repr__(self):
        return f"<Team(id={self.id}, name='{self.name}')>"


class Standing(Base):
    """
    Standing entity - team performance in a specific season
    One record per team per season
    """
    __tablename__ = "standings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    season = Column(String, nullable=False, index=True)
    position = Column(Integer, nullable=False)
    played = Column(Integer, nullable=False)
    won = Column(Integer, nullable=False)
    drawn = Column(Integer, nullable=False)
    lost = Column(Integer, nullable=False)
    goals_for = Column(Integer, nullable=False)
    goals_against = Column(Integer, nullable=False)
    goal_difference = Column(Integer, nullable=False)
    points = Column(Integer, nullable=False)
    form = Column(String, nullable=True)
    source = Column(String, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    team = relationship("Team", back_populates="standings")

    # Constraints
    __table_args__ = (
        UniqueConstraint("team_id", "season", name="uix_team_season"),
    )

    def __repr__(self):
        return f"<Standing(team_id={self.team_id}, season='{self.season}', position={self.position}, points={self.points})>"


class Match(Base):
    """
    Match entity - individual match records with teams, scores, and statistics
    """
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    season = Column(String, nullable=False, index=True)
    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    home_goals = Column(Integer, nullable=False)
    away_goals = Column(Integer, nullable=False)
    result = Column(String, nullable=False)  # H/A/D

    # Half-time scores
    home_goals_ht = Column(Integer, nullable=True)
    away_goals_ht = Column(Integer, nullable=True)

    # Match statistics
    home_shots = Column(Integer, nullable=True)
    away_shots = Column(Integer, nullable=True)
    home_shots_on_target = Column(Integer, nullable=True)
    away_shots_on_target = Column(Integer, nullable=True)
    home_corners = Column(Integer, nullable=True)
    away_corners = Column(Integer, nullable=True)
    home_fouls = Column(Integer, nullable=True)
    away_fouls = Column(Integer, nullable=True)
    home_yellow_cards = Column(Integer, nullable=True)
    away_yellow_cards = Column(Integer, nullable=True)
    home_red_cards = Column(Integer, nullable=True)
    away_red_cards = Column(Integer, nullable=True)

    # Match details
    referee = Column(String, nullable=True)
    venue = Column(String, nullable=True)
    attendance = Column(Integer, nullable=True)
    match_id = Column(String, nullable=True)
    source = Column(String, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_matches")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_matches")

    # Constraints - prevent duplicate matches
    __table_args__ = (
        UniqueConstraint("date", "home_team_id", "away_team_id", name="uix_match_date_teams"),
    )

    def __repr__(self):
        return f"<Match(date={self.date}, home_team_id={self.home_team_id}, away_team_id={self.away_team_id}, score={self.home_goals}-{self.away_goals})>"


class Player(Base):
    """
    Player entity - player statistics for a season
    A player can have multiple records (different seasons or transfers)
    """
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    season = Column(String, nullable=False, index=True)
    position = Column(String, nullable=False)
    nationality = Column(String, nullable=True)
    age = Column(Integer, nullable=True)

    # Performance stats
    appearances = Column(Integer, nullable=False)
    minutes_played = Column(Integer, nullable=False)
    starts = Column(Integer, nullable=True)
    goals = Column(Integer, nullable=False, default=0)
    assists = Column(Integer, nullable=False, default=0)
    penalties_scored = Column(Integer, nullable=True)
    penalties_missed = Column(Integer, nullable=True)

    # Discipline
    yellow_cards = Column(Integer, nullable=True)
    red_cards = Column(Integer, nullable=True)

    # Advanced stats
    shots = Column(Integer, nullable=True)
    shots_on_target = Column(Integer, nullable=True)
    passes = Column(Integer, nullable=True)
    key_passes = Column(Integer, nullable=True)
    dribbles = Column(Integer, nullable=True)
    tackles = Column(Integer, nullable=True)
    interceptions = Column(Integer, nullable=True)

    # Metadata
    player_id = Column(String, nullable=True)
    source = Column(String, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    team = relationship("Team", back_populates="players")

    # Constraints - one record per player per team per season
    __table_args__ = (
        UniqueConstraint("name", "team_id", "season", name="uix_player_team_season"),
    )

    def __repr__(self):
        return f"<Player(name='{self.name}', team_id={self.team_id}, season='{self.season}', goals={self.goals})>"

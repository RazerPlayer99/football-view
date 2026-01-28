"""
Provider interface for Predicted XI.

Clean interface for generating and retrieving predictions,
integrating with the app's api_client for data fetching.
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import PredictedLineup, ConfirmedLineup, AccuracyRecord
from .predictor import PredictionEngine
from .evaluator import get_prediction_evaluator
from .storage import get_prediction_storage

logger = logging.getLogger("predicted_xi.provider")

# How many historical matches to analyze
HISTORY_LIMIT = 5


class PredictedXIProvider:
    """
    Main interface for the Predicted XI system.

    Handles:
    - Generating predictions for upcoming matches
    - Retrieving existing predictions
    - Triggering evaluation when confirmed lineups arrive
    """

    def __init__(self):
        self.storage = get_prediction_storage()
        self.engine = PredictionEngine()
        self.evaluator = get_prediction_evaluator()

    def get_or_generate_prediction(
        self,
        match_id: int,
        team_id: int,
        force_regenerate: bool = False,
    ) -> Optional[PredictedLineup]:
        """
        Get prediction for a match, generating if needed.

        Args:
            match_id: The fixture ID
            team_id: The team ID
            force_regenerate: Force regeneration even if prediction exists

        Returns:
            PredictedLineup or None if unable to generate
        """
        # Check for confirmed lineup first
        if self.storage.has_confirmed_lineup(match_id, team_id):
            logger.info(f"Confirmed lineup exists for match {match_id}, team {team_id}")
            return None

        # Check for existing prediction
        if not force_regenerate:
            existing = self.storage.get_prediction(match_id, team_id)
            if existing:
                return existing

        # Generate new prediction
        return self.generate_prediction(match_id, team_id)

    def generate_prediction(
        self,
        match_id: int,
        team_id: int,
    ) -> Optional[PredictedLineup]:
        """
        Generate a new prediction for a match.

        Fetches required data from api_client and runs prediction engine.
        """
        try:
            from app import api_client

            # Get match info
            match_data = api_client.get_match_by_id(match_id)
            if not match_data:
                logger.error(f"Match {match_id} not found")
                return None

            # Determine if this team is home or away
            home_team = match_data.get("home_team", {})
            away_team = match_data.get("away_team", {})

            if home_team.get("id") == team_id:
                team_name = home_team.get("name", "")
            elif away_team.get("id") == team_id:
                team_name = away_team.get("name", "")
            else:
                logger.error(f"Team {team_id} not in match {match_id}")
                return None

            # Calculate days until match
            match_date = match_data.get("date", "")
            days_until = self._calculate_days_until(match_date)

            # Get current season
            season = self._get_current_season()

            # Fetch squad (None for league_id to get players across all competitions)
            squad_data = api_client.get_team_players(team_id, season, league_id=None)
            squad = squad_data.get("players", [])
            if not squad:
                logger.warning(f"No squad data for team {team_id}")
                return None

            # Fetch historical lineups
            historical_lineups = self._fetch_historical_lineups(
                team_id, season, limit=HISTORY_LIMIT
            )

            # Fetch player match logs only for players who appear in historical lineups
            # This dramatically reduces API calls while keeping prediction quality
            player_match_logs = {}
            players_in_history = set()
            for lineup in historical_lineups:
                for p in lineup.get("starting_xi", []) + lineup.get("substitutes", []):
                    pid = p.get("id") if isinstance(p, dict) else p
                    if pid:
                        players_in_history.add(pid)

            # Only fetch match logs for players who have actually played recently
            # Limit based on HISTORY_LIMIT to keep page load fast
            # Use ThreadPoolExecutor to fetch in parallel for significant speedup
            players_to_fetch = list(players_in_history)[:11]  # Max starting XI size

            def fetch_player_log(player_id: int) -> tuple:
                """Fetch a single player's match log."""
                try:
                    log_data = api_client.get_player_match_log(player_id, season)
                    return (player_id, log_data.get("fixtures", []))
                except Exception as e:
                    logger.debug(f"Could not fetch match log for player {player_id}: {e}")
                    return (player_id, [])

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(fetch_player_log, pid) for pid in players_to_fetch]
                for future in as_completed(futures):
                    player_id, fixtures = future.result()
                    if fixtures:
                        player_match_logs[player_id] = fixtures

            # Get coach ID if available
            coach_id = self._get_coach_id(team_id)

            # Determine competition type from match data
            competition = self._get_competition_type(match_data)

            # Generate prediction
            prediction = self.engine.predict_lineup(
                match_id=match_id,
                team_id=team_id,
                team_name=team_name,
                squad=squad,
                historical_lineups=historical_lineups,
                player_match_logs=player_match_logs,
                coach_id=coach_id,
                days_until_match=days_until,
            )

            # Set season and competition for tracking
            prediction.season = season
            prediction.competition = competition

            # Save prediction
            self.storage.save_prediction(prediction)

            logger.info(
                f"Generated prediction for match {match_id}, team {team_id}: "
                f"{prediction.formation}, confidence {prediction.overall_confidence:.2f}"
            )

            return prediction

        except Exception as e:
            logger.error(f"Failed to generate prediction: {e}", exc_info=True)
            return None

    def _fetch_historical_lineups(
        self, team_id: int, season: int, limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Fetch historical lineups for a team."""
        try:
            from app import api_client

            # Get team's matches across all competitions (finished ones only)
            matches_data = api_client.get_matches(
                season, league_id=None, team_id=team_id, limit=limit * 2  # Get more to filter
            )
            # Filter to finished matches only
            all_matches = matches_data.get("matches", [])
            matches = [
                m for m in all_matches
                if m.get("status") in ("Match Finished", "FT", "AET", "PEN")
            ][:limit]

            # Fetch lineups in parallel for significant speedup
            def fetch_lineup(match: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                """Fetch lineup for a single match."""
                match_id = match.get("id")
                if not match_id:
                    return None
                try:
                    lineup_data = api_client.get_match_lineups(match_id)
                    team_lineups = lineup_data.get("lineups", [])

                    # Find this team's lineup
                    for lineup in team_lineups:
                        if lineup.get("team_id") == team_id:
                            # Add match metadata
                            lineup["match_id"] = match_id
                            lineup["date"] = match.get("date")
                            lineup["opponent_id"] = (
                                match.get("away_team", {}).get("id")
                                if match.get("home_team", {}).get("id") == team_id
                                else match.get("home_team", {}).get("id")
                            )
                            return lineup
                except Exception as e:
                    logger.debug(f"Could not fetch lineup for match {match_id}: {e}")
                return None

            lineups = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(fetch_lineup, match) for match in matches]
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        lineups.append(result)

            return lineups

        except Exception as e:
            logger.error(f"Failed to fetch historical lineups: {e}")
            return []

    def _calculate_days_until(self, match_date: str) -> Optional[int]:
        """Calculate days until match."""
        if not match_date:
            return None
        try:
            dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            now = datetime.now(dt.tzinfo)
            return (dt - now).days
        except (ValueError, TypeError):
            return None

    def _get_current_season(self) -> int:
        """Get the current season year."""
        now = datetime.now()
        # Season typically starts in August
        if now.month >= 8:
            return now.year
        return now.year - 1

    def _get_coach_id(self, team_id: int) -> Optional[int]:
        """Get the coach ID for a team (if available)."""
        # For now, we don't have a direct coach endpoint
        # This could be enhanced to fetch from team data
        return None

    def _get_competition_type(self, match_data: Dict[str, Any]) -> str:
        """Determine competition type from match data."""
        league = match_data.get("league", {})
        league_name = league.get("name", "").lower()
        league_type = league.get("type", "").lower()

        # Map to competition types
        if "premier league" in league_name or "la liga" in league_name:
            return "league"
        if "champions league" in league_name:
            return "champions_league"
        if "europa" in league_name:
            return "europa_league"
        if "cup" in league_name or "fa cup" in league_name:
            return "cup"
        if "friendly" in league_name or league_type == "friendly":
            return "friendly"
        if league_type == "league":
            return "league"
        if league_type == "cup":
            return "cup"

        return "league"  # Default to league

    def record_confirmed_lineup(
        self,
        match_id: int,
        team_id: int,
        formation: Optional[str],
        starting_xi: List[int],
        coach_id: Optional[int] = None,
    ) -> Optional[AccuracyRecord]:
        """
        Record a confirmed lineup and evaluate any existing prediction.

        Args:
            match_id: The fixture ID
            team_id: The team ID
            formation: The actual formation used
            starting_xi: List of player IDs in the starting XI
            coach_id: Optional coach ID for weight updates

        Returns:
            AccuracyRecord if a prediction existed, None otherwise
        """
        confirmed = ConfirmedLineup(
            match_id=match_id,
            team_id=team_id,
            formation=formation,
            starting_xi=starting_xi,
        )

        # Evaluate and update weights
        record, _ = self.evaluator.evaluate_and_update(
            match_id=match_id,
            team_id=team_id,
            actual_lineup=confirmed,
            coach_id=coach_id,
        )

        return record

    def get_accuracy_stats(
        self, team_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get accuracy statistics."""
        return self.storage.get_accuracy_stats(team_id)

    def get_prediction(
        self, match_id: int, team_id: int
    ) -> Optional[PredictedLineup]:
        """Get an existing prediction (does not generate)."""
        return self.storage.get_prediction(match_id, team_id)

    def get_season_accuracy(
        self,
        season: Optional[int] = None,
        competition: Optional[str] = None,
        include_team_breakdown: bool = False,
    ) -> Dict[str, Any]:
        """
        Get season accuracy summary.

        Args:
            season: Season year (defaults to current season)
            competition: Optional competition filter
            include_team_breakdown: Include per-team stats

        Returns:
            Dictionary with season accuracy metrics
        """
        if season is None:
            season = self._get_current_season()

        summary = self.storage.get_season_accuracy_summary(
            season=season,
            competition=competition,
            include_team_breakdown=include_team_breakdown,
        )
        return summary.to_dict()


# Singleton instance
_provider: Optional[PredictedXIProvider] = None


def get_predicted_xi_provider() -> PredictedXIProvider:
    """Get the predicted XI provider instance."""
    global _provider
    if _provider is None:
        _provider = PredictedXIProvider()
    return _provider

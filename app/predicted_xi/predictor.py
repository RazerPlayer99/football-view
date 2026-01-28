"""
Prediction engine for Predicted XI.

Core scoring algorithm with position-aware XI selection.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from .models import (
    PlayerFeatures,
    PredictedPlayer,
    PredictedLineup,
    FormationPrediction,
    MatchContext,
    MODEL_VERSION,
)
from .features import (
    extract_player_features,
    extract_formation_patterns,
    get_formation_positions,
    HISTORY_WINDOW,
)
from .storage import get_prediction_storage

logger = logging.getLogger("predicted_xi.predictor")


class PredictionEngine:
    """
    Core prediction engine using weighted feature scoring.

    Produces predicted lineups with confidence scores and explanations.
    """

    def __init__(self):
        self.storage = get_prediction_storage()

    def predict_lineup(
        self,
        match_id: int,
        team_id: int,
        team_name: str,
        squad: List[Dict[str, Any]],
        historical_lineups: List[Dict[str, Any]],
        player_match_logs: Dict[int, List[Dict[str, Any]]],
        coach_id: Optional[int] = None,
        days_until_match: Optional[int] = None,
        context: Optional[MatchContext] = None,
    ) -> PredictedLineup:
        """
        Generate a predicted lineup for a match.

        Args:
            match_id: The fixture ID
            team_id: The team ID
            team_name: The team name
            squad: List of squad players with id, name, position, number
            historical_lineups: Past lineups for pattern learning
            player_match_logs: Dict of player_id -> match log
            coach_id: Optional coach ID for coach-specific weights
            days_until_match: Days until the match (for rotation calculation)
            context: Optional match context (competition, home/away, days rest)

        Returns:
            PredictedLineup with starting XI, bench, and explanations
        """
        # Build context from available info if not provided
        if context is None:
            context = MatchContext(
                days_rest=days_until_match,
            )
        # Get effective weights
        weights = self.storage.get_weights(team_id=team_id, coach_id=coach_id)
        weights_version = self.storage.get_weights_version(team_id, coach_id)

        # Extract formation patterns
        formation_data = extract_formation_patterns(historical_lineups)
        formation = formation_data["primary_formation"]
        formation_confidence = formation_data["confidence"]

        # Get position requirements for formation
        position_needs = get_formation_positions(formation)

        # Extract features for all squad players
        player_features: Dict[int, PlayerFeatures] = {}
        for player in squad:
            player_id = player.get("id")
            if not player_id:
                continue

            match_log = player_match_logs.get(player_id, [])

            features = extract_player_features(
                player_id=player_id,
                player_name=player.get("name", "Unknown"),
                player_position=player.get("position", "M"),
                squad_number=player.get("number"),
                historical_lineups=self._filter_lineups_with_player(
                    player_id, historical_lineups
                ),
                match_log=match_log,
                days_until_match=days_until_match,
            )
            player_features[player_id] = features

        # Score all players (with context adjustment)
        scored_players: List[Tuple[int, float, Dict[str, float], PlayerFeatures]] = []

        for player_id, features in player_features.items():
            score, contributions = self._score_player(features, weights, context)
            scored_players.append((player_id, score, contributions, features))

        # Sort by score
        scored_players.sort(key=lambda x: x[1], reverse=True)

        # Select XI with position constraints
        starting_xi, bench = self._select_xi_with_positions(
            scored_players, position_needs, weights
        )

        # Calculate overall confidence
        overall_confidence = self._calculate_overall_confidence(starting_xi)

        # Identify key uncertainties (context-aware)
        uncertainties = self._identify_uncertainties(starting_xi, bench, context)

        # Build prediction
        prediction = PredictedLineup(
            match_id=match_id,
            team_id=team_id,
            team_name=team_name,
            model_version=MODEL_VERSION,
            weights_version=weights_version,
            formation=formation,
            formation_confidence=formation_confidence,
            starting_xi=starting_xi,
            bench=bench,
            overall_confidence=overall_confidence,
            key_uncertainties=uncertainties,
            based_on_matches=len(historical_lineups),
            context=context,
        )

        return prediction

    def _filter_lineups_with_player(
        self, player_id: int, lineups: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter lineups where the player was in the squad."""
        result = []
        for lineup in lineups:
            all_players = lineup.get("starting_xi", []) + lineup.get("substitutes", [])
            for p in all_players:
                pid = p.get("id") if isinstance(p, dict) else p
                if pid == player_id:
                    result.append(lineup)
                    break
        return result

    def _score_player(
        self,
        features: PlayerFeatures,
        weights: Dict[str, float],
        context: Optional[MatchContext] = None,
    ) -> Tuple[float, Dict[str, float]]:
        """
        Calculate weighted score for a player.

        Returns (total_score, feature_contributions).
        """
        feature_values = features.get_feature_dict()
        contributions = {}
        total_score = 0.0

        for feature_name, weight in weights.items():
            value = feature_values.get(feature_name, 0.0)
            contribution = weight * value
            contributions[feature_name] = contribution
            total_score += contribution

        # Apply context-based adjustments
        if context:
            total_score = self._apply_context_adjustments(
                total_score, features, context
            )

        return total_score, contributions

    def _apply_context_adjustments(
        self,
        base_score: float,
        features: PlayerFeatures,
        context: MatchContext,
    ) -> float:
        """
        Adjust player score based on match context.

        High priority matches = favor experienced starters
        High rotation likelihood = favor fresh/rotation players
        """
        adjusted = base_score

        # High priority match: boost regular starters
        if context.is_high_priority:
            if features.recent_starts > 0.7:
                adjusted *= 1.05  # 5% boost for regulars
            elif features.recent_starts < 0.3:
                adjusted *= 0.95  # 5% penalty for rotation players

        # High rotation likelihood: boost well-rested players
        rotation_likelihood = context.rotation_likelihood
        if rotation_likelihood > 0.5:
            # Favor players who haven't played as much
            if features.rotation_signal > 0.7:
                adjusted *= 1.0 + (rotation_likelihood - 0.5) * 0.1
            elif features.rotation_signal < 0.4:
                adjusted *= 1.0 - (rotation_likelihood - 0.5) * 0.1

        # Cup competition (non-knockout): slight rotation boost
        if context.competition == "cup" and not context.is_knockout:
            if features.recent_starts < 0.5:
                adjusted *= 1.03  # Slight boost for fringe players

        return adjusted

    def _select_xi_with_positions(
        self,
        scored_players: List[Tuple[int, float, Dict[str, float], PlayerFeatures]],
        position_needs: Dict[str, int],
        weights: Dict[str, float],
    ) -> Tuple[List[PredictedPlayer], List[PredictedPlayer]]:
        """
        Select starting XI respecting position constraints.

        Uses a greedy approach: fill each position slot with the
        best available player who can play that position.
        """
        starting_xi: List[PredictedPlayer] = []
        bench: List[PredictedPlayer] = []
        used_players: set = set()

        # Track remaining needs
        remaining = position_needs.copy()

        # First pass: fill positions with best-fit players
        for position in ["G", "D", "M", "F"]:
            needed = remaining.get(position, 0)

            # Get candidates for this position (sorted by score)
            candidates = [
                (pid, score, contrib, feat)
                for pid, score, contrib, feat in scored_players
                if pid not in used_players
                and self._can_play_position(feat, position)
            ]

            # Sort candidates by position-adjusted score
            candidates.sort(
                key=lambda x: self._position_adjusted_score(x[1], x[3], position),
                reverse=True,
            )

            # Select top candidates
            for i, (player_id, score, contributions, features) in enumerate(candidates):
                if i >= needed:
                    break

                predicted = self._create_predicted_player(
                    features, position, score, contributions, weights
                )
                starting_xi.append(predicted)
                used_players.add(player_id)

        # Add remaining players to bench (sorted by score)
        for player_id, score, contributions, features in scored_players:
            if player_id not in used_players:
                predicted = self._create_predicted_player(
                    features,
                    features.primary_position,
                    score,
                    contributions,
                    weights,
                    is_bench=True,
                )
                bench.append(predicted)

        return starting_xi, bench

    def _can_play_position(self, features: PlayerFeatures, position: str) -> bool:
        """Check if player can play a position."""
        from .features import _normalize_position, _get_position_compatibility

        primary = _normalize_position(features.primary_position)

        if primary == position:
            return True

        # Check if they've played this position
        for pos, count in features.positions_played.items():
            if _normalize_position(pos) == position and count > 0:
                return True

        # Check compatibility
        compatibility = _get_position_compatibility(primary, position)
        return compatibility >= 0.4

    def _position_adjusted_score(
        self, base_score: float, features: PlayerFeatures, target_position: str
    ) -> float:
        """Adjust score based on position fit."""
        from .features import _normalize_position, _get_position_compatibility

        primary = _normalize_position(features.primary_position)

        if primary == target_position:
            return base_score * 1.0

        # Check position history
        total_appearances = sum(features.positions_played.values())
        if total_appearances > 0:
            target_appearances = sum(
                count for pos, count in features.positions_played.items()
                if _normalize_position(pos) == target_position
            )
            if target_appearances > 0:
                history_bonus = (target_appearances / total_appearances) * 0.2
                return base_score * (0.8 + history_bonus)

        # Use compatibility
        compatibility = _get_position_compatibility(primary, target_position)
        return base_score * compatibility

    def _create_predicted_player(
        self,
        features: PlayerFeatures,
        position: str,
        score: float,
        contributions: Dict[str, float],
        weights: Dict[str, float],
        is_bench: bool = False,
    ) -> PredictedPlayer:
        """Create a PredictedPlayer with explanations."""
        # Generate explanations from top contributing features
        explanations = self._generate_explanations(features, contributions, weights)

        # Calculate confidence (normalize score to 0-1)
        # Max possible score is 1.0 if all features are 1.0
        confidence = min(1.0, score / sum(weights.values())) if sum(weights.values()) > 0 else 0.5

        if is_bench:
            confidence *= 0.5  # Lower confidence for bench predictions

        return PredictedPlayer(
            player_id=features.player_id,
            player_name=features.player_name,
            position=position,
            squad_number=features.squad_number,
            confidence=confidence,
            total_score=score,
            explanations=explanations,
            feature_contributions=contributions,
        )

    def _generate_explanations(
        self,
        features: PlayerFeatures,
        contributions: Dict[str, float],
        weights: Dict[str, float],
    ) -> List[str]:
        """Generate top 2-3 human-readable explanations."""
        explanations = []

        # Sort contributions by value
        sorted_contrib = sorted(
            contributions.items(), key=lambda x: x[1], reverse=True
        )

        for feature_name, contribution in sorted_contrib[:3]:
            if contribution <= 0:
                continue

            explanation = self._feature_to_explanation(feature_name, features)
            if explanation:
                explanations.append(explanation)

        return explanations[:3]  # Max 3

    def _feature_to_explanation(
        self, feature_name: str, features: PlayerFeatures
    ) -> Optional[str]:
        """Convert a feature to a human-readable explanation."""
        if feature_name == "recent_starts":
            if features.starts_last_n > 0:
                return f"Started {features.starts_last_n} of last {features.total_matches_last_n} matches"
            return None

        if feature_name == "minutes_trend":
            if features.minutes_trend > 0.6:
                return "Minutes increasing recently"
            elif features.minutes_trend < 0.4:
                return "Minutes decreasing"
            return None

        if feature_name == "position_fit":
            if features.position_fit > 0.8:
                return "Primary position"
            elif features.position_fit > 0.5:
                most_played = max(features.positions_played.items(), key=lambda x: x[1])[0] if features.positions_played else None
                if most_played:
                    return f"Has played this position ({features.positions_played.get(most_played, 0)} times)"
            return None

        if feature_name == "rotation_signal":
            if features.rotation_signal > 0.7:
                return "Well rested"
            elif features.rotation_signal < 0.5:
                return "May be rotated (high workload)"
            return None

        if feature_name == "availability":
            if features.availability < 0.7:
                if features.yellow_cards_season >= 4:
                    return f"Suspension risk ({features.yellow_cards_season} yellows)"
            return None

        if feature_name == "formation_consistency":
            if features.consecutive_starts >= 3:
                return f"Regular starter ({features.consecutive_starts} consecutive)"
            return None

        return None

    def _calculate_overall_confidence(
        self, starting_xi: List[PredictedPlayer]
    ) -> float:
        """Calculate overall prediction confidence."""
        if not starting_xi:
            return 0.0

        # Average confidence of starting XI
        avg_confidence = sum(p.confidence for p in starting_xi) / len(starting_xi)

        # Penalize if we had to use players in non-primary positions
        position_penalties = sum(
            1 for p in starting_xi
            if p.feature_contributions.get("position_fit", 1.0) < 0.8
        )
        penalty = position_penalties * 0.02

        return max(0.0, avg_confidence - penalty)

    def _identify_uncertainties(
        self,
        starting_xi: List[PredictedPlayer],
        bench: List[PredictedPlayer],
        context: Optional[MatchContext] = None,
    ) -> List[str]:
        """Identify key prediction uncertainties."""
        uncertainties = []

        # Find close calls (starter with similar score to bench player)
        if bench:
            lowest_starter_score = min(p.total_score for p in starting_xi) if starting_xi else 0
            highest_bench_score = max(p.total_score for p in bench)

            if highest_bench_score > 0 and lowest_starter_score > 0:
                ratio = highest_bench_score / lowest_starter_score
                if ratio > 0.9:
                    bench_contender = max(bench, key=lambda p: p.total_score)
                    starter_at_risk = min(starting_xi, key=lambda p: p.total_score)
                    uncertainties.append(
                        f"{bench_contender.player_name} could replace {starter_at_risk.player_name}"
                    )

        # Check for rotation candidates (context-aware)
        rotation_threshold = 0.5
        if context and context.rotation_likelihood > 0.5:
            rotation_threshold = 0.6  # Higher threshold when rotation is likely

        for player in starting_xi:
            if player.feature_contributions.get("rotation_signal", 1.0) < rotation_threshold:
                uncertainties.append(f"{player.player_name} may be rotated")

        # Check for position uncertainty
        for player in starting_xi:
            if player.feature_contributions.get("position_fit", 1.0) < 0.6:
                uncertainties.append(
                    f"{player.player_name}'s position unclear"
                )

        return uncertainties[:5]  # Max 5 uncertainties

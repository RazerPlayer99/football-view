"""
Evaluation and weight update logic for Predicted XI.

Compares predictions to actual lineups and adjusts weights using
a rule-based optimizer.
"""
import logging
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from collections import defaultdict

from .models import (
    PredictedLineup,
    PredictedPlayer,
    ConfirmedLineup,
    AccuracyRecord,
    WeightConfig,
    WeightScope,
    DEFAULT_WEIGHTS,
)
from .storage import get_prediction_storage

logger = logging.getLogger("predicted_xi.evaluator")

# Learning rate for weight updates
LEARNING_RATE = 0.02  # Small adjustments
MIN_WEIGHT = 0.05  # Minimum weight for any feature
MAX_WEIGHT = 0.50  # Maximum weight for any feature


class PredictionEvaluator:
    """
    Evaluates predictions against actual lineups and updates weights.

    Implements a rule-based optimizer:
    - Features that correlate with correct picks get weight increase
    - Features that correlate with wrong picks get weight decrease
    """

    def __init__(self):
        self.storage = get_prediction_storage()

    def evaluate_prediction(
        self,
        match_id: int,
        team_id: int,
        actual_lineup: ConfirmedLineup,
        prediction: Optional[PredictedLineup] = None,
    ) -> Optional[AccuracyRecord]:
        """
        Evaluate a prediction against the actual lineup.

        Args:
            match_id: The fixture ID
            team_id: The team ID
            actual_lineup: The confirmed lineup
            prediction: Optional prediction (will be loaded if not provided)

        Returns:
            AccuracyRecord with detailed breakdown, or None if no prediction found
        """
        # Load prediction if not provided
        if prediction is None:
            prediction = self.storage.get_prediction(match_id, team_id)
            if prediction is None:
                logger.warning(f"No prediction found for match {match_id}, team {team_id}")
                return None

        # Save confirmed lineup
        self.storage.save_confirmed_lineup(actual_lineup)

        # Supersede the prediction (mark as no longer active)
        self.storage.supersede_prediction(match_id, team_id)

        # Calculate accuracy
        actual_ids = set(actual_lineup.starting_xi)
        predicted_ids = {p.player_id for p in prediction.starting_xi}

        correct_starters = len(actual_ids & predicted_ids)
        correct_positions = self._count_correct_positions(
            prediction.starting_xi, actual_lineup
        )
        formation_correct = (
            prediction.formation == actual_lineup.formation
            if actual_lineup.formation else False
        )

        # Build error breakdown
        error_breakdown = self._build_error_breakdown(
            prediction, actual_lineup, actual_ids, predicted_ids
        )

        # Create accuracy record
        record = AccuracyRecord(
            match_id=match_id,
            team_id=team_id,
            correct_starters=correct_starters,
            correct_positions=correct_positions,
            formation_correct=formation_correct,
            error_breakdown=error_breakdown,
        )

        # Get prediction ID from storage
        stored_prediction = self.storage.get_prediction(match_id, team_id, active_only=False)
        if stored_prediction:
            # We need to query for the ID (simplified - in production you'd return ID from save)
            pass

        # Save accuracy record
        self.storage.save_accuracy_record(record)

        logger.info(
            f"Evaluated prediction for match {match_id}: "
            f"{correct_starters}/11 correct ({record.starter_accuracy:.1%})"
        )

        return record

    def _count_correct_positions(
        self,
        predicted_xi: List[PredictedPlayer],
        actual_lineup: ConfirmedLineup,
    ) -> int:
        """Count how many players were predicted with correct position."""
        # Note: This requires actual lineup to have position info
        # For simplicity, we just count correct player IDs
        # In a full implementation, you'd compare positions too
        actual_ids = set(actual_lineup.starting_xi)
        return sum(1 for p in predicted_xi if p.player_id in actual_ids)

    def _build_error_breakdown(
        self,
        prediction: PredictedLineup,
        actual_lineup: ConfirmedLineup,
        actual_ids: Set[int],
        predicted_ids: Set[int],
    ) -> Dict[str, Any]:
        """Build detailed error breakdown."""
        missed_players = []
        wrong_picks = []

        # Players we predicted but didn't start
        for player in prediction.starting_xi:
            if player.player_id not in actual_ids:
                wrong_picks.append({
                    "player_id": player.player_id,
                    "player_name": player.player_name,
                    "confidence": player.confidence,
                    "top_reasons": player.explanations[:2],
                    "feature_contributions": player.feature_contributions,
                })

        # Players who started but we didn't predict
        bench_ids = {p.player_id: p for p in prediction.bench}
        for actual_id in actual_ids:
            if actual_id not in predicted_ids:
                # Check if they were on our bench
                bench_player = bench_ids.get(actual_id)
                missed_players.append({
                    "player_id": actual_id,
                    "was_on_bench": bench_player is not None,
                    "bench_confidence": bench_player.confidence if bench_player else None,
                })

        # Feature analysis: which features led to correct vs wrong picks
        feature_analysis = self._analyze_feature_performance(
            prediction.starting_xi, actual_ids
        )

        return {
            "missed_players": missed_players,
            "wrong_picks": wrong_picks,
            "feature_analysis": feature_analysis,
        }

    def _analyze_feature_performance(
        self,
        predicted_xi: List[PredictedPlayer],
        actual_ids: Set[int],
    ) -> Dict[str, Dict[str, float]]:
        """Analyze which features correlated with correct/wrong picks."""
        correct_contributions = defaultdict(list)
        wrong_contributions = defaultdict(list)

        for player in predicted_xi:
            is_correct = player.player_id in actual_ids
            target = correct_contributions if is_correct else wrong_contributions

            for feature, contribution in player.feature_contributions.items():
                target[feature].append(contribution)

        # Calculate averages
        analysis = {}
        all_features = set(correct_contributions.keys()) | set(wrong_contributions.keys())

        for feature in all_features:
            correct_vals = correct_contributions.get(feature, [])
            wrong_vals = wrong_contributions.get(feature, [])

            analysis[feature] = {
                "correct_avg": sum(correct_vals) / len(correct_vals) if correct_vals else 0,
                "wrong_avg": sum(wrong_vals) / len(wrong_vals) if wrong_vals else 0,
                "correct_count": len(correct_vals),
                "wrong_count": len(wrong_vals),
            }

        return analysis

    def update_weights(
        self,
        accuracy_record: AccuracyRecord,
        prediction: PredictedLineup,
        scope: WeightScope = WeightScope.GLOBAL,
        scope_id: Optional[int] = None,
    ) -> WeightConfig:
        """
        Update weights based on prediction accuracy.

        Uses a simple rule-based optimizer:
        - If a feature's contribution was high for correct picks, increase weight
        - If a feature's contribution was high for wrong picks, decrease weight

        Args:
            accuracy_record: The accuracy record with feature analysis
            prediction: The original prediction
            scope: Which weight scope to update (global, team, coach)
            scope_id: The team_id or coach_id for non-global scopes

        Returns:
            Updated WeightConfig
        """
        # Get current weights for this scope
        current_config = self.storage.get_weight_config(scope, scope_id)

        if current_config is None:
            # Create new config based on defaults
            current_weights = DEFAULT_WEIGHTS.copy()
            current_version = "1"
        else:
            current_weights = current_config.weights.copy()
            current_version = current_config.version

        # Get feature analysis
        feature_analysis = accuracy_record.error_breakdown.get("feature_analysis", {})

        # Update each weight
        for feature, analysis in feature_analysis.items():
            if feature not in current_weights:
                continue

            correct_avg = analysis.get("correct_avg", 0)
            wrong_avg = analysis.get("wrong_avg", 0)
            correct_count = analysis.get("correct_count", 0)
            wrong_count = analysis.get("wrong_count", 0)

            # Calculate adjustment
            adjustment = self._calculate_weight_adjustment(
                correct_avg, wrong_avg, correct_count, wrong_count
            )

            # Apply adjustment
            new_weight = current_weights[feature] * (1 + adjustment)

            # Clamp to bounds
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            current_weights[feature] = new_weight

        # Normalize weights to sum to 1.0
        total = sum(current_weights.values())
        if total > 0:
            current_weights = {k: v / total for k, v in current_weights.items()}

        # Increment version
        new_version = str(int(current_version) + 1)

        # Create updated config
        updated_config = WeightConfig(
            scope=scope,
            scope_id=scope_id,
            weights=current_weights,
            version=new_version,
            updated_at=datetime.utcnow().isoformat() + "Z",
        )

        # Save
        self.storage.save_weights(updated_config)

        logger.info(
            f"Updated {scope.value} weights (v{new_version}): "
            f"{', '.join(f'{k}={v:.3f}' for k, v in current_weights.items())}"
        )

        return updated_config

    def _calculate_weight_adjustment(
        self,
        correct_avg: float,
        wrong_avg: float,
        correct_count: int,
        wrong_count: int,
    ) -> float:
        """
        Calculate weight adjustment factor.

        Returns a value between -LEARNING_RATE and +LEARNING_RATE.
        """
        if correct_count + wrong_count == 0:
            return 0.0

        # Confidence in the adjustment based on sample size
        sample_confidence = min(1.0, (correct_count + wrong_count) / 5)

        # If feature contributed more to correct picks, increase weight
        if correct_avg > wrong_avg:
            # Positive adjustment
            diff = (correct_avg - wrong_avg) / max(correct_avg, 0.01)
            return LEARNING_RATE * diff * sample_confidence

        elif wrong_avg > correct_avg:
            # Negative adjustment
            diff = (wrong_avg - correct_avg) / max(wrong_avg, 0.01)
            return -LEARNING_RATE * diff * sample_confidence

        return 0.0

    def evaluate_and_update(
        self,
        match_id: int,
        team_id: int,
        actual_lineup: ConfirmedLineup,
        coach_id: Optional[int] = None,
        update_global: bool = True,
        update_team: bool = True,
        update_coach: bool = True,
    ) -> Tuple[Optional[AccuracyRecord], List[WeightConfig]]:
        """
        Convenience method to evaluate prediction and update all relevant weights.

        Args:
            match_id: The fixture ID
            team_id: The team ID
            actual_lineup: The confirmed lineup
            coach_id: Optional coach ID
            update_global: Whether to update global weights
            update_team: Whether to update team-specific weights
            update_coach: Whether to update coach-specific weights

        Returns:
            Tuple of (AccuracyRecord, list of updated WeightConfigs)
        """
        # Load prediction
        prediction = self.storage.get_prediction(match_id, team_id)
        if prediction is None:
            return None, []

        # Evaluate
        record = self.evaluate_prediction(match_id, team_id, actual_lineup, prediction)
        if record is None:
            return None, []

        # Update weights at various scopes
        updated_configs = []

        if update_global:
            config = self.update_weights(record, prediction, WeightScope.GLOBAL)
            updated_configs.append(config)

        if update_team:
            config = self.update_weights(record, prediction, WeightScope.TEAM, team_id)
            updated_configs.append(config)

        if update_coach and coach_id:
            config = self.update_weights(record, prediction, WeightScope.COACH, coach_id)
            updated_configs.append(config)

        return record, updated_configs


# Singleton instance
_evaluator: Optional[PredictionEvaluator] = None


def get_prediction_evaluator() -> PredictionEvaluator:
    """Get the prediction evaluator instance."""
    global _evaluator
    if _evaluator is None:
        _evaluator = PredictionEvaluator()
    return _evaluator

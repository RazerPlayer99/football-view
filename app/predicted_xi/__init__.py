"""
Predicted XI - Explainable lineup prediction engine.

This module provides lineup predictions with:
- Weighted feature scoring
- Self-learning weight adjustments
- Per-player explanations
- Accuracy tracking
"""

from .models import (
    PlayerFeatures,
    PredictedPlayer,
    PredictedLineup,
    FormationPrediction,
    WeightConfig,
    WeightScope,
    AccuracyRecord,
    ConfirmedLineup,
    MatchContext,
    CompetitionType,
    SeasonAccuracySummary,
    DEFAULT_WEIGHTS,
    MODEL_VERSION,
)
from .storage import (
    PredictionStorage,
    get_prediction_storage,
)
from .features import (
    extract_player_features,
    extract_formation_patterns,
    get_formation_positions,
)
from .predictor import (
    PredictionEngine,
)
from .evaluator import (
    PredictionEvaluator,
    get_prediction_evaluator,
)
from .provider import (
    PredictedXIProvider,
    get_predicted_xi_provider,
)

__all__ = [
    # Models
    "PlayerFeatures",
    "PredictedPlayer",
    "PredictedLineup",
    "FormationPrediction",
    "WeightConfig",
    "WeightScope",
    "AccuracyRecord",
    "ConfirmedLineup",
    "MatchContext",
    "CompetitionType",
    "SeasonAccuracySummary",
    "DEFAULT_WEIGHTS",
    "MODEL_VERSION",
    # Storage
    "PredictionStorage",
    "get_prediction_storage",
    # Features
    "extract_player_features",
    "extract_formation_patterns",
    "get_formation_positions",
    # Predictor
    "PredictionEngine",
    # Evaluator
    "PredictionEvaluator",
    "get_prediction_evaluator",
    # Provider
    "PredictedXIProvider",
    "get_predicted_xi_provider",
]

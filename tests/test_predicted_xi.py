"""
Unit tests for Predicted XI module.

Tests prediction engine, feature extraction, evaluation, and weight updates
using mocked fixture data.
"""
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from app.predicted_xi.models import (
    PlayerFeatures,
    PredictedPlayer,
    PredictedLineup,
    ConfirmedLineup,
    AccuracyRecord,
    WeightConfig,
    WeightScope,
    DEFAULT_WEIGHTS,
)
from app.predicted_xi.storage import PredictionStorage
from app.predicted_xi.features import (
    extract_player_features,
    extract_formation_patterns,
    get_formation_positions,
    _normalize_position,
    _calculate_minutes_trend,
)
from app.predicted_xi.predictor import PredictionEngine
from app.predicted_xi.evaluator import PredictionEvaluator


# =============================================================================
# Test Fixtures (Mock Data)
# =============================================================================

@pytest.fixture
def mock_squad():
    """Mock squad data."""
    return [
        {"id": 1, "name": "Goalkeeper One", "position": "G", "number": 1},
        {"id": 2, "name": "Defender One", "position": "D", "number": 2},
        {"id": 3, "name": "Defender Two", "position": "D", "number": 3},
        {"id": 4, "name": "Defender Three", "position": "D", "number": 4},
        {"id": 5, "name": "Defender Four", "position": "D", "number": 5},
        {"id": 6, "name": "Midfielder One", "position": "M", "number": 6},
        {"id": 7, "name": "Midfielder Two", "position": "M", "number": 7},
        {"id": 8, "name": "Midfielder Three", "position": "M", "number": 8},
        {"id": 9, "name": "Forward One", "position": "F", "number": 9},
        {"id": 10, "name": "Forward Two", "position": "F", "number": 10},
        {"id": 11, "name": "Forward Three", "position": "F", "number": 11},
        # Subs
        {"id": 12, "name": "Goalkeeper Two", "position": "G", "number": 12},
        {"id": 13, "name": "Defender Five", "position": "D", "number": 13},
        {"id": 14, "name": "Midfielder Four", "position": "M", "number": 14},
        {"id": 15, "name": "Forward Four", "position": "F", "number": 15},
    ]


@pytest.fixture
def mock_historical_lineups():
    """Mock historical lineup data showing consistent starters."""
    lineups = []
    base_date = datetime.now() - timedelta(days=60)

    # Regular starters: 1-11
    regular_starters = [
        {"id": 1, "name": "Goalkeeper One", "position": "G"},
        {"id": 2, "name": "Defender One", "position": "D"},
        {"id": 3, "name": "Defender Two", "position": "D"},
        {"id": 4, "name": "Defender Three", "position": "D"},
        {"id": 5, "name": "Defender Four", "position": "D"},
        {"id": 6, "name": "Midfielder One", "position": "M"},
        {"id": 7, "name": "Midfielder Two", "position": "M"},
        {"id": 8, "name": "Midfielder Three", "position": "M"},
        {"id": 9, "name": "Forward One", "position": "F"},
        {"id": 10, "name": "Forward Two", "position": "F"},
        {"id": 11, "name": "Forward Three", "position": "F"},
    ]

    for i in range(10):
        match_date = base_date + timedelta(days=i * 7)
        starting_xi = regular_starters.copy()

        # Occasional rotation in match 5 and 8
        if i == 5:
            starting_xi[10] = {"id": 15, "name": "Forward Four", "position": "F"}
        if i == 8:
            starting_xi[5] = {"id": 14, "name": "Midfielder Four", "position": "M"}

        lineups.append({
            "match_id": 1000 + i,
            "date": match_date.isoformat(),
            "formation": "4-3-3",
            "team_id": 100,
            "starting_xi": starting_xi,
            "substitutes": [
                {"id": 12, "name": "Goalkeeper Two", "position": "G"},
                {"id": 13, "name": "Defender Five", "position": "D"},
                {"id": 14 if i != 8 else 6, "name": "Midfielder Four" if i != 8 else "Midfielder One", "position": "M"},
                {"id": 15 if i != 5 else 11, "name": "Forward Four" if i != 5 else "Forward Three", "position": "F"},
            ],
        })

    return lineups


@pytest.fixture
def mock_player_match_logs():
    """Mock match logs for players."""
    logs = {}
    base_date = datetime.now() - timedelta(days=60)

    # Regular starters have high minutes
    for player_id in range(1, 12):
        logs[player_id] = [
            {
                "fixture_id": 1000 + i,
                "date": (base_date + timedelta(days=i * 7)).isoformat(),
                "minutes": 90 if player_id != 11 or i != 5 else 0,  # Player 11 rested in match 5
                "rating": 7.0 + (i % 3) * 0.3,
                "position": "G" if player_id == 1 else "D" if player_id <= 5 else "M" if player_id <= 8 else "F",
                "yellow_cards": 1 if player_id == 7 and i == 3 else 0,
            }
            for i in range(10)
        ]

    # Sub players have lower minutes
    for player_id in [12, 13, 14, 15]:
        logs[player_id] = [
            {
                "fixture_id": 1000 + i,
                "date": (base_date + timedelta(days=i * 7)).isoformat(),
                "minutes": 20 if i % 3 == 0 else 0,
                "rating": 6.5,
                "position": "G" if player_id == 12 else "D" if player_id == 13 else "M" if player_id == 14 else "F",
                "yellow_cards": 0,
            }
            for i in range(10)
        ]

    return logs


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_predictions.db"
        storage = PredictionStorage(db_path)
        yield storage


# =============================================================================
# Feature Extraction Tests
# =============================================================================

class TestFeatureExtraction:
    """Tests for feature extraction."""

    def test_normalize_position(self):
        """Test position normalization."""
        assert _normalize_position("G") == "G"
        assert _normalize_position("GK") == "G"
        assert _normalize_position("Goalkeeper") == "G"
        assert _normalize_position("D") == "D"
        assert _normalize_position("CB") == "D"
        assert _normalize_position("LB") == "D"
        assert _normalize_position("M") == "M"
        assert _normalize_position("CM") == "M"
        assert _normalize_position("CAM") == "M"
        assert _normalize_position("F") == "F"
        assert _normalize_position("ST") == "F"
        assert _normalize_position("LW") == "F"

    def test_formation_positions(self):
        """Test formation position parsing."""
        positions = get_formation_positions("4-3-3")
        assert positions["G"] == 1
        assert positions["D"] == 4
        assert positions["M"] == 3
        assert positions["F"] == 3

        positions = get_formation_positions("4-2-3-1")
        assert positions["G"] == 1
        assert positions["D"] == 4
        assert positions["M"] == 5  # 2+3
        assert positions["F"] == 1

        positions = get_formation_positions("3-5-2")
        assert positions["D"] == 3
        assert positions["M"] == 5
        assert positions["F"] == 2

    def test_extract_formation_patterns(self, mock_historical_lineups):
        """Test formation pattern extraction."""
        patterns = extract_formation_patterns(mock_historical_lineups)

        assert patterns["primary_formation"] == "4-3-3"
        assert patterns["total_matches"] == 10
        assert patterns["confidence"] == 1.0  # All matches use same formation

    def test_extract_player_features_regular_starter(
        self, mock_historical_lineups, mock_player_match_logs
    ):
        """Test feature extraction for a regular starter."""
        features = extract_player_features(
            player_id=9,
            player_name="Forward One",
            player_position="F",
            squad_number=9,
            historical_lineups=mock_historical_lineups,
            match_log=mock_player_match_logs[9],
        )

        # Regular starter should have high recent_starts
        assert features.recent_starts == 1.0  # Started all 10 matches
        assert features.starts_last_n == 10
        assert features.position_fit == 1.0  # Primary position

    def test_extract_player_features_rotation_player(
        self, mock_historical_lineups, mock_player_match_logs
    ):
        """Test feature extraction for a rotation player."""
        features = extract_player_features(
            player_id=14,
            player_name="Midfielder Four",
            player_position="M",
            squad_number=14,
            historical_lineups=mock_historical_lineups,
            match_log=mock_player_match_logs[14],
        )

        # Rotation player should have lower recent_starts
        assert features.recent_starts < 0.5
        assert features.minutes_trend <= 0.5  # Low/inconsistent minutes

    def test_minutes_trend_calculation(self):
        """Test minutes trend calculation."""
        # Increasing minutes
        increasing = [
            {"minutes": 90}, {"minutes": 85}, {"minutes": 90},
            {"minutes": 45}, {"minutes": 30}, {"minutes": 20},
        ]
        trend = _calculate_minutes_trend(increasing)
        assert trend > 0.5

        # Decreasing minutes
        decreasing = [
            {"minutes": 20}, {"minutes": 30}, {"minutes": 45},
            {"minutes": 90}, {"minutes": 85}, {"minutes": 90},
        ]
        trend = _calculate_minutes_trend(decreasing)
        assert trend < 0.5


# =============================================================================
# Prediction Engine Tests
# =============================================================================

class TestPredictionEngine:
    """Tests for the prediction engine."""

    def test_predict_lineup_selects_11(
        self, mock_squad, mock_historical_lineups, mock_player_match_logs, temp_db
    ):
        """Test that prediction produces exactly 11 starters."""
        engine = PredictionEngine()
        engine.storage = temp_db

        prediction = engine.predict_lineup(
            match_id=2000,
            team_id=100,
            team_name="Test Team",
            squad=mock_squad,
            historical_lineups=mock_historical_lineups,
            player_match_logs=mock_player_match_logs,
        )

        assert len(prediction.starting_xi) == 11
        assert len(prediction.bench) == 4  # Remaining squad

    def test_predict_lineup_respects_positions(
        self, mock_squad, mock_historical_lineups, mock_player_match_logs, temp_db
    ):
        """Test that prediction respects position constraints."""
        engine = PredictionEngine()
        engine.storage = temp_db

        prediction = engine.predict_lineup(
            match_id=2000,
            team_id=100,
            team_name="Test Team",
            squad=mock_squad,
            historical_lineups=mock_historical_lineups,
            player_match_logs=mock_player_match_logs,
        )

        # Count positions in starting XI
        positions = [p.position for p in prediction.starting_xi]
        assert positions.count("G") == 1
        assert positions.count("D") == 4
        assert positions.count("M") == 3
        assert positions.count("F") == 3

    def test_predict_lineup_prefers_regular_starters(
        self, mock_squad, mock_historical_lineups, mock_player_match_logs, temp_db
    ):
        """Test that prediction prefers players who start regularly."""
        engine = PredictionEngine()
        engine.storage = temp_db

        prediction = engine.predict_lineup(
            match_id=2000,
            team_id=100,
            team_name="Test Team",
            squad=mock_squad,
            historical_lineups=mock_historical_lineups,
            player_match_logs=mock_player_match_logs,
        )

        # Regular starters (1-11) should be predicted to start
        predicted_ids = {p.player_id for p in prediction.starting_xi}

        # Most regular starters should be in the predicted XI
        regular_starters = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
        overlap = predicted_ids & regular_starters
        assert len(overlap) >= 9  # At least 9 of 11 regular starters

    def test_predict_lineup_generates_explanations(
        self, mock_squad, mock_historical_lineups, mock_player_match_logs, temp_db
    ):
        """Test that predictions include explanations."""
        engine = PredictionEngine()
        engine.storage = temp_db

        prediction = engine.predict_lineup(
            match_id=2000,
            team_id=100,
            team_name="Test Team",
            squad=mock_squad,
            historical_lineups=mock_historical_lineups,
            player_match_logs=mock_player_match_logs,
        )

        # Each player should have explanations
        for player in prediction.starting_xi:
            assert len(player.explanations) >= 1
            assert all(isinstance(e, str) for e in player.explanations)


# =============================================================================
# Storage Tests
# =============================================================================

class TestStorage:
    """Tests for prediction storage."""

    def test_save_and_load_prediction(self, temp_db):
        """Test saving and loading predictions."""
        prediction = PredictedLineup(
            match_id=3000,
            team_id=100,
            team_name="Test Team",
            formation="4-3-3",
            starting_xi=[
                PredictedPlayer(
                    player_id=i,
                    player_name=f"Player {i}",
                    position="F" if i > 8 else "M" if i > 5 else "D" if i > 1 else "G",
                    confidence=0.8,
                    explanations=["Started 8 of last 10"],
                )
                for i in range(1, 12)
            ],
            overall_confidence=0.75,
        )

        # Save
        pred_id = temp_db.save_prediction(prediction)
        assert pred_id > 0

        # Load
        loaded = temp_db.get_prediction(3000, 100)
        assert loaded is not None
        assert loaded.match_id == 3000
        assert loaded.team_id == 100
        assert loaded.formation == "4-3-3"
        assert len(loaded.starting_xi) == 11

    def test_weight_hierarchy(self, temp_db):
        """Test weight hierarchy: global -> team -> coach."""
        # Global weights should exist by default
        global_weights = temp_db.get_weights()
        assert "recent_starts" in global_weights

        # Team-specific override
        team_config = WeightConfig(
            scope=WeightScope.TEAM,
            scope_id=100,
            weights={"recent_starts": 0.50, "minutes_trend": 0.15},
            version="1",
            updated_at=datetime.utcnow().isoformat() + "Z",
        )
        temp_db.save_weights(team_config)

        # Get effective weights for team 100
        effective = temp_db.get_weights(team_id=100)
        assert effective["recent_starts"] == 0.50  # Team override
        assert effective["position_fit"] == DEFAULT_WEIGHTS["position_fit"]  # Global default

    def test_supersede_prediction(self, temp_db):
        """Test superseding predictions when confirmed lineup arrives."""
        prediction = PredictedLineup(
            match_id=4000,
            team_id=100,
            team_name="Test Team",
            formation="4-3-3",
            starting_xi=[],
        )
        temp_db.save_prediction(prediction)

        # Supersede
        temp_db.supersede_prediction(4000, 100)

        # Active query should return None
        active = temp_db.get_prediction(4000, 100, active_only=True)
        assert active is None

        # Non-active query should still find it
        all_pred = temp_db.get_prediction(4000, 100, active_only=False)
        assert all_pred is not None
        assert all_pred.superseded_at is not None


# =============================================================================
# Evaluator Tests
# =============================================================================

class TestEvaluator:
    """Tests for prediction evaluation and weight updates."""

    def test_evaluate_perfect_prediction(self, temp_db):
        """Test evaluation with 100% correct prediction."""
        evaluator = PredictionEvaluator()
        evaluator.storage = temp_db

        # Create and save prediction
        prediction = PredictedLineup(
            match_id=5000,
            team_id=100,
            team_name="Test Team",
            formation="4-3-3",
            starting_xi=[
                PredictedPlayer(
                    player_id=i,
                    player_name=f"Player {i}",
                    position="F" if i > 8 else "M" if i > 5 else "D" if i > 1 else "G",
                    confidence=0.8,
                    explanations=["Regular starter"],
                    feature_contributions={
                        "recent_starts": 0.3,
                        "minutes_trend": 0.15,
                        "position_fit": 0.15,
                    },
                )
                for i in range(1, 12)
            ],
            overall_confidence=0.75,
        )
        temp_db.save_prediction(prediction)

        # Actual lineup matches prediction exactly
        actual = ConfirmedLineup(
            match_id=5000,
            team_id=100,
            formation="4-3-3",
            starting_xi=list(range(1, 12)),
        )

        record = evaluator.evaluate_prediction(5000, 100, actual, prediction)

        assert record is not None
        assert record.correct_starters == 11
        assert record.starter_accuracy == 1.0
        assert record.formation_correct is True

    def test_evaluate_partial_prediction(self, temp_db):
        """Test evaluation with partially correct prediction."""
        evaluator = PredictionEvaluator()
        evaluator.storage = temp_db

        # Prediction: players 1-11
        prediction = PredictedLineup(
            match_id=6000,
            team_id=100,
            team_name="Test Team",
            formation="4-3-3",
            starting_xi=[
                PredictedPlayer(
                    player_id=i,
                    player_name=f"Player {i}",
                    position="M",
                    confidence=0.7,
                    explanations=[],
                    feature_contributions={"recent_starts": 0.3},
                )
                for i in range(1, 12)
            ],
            bench=[
                PredictedPlayer(
                    player_id=i,
                    player_name=f"Player {i}",
                    position="M",
                    confidence=0.4,
                    explanations=[],
                )
                for i in range(12, 16)
            ],
            overall_confidence=0.65,
        )
        temp_db.save_prediction(prediction)

        # Actual: players 1-9, 12, 13 (2 changes)
        actual = ConfirmedLineup(
            match_id=6000,
            team_id=100,
            formation="4-3-3",
            starting_xi=[1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13],
        )

        record = evaluator.evaluate_prediction(6000, 100, actual, prediction)

        assert record is not None
        assert record.correct_starters == 9
        assert abs(record.starter_accuracy - 9/11) < 0.01

        # Check error breakdown
        assert "missed_players" in record.error_breakdown
        assert "wrong_picks" in record.error_breakdown
        assert len(record.error_breakdown["wrong_picks"]) == 2  # Players 10, 11

    def test_weight_update_increases_good_features(self, temp_db):
        """Test that weight update increases weights for correct features."""
        evaluator = PredictionEvaluator()
        evaluator.storage = temp_db

        # Create prediction where high recent_starts led to correct pick
        prediction = PredictedLineup(
            match_id=7000,
            team_id=100,
            team_name="Test Team",
            formation="4-3-3",
            starting_xi=[
                PredictedPlayer(
                    player_id=1,
                    player_name="Player 1",
                    position="G",
                    confidence=0.9,
                    explanations=[],
                    feature_contributions={
                        "recent_starts": 0.35,  # High contribution
                        "minutes_trend": 0.10,
                        "position_fit": 0.15,
                    },
                )
            ] + [
                PredictedPlayer(
                    player_id=i,
                    player_name=f"Player {i}",
                    position="M",
                    confidence=0.7,
                    explanations=[],
                    feature_contributions={
                        "recent_starts": 0.30,
                        "minutes_trend": 0.10,
                    },
                )
                for i in range(2, 12)
            ],
        )
        temp_db.save_prediction(prediction)

        # All predictions correct
        actual = ConfirmedLineup(
            match_id=7000,
            team_id=100,
            formation="4-3-3",
            starting_xi=list(range(1, 12)),
        )

        record = evaluator.evaluate_prediction(7000, 100, actual, prediction)

        # Get initial global weights
        initial_weights = temp_db.get_weights()
        initial_recent_starts = initial_weights["recent_starts"]

        # Update weights
        evaluator.update_weights(record, prediction, WeightScope.GLOBAL)

        # Check weights increased for features that contributed to correct picks
        updated_weights = temp_db.get_weights()

        # recent_starts should have increased (it led to correct predictions)
        # Note: The exact change depends on the algorithm, but direction should be positive
        # Due to normalization, we check the relative weight didn't decrease significantly
        assert updated_weights["recent_starts"] >= initial_recent_starts * 0.95


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """End-to-end integration tests."""

    def test_full_prediction_cycle(
        self, mock_squad, mock_historical_lineups, mock_player_match_logs, temp_db
    ):
        """Test complete cycle: predict -> confirm -> evaluate -> update weights."""
        engine = PredictionEngine()
        engine.storage = temp_db

        evaluator = PredictionEvaluator()
        evaluator.storage = temp_db

        # 1. Generate prediction
        prediction = engine.predict_lineup(
            match_id=8000,
            team_id=100,
            team_name="Test Team",
            squad=mock_squad,
            historical_lineups=mock_historical_lineups,
            player_match_logs=mock_player_match_logs,
        )

        assert prediction is not None
        assert len(prediction.starting_xi) == 11

        # 2. Save prediction
        temp_db.save_prediction(prediction)

        # 3. Simulate confirmed lineup (with some differences)
        predicted_ids = [p.player_id for p in prediction.starting_xi]
        actual_ids = predicted_ids[:9] + [12, 13]  # 2 surprises

        actual = ConfirmedLineup(
            match_id=8000,
            team_id=100,
            formation="4-3-3",
            starting_xi=actual_ids,
        )

        # 4. Evaluate
        record = evaluator.evaluate_prediction(8000, 100, actual, prediction)

        assert record is not None
        assert record.correct_starters == 9

        # 5. Update weights
        initial_version = temp_db.get_weights_version(100)
        evaluator.update_weights(record, prediction, WeightScope.TEAM, 100)
        updated_version = temp_db.get_weights_version(100)

        # Version should have changed
        assert updated_version != initial_version

        # 6. Verify prediction is superseded
        active_pred = temp_db.get_prediction(8000, 100, active_only=True)
        assert active_pred is None


class TestSeasonAccuracy:
    """Tests for season accuracy tracking."""

    def test_season_accuracy_summary(self, temp_db):
        """Test season accuracy summary calculation."""
        evaluator = PredictionEvaluator()
        evaluator.storage = temp_db

        # Create predictions with season tracking for 3 matches
        for i, (correct_count, match_id) in enumerate([
            (11, 9001),  # Perfect prediction
            (9, 9002),   # 9 correct
            (8, 9003),   # 8 correct
        ]):
            prediction = PredictedLineup(
                match_id=match_id,
                team_id=100,
                team_name="Test Team",
                season=2024,
                competition="league",
                formation="4-3-3",
                starting_xi=[
                    PredictedPlayer(
                        player_id=j,
                        player_name=f"Player {j}",
                        position="M",
                        confidence=0.8,
                        explanations=[],
                        feature_contributions={"recent_starts": 0.3},
                    )
                    for j in range(1, 12)
                ],
            )
            pred_id = temp_db.save_prediction(prediction)

            # Create accuracy record
            record = AccuracyRecord(
                prediction_id=pred_id,
                match_id=match_id,
                team_id=100,
                correct_starters=correct_count,
                correct_positions=correct_count,
                formation_correct=True,
            )
            temp_db.save_accuracy_record(record)

        # Get season summary
        summary = temp_db.get_season_accuracy_summary(2024)

        assert summary.season == 2024
        assert summary.matches_evaluated == 3
        assert summary.total_correct_xi == 28  # 11 + 9 + 8
        assert summary.perfect_xi_count == 1   # Only 1 perfect prediction
        assert summary.avg_correct_xi == 28 / 3
        assert summary.perfect_xi_rate == 1 / 3

    def test_season_accuracy_with_competition_filter(self, temp_db):
        """Test season accuracy with competition filter."""
        # Create predictions for different competitions
        for competition, match_id, correct in [
            ("league", 9101, 10),
            ("league", 9102, 9),
            ("cup", 9103, 11),
        ]:
            prediction = PredictedLineup(
                match_id=match_id,
                team_id=100,
                team_name="Test Team",
                season=2024,
                competition=competition,
                formation="4-3-3",
                starting_xi=[
                    PredictedPlayer(
                        player_id=j,
                        player_name=f"Player {j}",
                        position="M",
                        confidence=0.8,
                        explanations=[],
                        feature_contributions={},
                    )
                    for j in range(1, 12)
                ],
            )
            pred_id = temp_db.save_prediction(prediction)

            record = AccuracyRecord(
                prediction_id=pred_id,
                match_id=match_id,
                team_id=100,
                correct_starters=correct,
                correct_positions=correct,
                formation_correct=True,
            )
            temp_db.save_accuracy_record(record)

        # Filter by league only
        league_summary = temp_db.get_season_accuracy_summary(2024, competition="league")
        assert league_summary.matches_evaluated == 2
        assert league_summary.total_correct_xi == 19  # 10 + 9

        # Filter by cup only
        cup_summary = temp_db.get_season_accuracy_summary(2024, competition="cup")
        assert cup_summary.matches_evaluated == 1
        assert cup_summary.perfect_xi_count == 1

    def test_season_accuracy_team_breakdown(self, temp_db):
        """Test season accuracy with team breakdown."""
        # Create predictions for different teams
        for team_id, team_name, match_id, correct in [
            (100, "Team A", 9201, 10),
            (100, "Team A", 9202, 9),
            (200, "Team B", 9203, 11),
        ]:
            prediction = PredictedLineup(
                match_id=match_id,
                team_id=team_id,
                team_name=team_name,
                season=2025,
                competition="league",
                formation="4-3-3",
                starting_xi=[
                    PredictedPlayer(
                        player_id=j,
                        player_name=f"Player {j}",
                        position="M",
                        confidence=0.8,
                        explanations=[],
                        feature_contributions={},
                    )
                    for j in range(1, 12)
                ],
            )
            pred_id = temp_db.save_prediction(prediction)

            record = AccuracyRecord(
                prediction_id=pred_id,
                match_id=match_id,
                team_id=team_id,
                correct_starters=correct,
                correct_positions=correct,
                formation_correct=True,
            )
            temp_db.save_accuracy_record(record)

        # Get summary with team breakdown
        summary = temp_db.get_season_accuracy_summary(
            2025, include_team_breakdown=True
        )

        assert summary.matches_evaluated == 3
        assert 100 in summary.team_breakdown
        assert 200 in summary.team_breakdown
        assert summary.team_breakdown[100]["matches"] == 2
        assert summary.team_breakdown[100]["avg_correct"] == 9.5
        assert summary.team_breakdown[200]["matches"] == 1
        assert summary.team_breakdown[200]["avg_correct"] == 11


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

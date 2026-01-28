"""
SQLite storage layer for Predicted XI engine.

Handles persistence of predictions, confirmed lineups, accuracy records, and weights.
"""
import sqlite3
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager

from .models import (
    PredictedLineup,
    PredictedPlayer,
    ConfirmedLineup,
    AccuracyRecord,
    WeightConfig,
    WeightScope,
    SeasonAccuracySummary,
    DEFAULT_WEIGHTS,
)

logger = logging.getLogger("predicted_xi.storage")

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "predicted_xi.db"


SCHEMA = """
-- Predictions (first-class records)
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    team_name TEXT,
    season INTEGER,
    competition TEXT,
    generated_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    weights_version TEXT NOT NULL,
    formation TEXT,
    formation_confidence REAL,
    predicted_xi TEXT NOT NULL,
    bench TEXT,
    overall_confidence REAL,
    key_uncertainties TEXT,
    based_on_matches INTEGER,
    superseded_at TEXT,
    UNIQUE(match_id, team_id, generated_at)
);

-- Confirmed lineups (for comparison)
CREATE TABLE IF NOT EXISTS confirmed_lineups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    formation TEXT,
    starting_xi TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(match_id, team_id)
);

-- Accuracy records
CREATE TABLE IF NOT EXISTS accuracy_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER REFERENCES predictions(id),
    match_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    correct_starters INTEGER,
    correct_positions INTEGER,
    formation_correct INTEGER,
    error_breakdown TEXT,
    evaluated_at TEXT NOT NULL
);

-- Weight configurations (3-tier hierarchy)
CREATE TABLE IF NOT EXISTS weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    scope_id INTEGER,
    weights TEXT NOT NULL,
    version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope, scope_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id, team_id);
CREATE INDEX IF NOT EXISTS idx_predictions_active ON predictions(match_id, team_id, superseded_at);
CREATE INDEX IF NOT EXISTS idx_accuracy_team ON accuracy_records(team_id);
CREATE INDEX IF NOT EXISTS idx_accuracy_match ON accuracy_records(match_id);
CREATE INDEX IF NOT EXISTS idx_weights_scope ON weights(scope, scope_id);
CREATE INDEX IF NOT EXISTS idx_confirmed_match ON confirmed_lineups(match_id, team_id);
"""


class PredictionStorage:
    """
    SQLite-based storage for the Predicted XI system.

    Handles all database operations including:
    - Saving/loading predictions
    - Recording confirmed lineups
    - Tracking accuracy
    - Managing weight configurations
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database with schema."""
        with self._get_connection() as conn:
            conn.executescript(SCHEMA)
            # Ensure global weights exist
            self._ensure_global_weights(conn)
            # Run migrations for existing databases
            self._run_migrations(conn)
            conn.commit()

    def _run_migrations(self, conn: sqlite3.Connection):
        """Run any pending migrations."""
        # Check if season column exists in predictions
        cursor = conn.execute("PRAGMA table_info(predictions)")
        columns = [row[1] for row in cursor.fetchall()]

        if "season" not in columns:
            try:
                conn.execute("ALTER TABLE predictions ADD COLUMN season INTEGER")
                conn.execute("ALTER TABLE predictions ADD COLUMN competition TEXT")
                logger.info("Migrated predictions table: added season and competition columns")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Create index on season columns (safe to run after migration)
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictions_season ON predictions(season, competition)"
            )
        except sqlite3.OperationalError:
            pass  # Index creation may fail if columns don't exist yet

    @contextmanager
    def _get_connection(self):
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_global_weights(self, conn: sqlite3.Connection):
        """Ensure global default weights exist."""
        cursor = conn.execute(
            "SELECT id FROM weights WHERE scope = 'global' AND scope_id IS NULL"
        )
        if cursor.fetchone() is None:
            now = datetime.utcnow().isoformat() + "Z"
            conn.execute(
                """
                INSERT INTO weights (scope, scope_id, weights, version, updated_at)
                VALUES ('global', NULL, ?, '1', ?)
                """,
                (json.dumps(DEFAULT_WEIGHTS), now),
            )
            logger.info("Initialized global default weights")

    # =========================================================================
    # Predictions
    # =========================================================================

    def save_prediction(self, prediction: PredictedLineup) -> int:
        """
        Save a prediction to the database.

        Returns the prediction ID.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO predictions (
                    match_id, team_id, team_name, season, competition,
                    generated_at, model_version, weights_version, formation,
                    formation_confidence, predicted_xi, bench, overall_confidence,
                    key_uncertainties, based_on_matches, superseded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction.match_id,
                    prediction.team_id,
                    prediction.team_name,
                    prediction.season,
                    prediction.competition,
                    prediction.generated_at,
                    prediction.model_version,
                    prediction.weights_version,
                    prediction.formation,
                    prediction.formation_confidence,
                    json.dumps([p.to_dict() for p in prediction.starting_xi]),
                    json.dumps([p.to_dict() for p in prediction.bench]),
                    prediction.overall_confidence,
                    json.dumps(prediction.key_uncertainties),
                    prediction.based_on_matches,
                    prediction.superseded_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_prediction(
        self, match_id: int, team_id: int, active_only: bool = True
    ) -> Optional[PredictedLineup]:
        """
        Get the latest prediction for a match/team.

        Args:
            match_id: The fixture ID
            team_id: The team ID
            active_only: If True, only return non-superseded predictions
        """
        with self._get_connection() as conn:
            if active_only:
                cursor = conn.execute(
                    """
                    SELECT * FROM predictions
                    WHERE match_id = ? AND team_id = ? AND superseded_at IS NULL
                    ORDER BY generated_at DESC
                    LIMIT 1
                    """,
                    (match_id, team_id),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM predictions
                    WHERE match_id = ? AND team_id = ?
                    ORDER BY generated_at DESC
                    LIMIT 1
                    """,
                    (match_id, team_id),
                )

            row = cursor.fetchone()
            if row is None:
                return None

            return self._row_to_prediction(row)

    def supersede_prediction(self, match_id: int, team_id: int):
        """Mark all predictions for a match/team as superseded."""
        now = datetime.utcnow().isoformat() + "Z"
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE predictions
                SET superseded_at = ?
                WHERE match_id = ? AND team_id = ? AND superseded_at IS NULL
                """,
                (now, match_id, team_id),
            )
            conn.commit()

    def _row_to_prediction(self, row: sqlite3.Row) -> PredictedLineup:
        """Convert a database row to PredictedLineup."""
        return PredictedLineup(
            match_id=row["match_id"],
            team_id=row["team_id"],
            team_name=row["team_name"] or "",
            season=row["season"] if "season" in row.keys() else None,
            competition=row["competition"] if "competition" in row.keys() else None,
            model_version=row["model_version"],
            weights_version=row["weights_version"],
            generated_at=row["generated_at"],
            superseded_at=row["superseded_at"],
            formation=row["formation"] or "",
            formation_confidence=row["formation_confidence"] or 0.0,
            starting_xi=[
                PredictedPlayer.from_dict(p)
                for p in json.loads(row["predicted_xi"])
            ],
            bench=[
                PredictedPlayer.from_dict(p)
                for p in json.loads(row["bench"] or "[]")
            ],
            overall_confidence=row["overall_confidence"] or 0.0,
            key_uncertainties=json.loads(row["key_uncertainties"] or "[]"),
            based_on_matches=row["based_on_matches"] or 0,
        )

    # =========================================================================
    # Confirmed Lineups
    # =========================================================================

    def save_confirmed_lineup(self, lineup: ConfirmedLineup):
        """Save a confirmed lineup."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO confirmed_lineups (
                    match_id, team_id, formation, starting_xi, recorded_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    lineup.match_id,
                    lineup.team_id,
                    lineup.formation,
                    json.dumps(lineup.starting_xi),
                    lineup.recorded_at,
                ),
            )
            conn.commit()

    def get_confirmed_lineup(self, match_id: int, team_id: int) -> Optional[ConfirmedLineup]:
        """Get the confirmed lineup for a match/team."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM confirmed_lineups
                WHERE match_id = ? AND team_id = ?
                """,
                (match_id, team_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            return ConfirmedLineup(
                match_id=row["match_id"],
                team_id=row["team_id"],
                formation=row["formation"],
                starting_xi=json.loads(row["starting_xi"]),
                recorded_at=row["recorded_at"],
            )

    def has_confirmed_lineup(self, match_id: int, team_id: int) -> bool:
        """Check if a confirmed lineup exists."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM confirmed_lineups WHERE match_id = ? AND team_id = ?",
                (match_id, team_id),
            )
            return cursor.fetchone() is not None

    # =========================================================================
    # Accuracy Records
    # =========================================================================

    def save_accuracy_record(self, record: AccuracyRecord) -> int:
        """Save an accuracy record."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO accuracy_records (
                    prediction_id, match_id, team_id, correct_starters,
                    correct_positions, formation_correct, error_breakdown, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.prediction_id,
                    record.match_id,
                    record.team_id,
                    record.correct_starters,
                    record.correct_positions,
                    1 if record.formation_correct else 0,
                    json.dumps(record.error_breakdown),
                    record.evaluated_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_accuracy_stats(
        self, team_id: Optional[int] = None, limit: int = 50
    ) -> Dict[str, Any]:
        """Get aggregate accuracy statistics."""
        with self._get_connection() as conn:
            if team_id:
                cursor = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total_predictions,
                        AVG(correct_starters) as avg_correct_starters,
                        AVG(correct_positions) as avg_correct_positions,
                        SUM(formation_correct) as formation_correct_count
                    FROM accuracy_records
                    WHERE team_id = ?
                    ORDER BY evaluated_at DESC
                    LIMIT ?
                    """,
                    (team_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total_predictions,
                        AVG(correct_starters) as avg_correct_starters,
                        AVG(correct_positions) as avg_correct_positions,
                        SUM(formation_correct) as formation_correct_count
                    FROM accuracy_records
                    ORDER BY evaluated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

            row = cursor.fetchone()
            total = row["total_predictions"] or 0

            return {
                "total_predictions": total,
                "avg_starter_accuracy": (
                    round((row["avg_correct_starters"] or 0) / 11.0, 3)
                    if total > 0 else 0
                ),
                "avg_position_accuracy": (
                    round((row["avg_correct_positions"] or 0) / 11.0, 3)
                    if total > 0 else 0
                ),
                "formation_accuracy": (
                    round((row["formation_correct_count"] or 0) / total, 3)
                    if total > 0 else 0
                ),
            }

    def get_recent_accuracy_records(
        self, team_id: Optional[int] = None, limit: int = 10
    ) -> List[AccuracyRecord]:
        """Get recent accuracy records."""
        with self._get_connection() as conn:
            if team_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM accuracy_records
                    WHERE team_id = ?
                    ORDER BY evaluated_at DESC
                    LIMIT ?
                    """,
                    (team_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM accuracy_records
                    ORDER BY evaluated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

            records = []
            for row in cursor:
                records.append(AccuracyRecord(
                    id=row["id"],
                    prediction_id=row["prediction_id"],
                    match_id=row["match_id"],
                    team_id=row["team_id"],
                    correct_starters=row["correct_starters"],
                    correct_positions=row["correct_positions"],
                    formation_correct=bool(row["formation_correct"]),
                    error_breakdown=json.loads(row["error_breakdown"] or "{}"),
                    evaluated_at=row["evaluated_at"],
                ))
            return records

    # =========================================================================
    # Season Accuracy Summary
    # =========================================================================

    def get_season_accuracy_summary(
        self,
        season: int,
        competition: Optional[str] = None,
        include_team_breakdown: bool = False,
    ) -> SeasonAccuracySummary:
        """
        Get season-level accuracy summary for Predicted XI.

        Args:
            season: The season year (e.g., 2024 for 2024-25)
            competition: Optional competition filter (e.g., "league", "cup")
            include_team_breakdown: If True, include per-team breakdown

        Returns:
            SeasonAccuracySummary with aggregated metrics
        """
        summary = SeasonAccuracySummary(season=season, competition=competition)

        with self._get_connection() as conn:
            # Build the query based on filters
            base_query = """
                SELECT
                    ar.match_id,
                    ar.team_id,
                    ar.correct_starters,
                    p.team_name
                FROM accuracy_records ar
                JOIN predictions p ON ar.prediction_id = p.id
                WHERE p.season = ?
            """
            params: List[Any] = [season]

            if competition:
                base_query += " AND p.competition = ?"
                params.append(competition)

            cursor = conn.execute(base_query, params)
            rows = cursor.fetchall()

            if not rows:
                return summary

            # Calculate aggregates
            total_correct = 0
            perfect_count = 0
            team_data: Dict[int, Dict[str, Any]] = {}

            for row in rows:
                correct = row["correct_starters"]
                team_id = row["team_id"]
                team_name = row["team_name"] or f"Team {team_id}"

                total_correct += correct
                if correct == 11:
                    perfect_count += 1

                # Track per-team stats
                if team_id not in team_data:
                    team_data[team_id] = {
                        "team_name": team_name,
                        "matches": 0,
                        "total_correct": 0,
                    }
                team_data[team_id]["matches"] += 1
                team_data[team_id]["total_correct"] += correct

            summary.matches_evaluated = len(rows)
            summary.total_correct_xi = total_correct
            summary.perfect_xi_count = perfect_count

            # Include team breakdown if requested
            if include_team_breakdown:
                summary.team_breakdown = {
                    tid: {
                        "team_name": data["team_name"],
                        "matches": data["matches"],
                        "avg_correct": round(data["total_correct"] / data["matches"], 2)
                        if data["matches"] > 0 else 0,
                    }
                    for tid, data in team_data.items()
                }

        return summary

    def get_all_season_summaries(
        self, include_team_breakdown: bool = False
    ) -> List[SeasonAccuracySummary]:
        """Get accuracy summaries for all seasons with data."""
        summaries = []

        with self._get_connection() as conn:
            # Get all distinct seasons
            cursor = conn.execute(
                """
                SELECT DISTINCT season FROM predictions
                WHERE season IS NOT NULL
                ORDER BY season DESC
                """
            )
            seasons = [row["season"] for row in cursor.fetchall()]

        for season in seasons:
            summary = self.get_season_accuracy_summary(
                season, include_team_breakdown=include_team_breakdown
            )
            if summary.matches_evaluated > 0:
                summaries.append(summary)

        return summaries

    # =========================================================================
    # Weights
    # =========================================================================

    def get_weights(
        self, team_id: Optional[int] = None, coach_id: Optional[int] = None
    ) -> Dict[str, float]:
        """
        Get effective weights by merging hierarchy: global -> team -> coach.

        Returns the merged weight configuration.
        """
        weights = DEFAULT_WEIGHTS.copy()

        with self._get_connection() as conn:
            # Load global
            cursor = conn.execute(
                "SELECT weights FROM weights WHERE scope = 'global' AND scope_id IS NULL"
            )
            row = cursor.fetchone()
            if row:
                weights.update(json.loads(row["weights"]))

            # Load team-specific (if provided)
            if team_id:
                cursor = conn.execute(
                    "SELECT weights FROM weights WHERE scope = 'team' AND scope_id = ?",
                    (team_id,),
                )
                row = cursor.fetchone()
                if row:
                    weights.update(json.loads(row["weights"]))

            # Load coach-specific (if provided)
            if coach_id:
                cursor = conn.execute(
                    "SELECT weights FROM weights WHERE scope = 'coach' AND scope_id = ?",
                    (coach_id,),
                )
                row = cursor.fetchone()
                if row:
                    weights.update(json.loads(row["weights"]))

        return weights

    def get_weight_config(
        self, scope: WeightScope, scope_id: Optional[int] = None
    ) -> Optional[WeightConfig]:
        """Get a specific weight configuration."""
        with self._get_connection() as conn:
            if scope_id is None:
                cursor = conn.execute(
                    "SELECT * FROM weights WHERE scope = ? AND scope_id IS NULL",
                    (scope.value,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM weights WHERE scope = ? AND scope_id = ?",
                    (scope.value, scope_id),
                )

            row = cursor.fetchone()
            if row is None:
                return None

            return WeightConfig(
                scope=WeightScope(row["scope"]),
                scope_id=row["scope_id"],
                weights=json.loads(row["weights"]),
                version=row["version"],
                updated_at=row["updated_at"],
            )

    def save_weights(self, config: WeightConfig):
        """Save/update a weight configuration."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO weights (scope, scope_id, weights, version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    config.scope.value,
                    config.scope_id,
                    json.dumps(config.weights),
                    config.version,
                    config.updated_at,
                ),
            )
            conn.commit()

    def get_weights_version(
        self, team_id: Optional[int] = None, coach_id: Optional[int] = None
    ) -> str:
        """Get a version string representing the effective weight state."""
        versions = []
        with self._get_connection() as conn:
            # Global version
            cursor = conn.execute(
                "SELECT version FROM weights WHERE scope = 'global' AND scope_id IS NULL"
            )
            row = cursor.fetchone()
            versions.append(f"g{row['version']}" if row else "g1")

            if team_id:
                cursor = conn.execute(
                    "SELECT version FROM weights WHERE scope = 'team' AND scope_id = ?",
                    (team_id,),
                )
                row = cursor.fetchone()
                if row:
                    versions.append(f"t{row['version']}")

            if coach_id:
                cursor = conn.execute(
                    "SELECT version FROM weights WHERE scope = 'coach' AND scope_id = ?",
                    (coach_id,),
                )
                row = cursor.fetchone()
                if row:
                    versions.append(f"c{row['version']}")

        return "-".join(versions)


# Singleton instance
_storage: Optional[PredictionStorage] = None


def get_prediction_storage() -> PredictionStorage:
    """Get the prediction storage instance."""
    global _storage
    if _storage is None:
        _storage = PredictionStorage()
    return _storage

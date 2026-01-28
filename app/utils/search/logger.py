"""Query logging for search analytics and improvement.

Logs low-confidence queries and failures for review.
Controlled by SEARCH_LOGGING environment variable (0/1).
"""

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import threading

# Configuration
SEARCH_LOGGING_ENABLED = os.getenv("SEARCH_LOGGING", "0") == "1"
LOG_DIR = Path(__file__).parent.parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "search_queries.jsonl"

# Lock for thread-safe writing
_log_lock = threading.Lock()


@dataclass
class QueryLog:
    """Log entry for a search query."""
    timestamp: str
    query_hash: str  # SHA256 of normalized query for privacy
    intent: Optional[str]
    intent_confidence: float
    entities_found: int
    disambiguation_triggered: bool
    error_type: Optional[str]
    latency_ms: int
    used_llm: bool


def _hash_query(query: str) -> str:
    """Hash query for privacy-preserving logging."""
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]


def log_query(
    query: str,
    intent: Optional[str],
    intent_confidence: float,
    entities_found: int,
    disambiguation_triggered: bool,
    error_type: Optional[str],
    latency_ms: int,
    used_llm: bool,
) -> None:
    """
    Log a search query for analytics.

    Only logs if SEARCH_LOGGING=1 and one of:
    - intent_confidence < 0.7
    - disambiguation_triggered is True
    - error_type is not None
    """
    if not SEARCH_LOGGING_ENABLED:
        return

    # Only log notable queries
    should_log = (
        intent_confidence < 0.7 or
        disambiguation_triggered or
        error_type is not None
    )

    if not should_log:
        return

    entry = QueryLog(
        timestamp=datetime.utcnow().isoformat() + "Z",
        query_hash=_hash_query(query),
        intent=intent,
        intent_confidence=intent_confidence,
        entities_found=entities_found,
        disambiguation_triggered=disambiguation_triggered,
        error_type=error_type,
        latency_ms=latency_ms,
        used_llm=used_llm,
    )

    _write_log(entry)


def _write_log(entry: QueryLog) -> None:
    """Write log entry to file."""
    with _log_lock:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception:
            pass  # Silently fail on logging errors


def get_recent_logs(limit: int = 100) -> list[dict]:
    """Read recent log entries for review."""
    if not LOG_FILE.exists():
        return []

    entries = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception:
        return []

    return entries[-limit:]


def clear_logs() -> None:
    """Clear all log entries."""
    if LOG_FILE.exists():
        LOG_FILE.unlink()

"""
Search Analytics & Failed Query Registry

Tracks search queries to identify:
1. Failed searches (no results, errors)
2. Low-confidence matches (might be wrong)
3. Popular queries (for optimization)
4. Query patterns (for improving entity matching)

This data helps improve the search system over time.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from collections import defaultdict
import threading


class SearchAnalytics:
    """
    Records and analyzes search queries for continuous improvement.

    Stores:
    - Failed queries (no match, errors)
    - Low confidence matches (might be wrong)
    - Successful queries (for popularity tracking)
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent.parent / "data" / "analytics"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.failed_queries_file = self.data_dir / "failed_queries.json"
        self.low_confidence_file = self.data_dir / "low_confidence_queries.json"
        self.query_log_file = self.data_dir / "query_log.json"

        # In-memory caches
        self._failed_queries: Dict[str, Dict] = {}
        self._low_confidence: Dict[str, Dict] = {}
        self._query_counts: Dict[str, int] = defaultdict(int)

        # Thread safety
        self._lock = threading.Lock()

        # Load existing data
        self._load_data()

    def _load_data(self):
        """Load existing analytics data from disk."""
        try:
            if self.failed_queries_file.exists():
                with open(self.failed_queries_file, 'r', encoding='utf-8') as f:
                    self._failed_queries = json.load(f)
        except (json.JSONDecodeError, IOError):
            self._failed_queries = {}

        try:
            if self.low_confidence_file.exists():
                with open(self.low_confidence_file, 'r', encoding='utf-8') as f:
                    self._low_confidence = json.load(f)
        except (json.JSONDecodeError, IOError):
            self._low_confidence = {}

    def _save_failed_queries(self):
        """Persist failed queries to disk."""
        try:
            with open(self.failed_queries_file, 'w', encoding='utf-8') as f:
                json.dump(self._failed_queries, f, indent=2, ensure_ascii=False)
        except IOError:
            pass  # Non-critical, continue

    def _save_low_confidence(self):
        """Persist low confidence queries to disk."""
        try:
            with open(self.low_confidence_file, 'w', encoding='utf-8') as f:
                json.dump(self._low_confidence, f, indent=2, ensure_ascii=False)
        except IOError:
            pass

    def record_failed_query(
        self,
        query: str,
        reason: str,
        intent_detected: Optional[str] = None,
        entities_found: Optional[List[str]] = None,
        error_message: Optional[str] = None,
    ):
        """
        Record a query that failed to return results.

        Args:
            query: The original search query
            reason: Why it failed (no_entity_match, execution_error, no_data, etc.)
            intent_detected: What intent was classified (if any)
            entities_found: What entities were extracted (if any)
            error_message: Specific error message
        """
        query_lower = query.lower().strip()

        with self._lock:
            if query_lower not in self._failed_queries:
                self._failed_queries[query_lower] = {
                    "query": query,
                    "first_seen": datetime.utcnow().isoformat(),
                    "count": 0,
                    "reasons": [],
                }

            entry = self._failed_queries[query_lower]
            entry["count"] += 1
            entry["last_seen"] = datetime.utcnow().isoformat()

            # Track unique reasons
            reason_entry = {
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
            }
            if intent_detected:
                reason_entry["intent"] = intent_detected
            if entities_found:
                reason_entry["entities"] = entities_found
            if error_message:
                reason_entry["error"] = error_message

            # Keep last 5 failure reasons per query
            entry["reasons"] = entry.get("reasons", [])[-4:] + [reason_entry]

            self._save_failed_queries()

    def record_low_confidence_match(
        self,
        query: str,
        matched_entity: str,
        entity_type: str,
        confidence: float,
        match_method: str,
    ):
        """
        Record a query that matched but with low confidence.

        These are candidates for adding to aliases or improving matching.

        Args:
            query: The original search query
            matched_entity: What entity was matched
            entity_type: player, team, etc.
            confidence: The match confidence score
            match_method: How it was matched (fuzzy, token, etc.)
        """
        query_lower = query.lower().strip()

        with self._lock:
            if query_lower not in self._low_confidence:
                self._low_confidence[query_lower] = {
                    "query": query,
                    "first_seen": datetime.utcnow().isoformat(),
                    "count": 0,
                    "matches": [],
                }

            entry = self._low_confidence[query_lower]
            entry["count"] += 1
            entry["last_seen"] = datetime.utcnow().isoformat()

            match_entry = {
                "entity": matched_entity,
                "type": entity_type,
                "confidence": round(confidence, 3),
                "method": match_method,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Keep last 3 matches per query
            entry["matches"] = entry.get("matches", [])[-2:] + [match_entry]

            self._save_low_confidence()

    def record_successful_query(self, query: str, result_type: str):
        """Record a successful query for popularity tracking."""
        query_lower = query.lower().strip()
        with self._lock:
            self._query_counts[query_lower] += 1

    def get_failed_queries(self, min_count: int = 1, limit: int = 100) -> List[Dict]:
        """
        Get failed queries sorted by count.

        Args:
            min_count: Minimum failure count to include
            limit: Maximum results to return

        Returns:
            List of failed query entries
        """
        with self._lock:
            queries = [
                {**v, "query_key": k}
                for k, v in self._failed_queries.items()
                if v.get("count", 0) >= min_count
            ]

        queries.sort(key=lambda x: x.get("count", 0), reverse=True)
        return queries[:limit]

    def get_low_confidence_queries(self, max_confidence: float = 0.85, limit: int = 100) -> List[Dict]:
        """
        Get low confidence matches sorted by count.

        Args:
            max_confidence: Maximum confidence to include
            limit: Maximum results to return

        Returns:
            List of low confidence query entries
        """
        with self._lock:
            queries = []
            for k, v in self._low_confidence.items():
                matches = v.get("matches", [])
                if matches:
                    # Get the most recent match confidence
                    latest_confidence = matches[-1].get("confidence", 1.0)
                    if latest_confidence <= max_confidence:
                        queries.append({**v, "query_key": k})

        queries.sort(key=lambda x: x.get("count", 0), reverse=True)
        return queries[:limit]

    def get_summary(self) -> Dict[str, Any]:
        """Get analytics summary."""
        # Get counts under lock
        with self._lock:
            failed_count = len(self._failed_queries)
            low_conf_count = len(self._low_confidence)

        # Get top items without lock (they acquire their own)
        return {
            "total_failed_queries": failed_count,
            "total_low_confidence": low_conf_count,
            "top_failed": self.get_failed_queries(limit=10),
            "top_low_confidence": self.get_low_confidence_queries(limit=10),
        }

    def export_for_review(self) -> Dict[str, Any]:
        """
        Export all analytics data for manual review.

        Returns dict suitable for analysis/improvement.
        """
        with self._lock:
            return {
                "exported_at": datetime.utcnow().isoformat(),
                "failed_queries": self._failed_queries,
                "low_confidence_queries": self._low_confidence,
                "summary": {
                    "total_failed": len(self._failed_queries),
                    "total_low_confidence": len(self._low_confidence),
                    "unique_failure_reasons": self._get_failure_reasons(),
                }
            }

    def _get_failure_reasons(self) -> Dict[str, int]:
        """Get count of each failure reason."""
        reasons = defaultdict(int)
        for entry in self._failed_queries.values():
            for r in entry.get("reasons", []):
                reasons[r.get("reason", "unknown")] += 1
        return dict(reasons)

    def clear_old_entries(self, days: int = 30):
        """Clear entries older than specified days."""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        with self._lock:
            # Clear old failed queries
            self._failed_queries = {
                k: v for k, v in self._failed_queries.items()
                if v.get("last_seen", v.get("first_seen", "")) >= cutoff_str
            }
            self._save_failed_queries()

            # Clear old low confidence
            self._low_confidence = {
                k: v for k, v in self._low_confidence.items()
                if v.get("last_seen", v.get("first_seen", "")) >= cutoff_str
            }
            self._save_low_confidence()


# Global instance
_analytics: Optional[SearchAnalytics] = None


def get_analytics() -> SearchAnalytics:
    """Get the global analytics instance."""
    global _analytics
    if _analytics is None:
        _analytics = SearchAnalytics()
    return _analytics


def record_search_result(
    query: str,
    success: bool,
    result_type: Optional[str] = None,
    confidence: Optional[float] = None,
    matched_entity: Optional[str] = None,
    entity_type: Optional[str] = None,
    match_method: Optional[str] = None,
    error_reason: Optional[str] = None,
    error_message: Optional[str] = None,
    intent_detected: Optional[str] = None,
    entities_found: Optional[List[str]] = None,
):
    """
    Convenience function to record a search result.

    Call this after each search to build analytics.
    """
    analytics = get_analytics()

    if not success:
        analytics.record_failed_query(
            query=query,
            reason=error_reason or "unknown",
            intent_detected=intent_detected,
            entities_found=entities_found,
            error_message=error_message,
        )
    elif confidence is not None and confidence < 0.85 and matched_entity:
        analytics.record_low_confidence_match(
            query=query,
            matched_entity=matched_entity,
            entity_type=entity_type or "unknown",
            confidence=confidence,
            match_method=match_method or "unknown",
        )
    else:
        analytics.record_successful_query(query, result_type or "unknown")

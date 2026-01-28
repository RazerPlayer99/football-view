"""Session management for search context."""

import uuid
from datetime import datetime
from typing import Dict, Optional
from threading import Lock

from .models.session import SearchSession


class SessionStore:
    """
    In-memory session store for search context.

    Thread-safe storage for session state with TTL-based expiration.
    Sessions expire after 30 minutes of inactivity.
    """

    def __init__(self):
        self._sessions: Dict[str, SearchSession] = {}
        self._lock = Lock()

    def get(self, session_id: str) -> Optional[SearchSession]:
        """
        Get a session by ID.

        Returns None if session doesn't exist or has expired.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.is_expired():
                del self._sessions[session_id]
                return None
            return session

    def get_or_create(self, session_id: Optional[str] = None) -> SearchSession:
        """
        Get an existing session or create a new one.

        Args:
            session_id: Optional ID to retrieve. If None, creates new session.

        Returns:
            The session (existing or newly created)
        """
        if session_id:
            session = self.get(session_id)
            if session:
                return session

        # Create new session
        new_id = session_id or str(uuid.uuid4())
        with self._lock:
            session = SearchSession(session_id=new_id)
            self._sessions[new_id] = session
            return session

    def update(
        self,
        session_id: str,
        team_id: Optional[int] = None,
        player_id: Optional[int] = None,
        fixture_id: Optional[int] = None,
        league_id: Optional[int] = None,
        season: Optional[int] = None,
        intent: Optional[str] = None,
    ) -> Optional[SearchSession]:
        """
        Update a session with new context.

        Returns the updated session, or None if session doesn't exist.
        """
        session = self.get(session_id)
        if session is None:
            return None

        with self._lock:
            session.update_from_entities(
                team_id=team_id,
                player_id=player_id,
                fixture_id=fixture_id,
                league_id=league_id,
                season=season,
                intent=intent,
            )
            return session

    def cleanup_expired(self) -> int:
        """
        Remove all expired sessions.

        Returns the number of sessions removed.
        """
        with self._lock:
            expired_ids = [
                sid for sid, session in self._sessions.items()
                if session.is_expired()
            ]
            for sid in expired_ids:
                del self._sessions[sid]
            return len(expired_ids)

    def clear(self) -> None:
        """Remove all sessions."""
        with self._lock:
            self._sessions.clear()

    @property
    def count(self) -> int:
        """Return the number of active sessions."""
        return len(self._sessions)


# Global session store instance
_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Get the global session store instance."""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store

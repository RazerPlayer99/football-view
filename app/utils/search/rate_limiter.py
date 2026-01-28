"""Rate limiting for search endpoint."""

from collections import defaultdict
from time import time
from threading import Lock
from typing import Optional, Tuple

# Configuration
RATE_LIMIT_REQUESTS = 60  # Max requests per window
RATE_LIMIT_WINDOW_SECONDS = 60  # Window size in seconds


class RateLimiter:
    """
    Sliding window rate limiter for search requests.

    Limits to 60 requests per minute per client (IP or session).
    Thread-safe implementation.
    """

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_REQUESTS,
        window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, client_id: str) -> Tuple[bool, Optional[int]]:
        """
        Check if a request is allowed for the given client.

        Args:
            client_id: Unique identifier for the client (IP address or session ID)

        Returns:
            Tuple of (allowed: bool, retry_after_seconds: Optional[int])
            If not allowed, retry_after_seconds indicates when to retry.
        """
        now = time()
        window_start = now - self.window_seconds

        with self._lock:
            # Clean old entries
            self._requests[client_id] = [
                ts for ts in self._requests[client_id]
                if ts > window_start
            ]

            # Check limit
            if len(self._requests[client_id]) >= self.max_requests:
                # Calculate retry time
                oldest_in_window = min(self._requests[client_id])
                retry_after = int(oldest_in_window + self.window_seconds - now) + 1
                return False, max(1, retry_after)

            # Record this request
            self._requests[client_id].append(now)
            return True, None

    def remaining(self, client_id: str) -> int:
        """
        Get the number of remaining requests for a client.

        Args:
            client_id: Unique identifier for the client

        Returns:
            Number of requests remaining in the current window
        """
        now = time()
        window_start = now - self.window_seconds

        with self._lock:
            current_requests = [
                ts for ts in self._requests[client_id]
                if ts > window_start
            ]
            return max(0, self.max_requests - len(current_requests))

    def reset(self, client_id: str) -> None:
        """
        Reset the rate limit for a specific client.

        Useful for testing or admin override.
        """
        with self._lock:
            if client_id in self._requests:
                del self._requests[client_id]

    def cleanup(self) -> int:
        """
        Remove all stale entries from the limiter.

        Returns the number of clients cleaned up.
        """
        now = time()
        window_start = now - self.window_seconds
        cleaned = 0

        with self._lock:
            empty_clients = []
            for client_id, timestamps in self._requests.items():
                # Filter to only recent timestamps
                recent = [ts for ts in timestamps if ts > window_start]
                if recent:
                    self._requests[client_id] = recent
                else:
                    empty_clients.append(client_id)

            # Remove empty clients
            for client_id in empty_clients:
                del self._requests[client_id]
                cleaned += 1

        return cleaned


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter

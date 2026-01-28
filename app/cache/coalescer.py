"""
Request coalescing to prevent duplicate upstream API calls.

When multiple concurrent requests ask for the same data, only one
upstream call is made and all requesters share the result.
"""
import threading
import time
import logging
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger("cache.coalescer")


@dataclass
class InFlightRequest:
    """Tracks an in-progress upstream request."""
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[Any] = None
    error: Optional[Exception] = None
    started_at: float = field(default_factory=time.time)
    waiter_count: int = 0


class RequestCoalescer:
    """
    Ensures concurrent requests for the same cache key share one upstream call.

    Pattern:
    - First request for a key initiates the fetch
    - Subsequent requests for the same key wait on the Event
    - When fetch completes, all waiters receive the same result
    - Thread-safe via key-level management

    Usage:
        coalescer = RequestCoalescer()
        result = coalescer.get_or_fetch(
            cache_key="standings:...",
            fetch_fn=lambda: make_api_call(),
        )
    """

    def __init__(self, timeout: float = 30.0):
        """
        Initialize the coalescer.

        Args:
            timeout: Max seconds to wait for an in-flight request
        """
        self._in_flight: Dict[str, InFlightRequest] = {}
        self._lock = threading.Lock()
        self._timeout = timeout

    def get_or_fetch(
        self,
        cache_key: str,
        fetch_fn: Callable[[], Any],
    ) -> Any:
        """
        Either join an existing in-flight request or initiate a new one.

        Args:
            cache_key: Unique key for this request
            fetch_fn: Function to call if we need to fetch

        Returns:
            The fetched data (shared among all concurrent callers)

        Raises:
            TimeoutError: If waiting for in-flight request times out
            Exception: Any error from fetch_fn is propagated
        """
        with self._lock:
            if cache_key in self._in_flight:
                # Join existing request
                in_flight = self._in_flight[cache_key]
                in_flight.waiter_count += 1
                logger.debug(
                    f"Coalescing request for {cache_key} "
                    f"(waiters: {in_flight.waiter_count})"
                )
                is_initiator = False
            else:
                # Start new request
                in_flight = InFlightRequest()
                self._in_flight[cache_key] = in_flight
                is_initiator = True
                logger.debug(f"Initiating fetch for {cache_key}")

        if is_initiator:
            # We're the initiator - perform the fetch
            try:
                result = fetch_fn()
                in_flight.result = result
            except Exception as e:
                in_flight.error = e
                logger.warning(f"Fetch failed for {cache_key}: {e}")
            finally:
                # Signal completion to all waiters
                in_flight.event.set()
                # Clean up
                with self._lock:
                    if cache_key in self._in_flight:
                        del self._in_flight[cache_key]

            if in_flight.error:
                raise in_flight.error
            return in_flight.result

        # We're a waiter - wait for the initiator to complete
        completed = in_flight.event.wait(timeout=self._timeout)

        if not completed:
            logger.error(f"Timeout waiting for coalesced request: {cache_key}")
            raise TimeoutError(f"Request for {cache_key} timed out after {self._timeout}s")

        if in_flight.error:
            raise in_flight.error

        return in_flight.result

    @property
    def active_requests(self) -> int:
        """Number of currently in-flight requests."""
        with self._lock:
            return len(self._in_flight)

    def get_stats(self) -> Dict[str, Any]:
        """Get coalescer statistics."""
        with self._lock:
            return {
                "active_requests": len(self._in_flight),
                "active_keys": list(self._in_flight.keys()),
            }

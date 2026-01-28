"""
Main cache orchestration with tiered TTL and stale-while-revalidate.
"""
import threading
import logging
from datetime import datetime
from typing import Dict, Optional, Callable, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

from .core import CacheEntry, CacheMeta, CacheSource, DataCategory
from .coalescer import RequestCoalescer
from .ttl_policies import get_ttl_for_category, get_category_for_endpoint

logger = logging.getLogger("cache.manager")


class CacheManager:
    """
    Main cache orchestration with:
    - Tiered TTL based on data category
    - Request coalescing for concurrent duplicate requests
    - Stale-while-revalidate for background refresh
    - Response metadata tracking
    """

    def __init__(
        self,
        max_revalidation_workers: int = 4,
        coalesce_timeout: float = 30.0,
    ):
        """
        Initialize the cache manager.

        Args:
            max_revalidation_workers: Thread pool size for background revalidation
            coalesce_timeout: Timeout for waiting on coalesced requests
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._cache_lock = threading.RLock()
        self._coalescer = RequestCoalescer(timeout=coalesce_timeout)

        # Background revalidation
        self._revalidation_pool = ThreadPoolExecutor(
            max_workers=max_revalidation_workers,
            thread_name_prefix="cache-revalidate",
        )
        self._revalidating: set = set()
        self._revalidating_lock = threading.Lock()

        # Stats tracking
        self._stats = {
            "hits_fresh": 0,
            "hits_stale": 0,
            "misses": 0,
            "revalidations": 0,
        }

    def get(
        self,
        cache_key: str,
        fetch_fn: Callable[[], Any],
        endpoint: str,
        params: Dict[str, Any],
        force_refresh: bool = False,
        context: Optional[Dict[str, Any]] = None,
        is_live_match_window: bool = False,
    ) -> Tuple[Any, CacheMeta]:
        """
        Get data from cache or fetch from upstream.

        Args:
            cache_key: Unique cache key
            fetch_fn: Function to fetch data if needed
            endpoint: API endpoint for category determination
            params: API parameters for category determination
            force_refresh: Bypass cache entirely
            context: Additional context (e.g., fixture status)
            is_live_match_window: True if live matches are happening

        Returns:
            (data, cache_meta) tuple
        """
        # Determine category and TTL
        category = get_category_for_endpoint(endpoint, params, context)
        fresh_ttl, stale_ttl, allow_swr = get_ttl_for_category(
            category, is_live_match_window
        )

        # Force refresh bypasses cache entirely
        if force_refresh:
            logger.info(f"FORCE REFRESH: {cache_key}")
            data = self._coalescer.get_or_fetch(cache_key, fetch_fn)
            self._store(cache_key, data, fresh_ttl, stale_ttl, category)
            self._stats["misses"] += 1
            return data, self._make_meta(CacheSource.UPSTREAM, category, fresh_ttl, 0)

        # Check cache
        with self._cache_lock:
            entry = self._cache.get(cache_key)

        # Cache miss
        if entry is None:
            logger.info(f"CACHE MISS: {cache_key}")
            data = self._coalescer.get_or_fetch(cache_key, fetch_fn)
            self._store(cache_key, data, fresh_ttl, stale_ttl, category)
            self._stats["misses"] += 1
            return data, self._make_meta(CacheSource.UPSTREAM, category, fresh_ttl, 0)

        # Cache hit - fresh
        if entry.is_fresh:
            logger.debug(f"CACHE HIT (fresh): {cache_key} [age={entry.age_seconds:.1f}s]")
            self._stats["hits_fresh"] += 1
            return entry.data, self._make_meta(
                CacheSource.FRESH, category, fresh_ttl, entry.age_seconds
            )

        # Stale but usable with SWR
        if entry.is_usable_stale and allow_swr:
            logger.info(
                f"CACHE HIT (stale, revalidating): {cache_key} "
                f"[age={entry.age_seconds:.1f}s]"
            )
            self._trigger_background_revalidate(
                cache_key, fetch_fn, fresh_ttl, stale_ttl, category
            )
            self._stats["hits_stale"] += 1
            return entry.data, self._make_meta(
                CacheSource.STALE, category, fresh_ttl, entry.age_seconds
            )

        # Expired or stale without SWR - must refetch
        logger.info(f"CACHE EXPIRED: {cache_key} [age={entry.age_seconds:.1f}s]")
        data = self._coalescer.get_or_fetch(cache_key, fetch_fn)
        self._store(cache_key, data, fresh_ttl, stale_ttl, category)
        self._stats["misses"] += 1
        return data, self._make_meta(CacheSource.UPSTREAM, category, fresh_ttl, 0)

    def _store(
        self,
        cache_key: str,
        data: Any,
        fresh_ttl: int,
        stale_ttl: int,
        category: DataCategory,
    ) -> None:
        """Store data in cache."""
        entry = CacheEntry(
            data=data,
            fetched_at=datetime.utcnow(),
            ttl_seconds=fresh_ttl,
            stale_ttl_seconds=stale_ttl,
            category=category,
        )
        with self._cache_lock:
            self._cache[cache_key] = entry

    def _trigger_background_revalidate(
        self,
        cache_key: str,
        fetch_fn: Callable[[], Any],
        fresh_ttl: int,
        stale_ttl: int,
        category: DataCategory,
    ) -> None:
        """Trigger background refresh without blocking."""
        with self._revalidating_lock:
            if cache_key in self._revalidating:
                logger.debug(f"Already revalidating: {cache_key}")
                return
            self._revalidating.add(cache_key)

        def do_revalidate():
            try:
                logger.debug(f"Background revalidation started: {cache_key}")
                # Use separate coalesce key to not block reads
                data = self._coalescer.get_or_fetch(
                    f"{cache_key}:revalidate",
                    fetch_fn,
                )
                self._store(cache_key, data, fresh_ttl, stale_ttl, category)
                self._stats["revalidations"] += 1
                logger.debug(f"Background revalidation complete: {cache_key}")
            except Exception as e:
                logger.warning(f"Background revalidation failed: {cache_key} - {e}")
            finally:
                with self._revalidating_lock:
                    self._revalidating.discard(cache_key)

        self._revalidation_pool.submit(do_revalidate)

    def _make_meta(
        self,
        source: CacheSource,
        category: DataCategory,
        ttl: int,
        age: float,
    ) -> CacheMeta:
        """Create cache metadata for response."""
        return CacheMeta(
            last_updated=datetime.utcnow().isoformat() + "Z",
            cache_source=source.value,
            category=category.value,
            ttl_seconds=ttl,
            age_seconds=age,
        )

    def invalidate(self, cache_key: str) -> bool:
        """
        Invalidate a specific cache entry.

        Returns:
            True if entry was found and removed
        """
        with self._cache_lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.info(f"Invalidated cache: {cache_key}")
                return True
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all cache entries matching a pattern.

        Args:
            pattern: Substring to match in cache keys

        Returns:
            Number of entries invalidated
        """
        with self._cache_lock:
            to_delete = [k for k in self._cache if pattern in k]
            for key in to_delete:
                del self._cache[key]
            if to_delete:
                logger.info(f"Invalidated {len(to_delete)} entries matching '{pattern}'")
            return len(to_delete)

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared {count} cache entries")
            return count

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._cache_lock:
            total_hits = self._stats["hits_fresh"] + self._stats["hits_stale"]
            total_requests = total_hits + self._stats["misses"]
            hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0

            return {
                "entries": len(self._cache),
                "hits_fresh": self._stats["hits_fresh"],
                "hits_stale": self._stats["hits_stale"],
                "misses": self._stats["misses"],
                "revalidations": self._stats["revalidations"],
                "hit_rate_percent": round(hit_rate, 1),
                "coalescer": self._coalescer.get_stats(),
                "revalidating_count": len(self._revalidating),
            }


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """Get or create the global cache manager."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager

"""
Core cache data structures.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from enum import Enum


class DataCategory(Enum):
    """Categories of data with different caching behaviors."""
    LIVE_MATCH = "live_match"                     # 2-5 seconds, no SWR
    SEMI_VOLATILE = "semi_volatile"               # 30-60 seconds
    STANDINGS = "standings"                       # 60-180 seconds, SWR outside live
    PLAYER_SEASON_STATS = "player_season_stats"   # 10-30 minutes, SWR
    TEAM_SEASON_STATS = "team_season_stats"       # 10-30 minutes, SWR
    STABLE_METADATA = "stable_metadata"           # 6-24 hours, SWR


class CacheSource(Enum):
    """Source of cached data."""
    FRESH = "fresh"       # Within TTL
    STALE = "stale"       # Past TTL but within stale window, revalidating
    UPSTREAM = "upstream" # Fetched from API


@dataclass
class CacheEntry:
    """
    Represents a cached item with metadata for TTL and staleness tracking.
    """
    data: Any
    fetched_at: datetime
    ttl_seconds: int
    stale_ttl_seconds: int = 0  # Additional time stale data can be served
    category: DataCategory = DataCategory.SEMI_VOLATILE

    @property
    def age_seconds(self) -> float:
        """Seconds since data was fetched."""
        return (datetime.utcnow() - self.fetched_at).total_seconds()

    @property
    def is_fresh(self) -> bool:
        """Check if data is within its TTL."""
        return self.age_seconds < self.ttl_seconds

    @property
    def is_usable_stale(self) -> bool:
        """Check if data is stale but can still be served while revalidating."""
        age = self.age_seconds
        return self.ttl_seconds <= age < (self.ttl_seconds + self.stale_ttl_seconds)

    @property
    def is_expired(self) -> bool:
        """Check if data is completely expired and must be refetched."""
        return self.age_seconds >= (self.ttl_seconds + self.stale_ttl_seconds)

    @property
    def cache_source(self) -> CacheSource:
        """Determine the cache source status."""
        if self.is_fresh:
            return CacheSource.FRESH
        elif self.is_usable_stale:
            return CacheSource.STALE
        else:
            return CacheSource.UPSTREAM


@dataclass
class CacheMeta:
    """
    Metadata about a cache access, included in API responses.
    """
    last_updated: str  # ISO timestamp
    cache_source: str  # "fresh", "stale", or "upstream"
    category: Optional[str] = None
    ttl_seconds: Optional[int] = None
    age_seconds: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON response."""
        result = {
            "lastUpdated": self.last_updated,
            "cacheSource": self.cache_source,
        }
        # Include debug info if available
        if self.category:
            result["_debug"] = {
                "category": self.category,
                "ttl": self.ttl_seconds,
                "age": round(self.age_seconds, 1) if self.age_seconds else None,
            }
        return result

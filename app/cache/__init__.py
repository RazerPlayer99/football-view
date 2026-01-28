"""
Advanced caching module with tiered TTL, request coalescing, and stale-while-revalidate.
"""
from .core import CacheEntry, CacheMeta, CacheSource, DataCategory
from .ttl_policies import (
    TTL_CONFIG,
    get_ttl_for_category,
    get_category_for_endpoint,
    get_lineup_ttl,
)
from .coalescer import RequestCoalescer
from .manager import CacheManager, get_cache_manager

__all__ = [
    # Core types
    "CacheEntry",
    "CacheMeta",
    "CacheSource",
    "DataCategory",
    # TTL policies
    "TTL_CONFIG",
    "get_ttl_for_category",
    "get_category_for_endpoint",
    "get_lineup_ttl",
    # Coalescing
    "RequestCoalescer",
    # Manager
    "CacheManager",
    "get_cache_manager",
]

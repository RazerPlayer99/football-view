"""
Utility helper functions for safe data handling.
"""
from typing import Any, Optional


def safe_str(value: Any, default: str = "") -> str:
    """
    Safely convert value to string, handling None.

    Args:
        value: Any value to convert
        default: Default string if value is None

    Returns:
        String representation or default
    """
    if value is None:
        return default
    return str(value)


def safe_lower(value: Any) -> str:
    """
    Safely lowercase a value, handling None.

    Args:
        value: Any value to lowercase

    Returns:
        Lowercased string or empty string if None
    """
    if value is None:
        return ""
    return str(value).lower()


def safe_strip(value: Any) -> str:
    """
    Safely strip whitespace from a value, handling None.

    Args:
        value: Any value to strip

    Returns:
        Stripped string or empty string if None
    """
    if value is None:
        return ""
    return str(value).strip()


def safe_int(value: Any, default: int = 0) -> int:
    """
    Safely convert value to int, handling None and invalid values.

    Args:
        value: Any value to convert
        default: Default int if conversion fails

    Returns:
        Integer or default
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

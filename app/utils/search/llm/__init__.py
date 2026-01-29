# LLM integration for search fallback
# LLM is ONLY used for intent/entities/confidence - NEVER factual answers

import os
import logging
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from .base import LLMProvider, NullLLMProvider

# Ensure .env is loaded for API key access (override=True in case empty var exists)
load_dotenv(override=True)

if TYPE_CHECKING:
    from .claude import ClaudeProvider

logger = logging.getLogger(__name__)

__all__ = ["LLMProvider", "NullLLMProvider", "get_llm_provider"]


def get_llm_provider() -> LLMProvider:
    """
    Get the configured LLM provider.

    Returns ClaudeProvider if ANTHROPIC_API_KEY is set and anthropic
    package is installed. Otherwise returns NullLLMProvider.

    The NullLLMProvider is a safe fallback that returns low-confidence
    UNKNOWN results, allowing the search to continue with rule-based
    classification only.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if api_key:
        try:
            from .claude import ClaudeProvider
            provider = ClaudeProvider(api_key=api_key)
            if provider.is_available:
                logger.info("Using Claude LLM provider for search fallback")
                return provider
            else:
                logger.warning("Claude provider not available, falling back to null")
        except ImportError:
            logger.warning("anthropic package not installed, LLM fallback disabled")
        except Exception as e:
            logger.warning(f"Failed to initialize Claude provider: {e}")

    logger.info("Using null LLM provider (rule-based classification only)")
    return NullLLMProvider()

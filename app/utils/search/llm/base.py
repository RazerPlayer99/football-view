"""Base LLM provider abstraction for search fallback.

IMPORTANT: LLM is ONLY used for:
- Intent classification when rule-based confidence < 0.7
- Entity extraction when fuzzy matching is ambiguous
- Pronoun resolution requiring context understanding

LLM is NEVER used for:
- Answering factual questions directly
- Generating match results, stats, or data
- Making predictions or opinions
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

from ..models.intent import IntentResult
from ..models.entities import Entity


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All implementations must ensure they ONLY return structural information
    (intent, entities, confidence) and NEVER factual football data.
    """

    @abstractmethod
    def classify_intent(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        Classify the intent of a search query.

        Args:
            query: The normalized search query
            context: Optional session context (last entities, etc.)

        Returns:
            IntentResult with intent type and confidence

        Note:
            Must NEVER return factual data, only classification.
        """
        pass

    @abstractmethod
    def extract_entities(
        self,
        query: str,
        entity_types: List[str],
        known_entities: Optional[Dict[str, List[str]]] = None,
    ) -> List[Entity]:
        """
        Extract entity mentions from a query.

        Args:
            query: The search query
            entity_types: Types to look for ("team", "player", "competition")
            known_entities: Optional dict of known entity names for matching

        Returns:
            List of extracted entities with confidence scores

        Note:
            Must NEVER return factual data, only entity extraction.
        """
        pass

    @abstractmethod
    def resolve_pronoun(
        self,
        pronoun: str,
        context: Dict[str, Any],
        query: str,
    ) -> Optional[tuple[str, int]]:
        """
        Resolve a pronoun to an entity using context.

        Args:
            pronoun: The pronoun to resolve ("he", "they", etc.)
            context: Session context with recent entities
            query: Full query for additional context

        Returns:
            Tuple of (entity_type, entity_id) or None if unresolvable

        Note:
            Uses context only, does not make up entity references.
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of this LLM provider."""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and available."""
        pass


class NullLLMProvider(LLMProvider):
    """
    Null implementation that returns low-confidence results.

    Used when no LLM is configured or during testing.
    """

    def classify_intent(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        from ..models.intent import IntentType
        return IntentResult(
            intent_type=IntentType.UNKNOWN,
            confidence=0.0,
            used_llm=False,
        )

    def extract_entities(
        self,
        query: str,
        entity_types: List[str],
        known_entities: Optional[Dict[str, List[str]]] = None,
    ) -> List[Entity]:
        return []

    def resolve_pronoun(
        self,
        pronoun: str,
        context: Dict[str, Any],
        query: str,
    ) -> Optional[tuple[str, int]]:
        return None

    @property
    def provider_name(self) -> str:
        return "null"

    @property
    def is_available(self) -> bool:
        return True

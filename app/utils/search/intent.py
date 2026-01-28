"""Intent classification for search queries."""

from typing import Optional, Dict, Any

from .models.intent import IntentType, IntentResult, TimeModifier
from .models.entities import ExtractionResult
from .patterns import match_intent, UNSUPPORTED_PATTERNS
from .normalizer import normalize_query
from .llm.base import LLMProvider, NullLLMProvider


# Confidence threshold for LLM fallback
LLM_FALLBACK_THRESHOLD = 0.70


class IntentClassifier:
    """
    Classifies search queries into intent types.

    Uses rule-based pattern matching first, with optional LLM fallback
    for low-confidence or ambiguous queries.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        """
        Initialize the classifier.

        Args:
            llm_provider: Optional LLM provider for fallback. Uses NullLLMProvider if not provided.
        """
        self.llm_provider = llm_provider or NullLLMProvider()

    def classify(
        self,
        query: str,
        normalized_query: str,
        entities: Optional[ExtractionResult] = None,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        Classify a search query into an intent.

        Args:
            query: Original raw query
            normalized_query: Normalized query (lowercase, expanded abbreviations)
            entities: Optional extracted entities for refinement
            session_context: Optional session context for disambiguation

        Returns:
            IntentResult with intent type, confidence, and any time modifier
        """
        # Step 1: Rule-based classification
        result = match_intent(normalized_query)

        # Step 2: Refine based on entities
        if entities:
            result = self._refine_with_entities(result, entities)

        # Step 3: LLM fallback if needed
        if result.needs_llm_fallback and self.llm_provider.is_available:
            llm_result = self._llm_classify(query, session_context)
            if llm_result and llm_result.confidence > result.confidence:
                return llm_result

        return result

    def _refine_with_entities(
        self,
        result: IntentResult,
        entities: ExtractionResult,
    ) -> IntentResult:
        """
        Refine intent classification based on extracted entities.

        For example:
        - If query matched TEAM_LOOKUP but only players were found, switch to PLAYER_LOOKUP
        - If two teams found with "vs", confirm MATCH_LOOKUP
        - If two entities of same type with high confidence, likely COMPARISON
        """
        # If we detected a team lookup but only found players, switch to player lookup
        if result.intent_type == IntentType.TEAM_LOOKUP:
            if entities.players and not entities.teams:
                return IntentResult(
                    intent_type=IntentType.PLAYER_LOOKUP,
                    confidence=result.confidence,
                    time_modifier=result.time_modifier,
                    matched_pattern=result.matched_pattern,
                    raw_captures=result.raw_captures,
                )

        # If we found exactly 2 teams/players, might be comparison
        if result.intent_type in (IntentType.TEAM_LOOKUP, IntentType.PLAYER_LOOKUP):
            if len(entities.teams) == 2 or len(entities.players) == 2:
                # Check if this looks more like a match lookup (vs pattern)
                if "versus" in result.matched_pattern if result.matched_pattern else False:
                    return IntentResult(
                        intent_type=IntentType.MATCH_LOOKUP,
                        confidence=min(result.confidence + 0.05, 0.98),
                        time_modifier=result.time_modifier,
                        matched_pattern=result.matched_pattern,
                        raw_captures=result.raw_captures,
                    )

        # If we found a metric, boost confidence for relevant intents
        if entities.metrics:
            metric = entities.metrics[0]
            if metric.metric_id in ("goals", "xg", "shots"):
                if result.intent_type == IntentType.TOP_SCORERS:
                    result = IntentResult(
                        intent_type=result.intent_type,
                        confidence=min(result.confidence + 0.05, 0.98),
                        time_modifier=result.time_modifier,
                        matched_pattern=result.matched_pattern,
                        raw_captures=result.raw_captures,
                    )
            elif metric.metric_id in ("assists", "xa"):
                if result.intent_type == IntentType.TOP_ASSISTS:
                    result = IntentResult(
                        intent_type=result.intent_type,
                        confidence=min(result.confidence + 0.05, 0.98),
                        time_modifier=result.time_modifier,
                        matched_pattern=result.matched_pattern,
                        raw_captures=result.raw_captures,
                    )

        return result

    def _llm_classify(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[IntentResult]:
        """
        Use LLM for intent classification fallback.

        Only called when rule-based confidence is below threshold.
        LLM only returns intent/confidence, NEVER factual data.
        """
        try:
            return self.llm_provider.classify_intent(query, context or {})
        except Exception:
            return None


def classify_intent(
    raw_query: str,
    entities: Optional[ExtractionResult] = None,
    session_context: Optional[Dict[str, Any]] = None,
    llm_provider: Optional[LLMProvider] = None,
) -> tuple[IntentResult, str, str, Optional[TimeModifier]]:
    """
    Convenience function to classify a query.

    Returns:
        Tuple of (IntentResult, normalized_query, query_for_matching, time_modifier)
    """
    # Normalize the query
    normalized, for_matching, time_modifier = normalize_query(raw_query)

    # Classify
    classifier = IntentClassifier(llm_provider)
    result = classifier.classify(
        raw_query,
        normalized,
        entities,
        session_context,
    )

    # Attach time modifier to result if found during normalization
    if time_modifier and not result.time_modifier:
        result = IntentResult(
            intent_type=result.intent_type,
            confidence=result.confidence,
            time_modifier=time_modifier,
            used_llm=result.used_llm,
            matched_pattern=result.matched_pattern,
            raw_captures=result.raw_captures,
        )

    return result, normalized, for_matching, time_modifier

"""
Main search pipeline orchestrator.

This module coordinates the full search flow:
1. Rate limiting check
2. Normalize query
3. Classify intent
4. Extract entities
5. Resolve disambiguation
6. Execute query
7. Format response
8. Log query (if enabled)
"""

import time
from typing import Optional

from .normalizer import normalize_query
from .patterns import match_intent
from .entities import extract_entities, get_alias_database
from .intent import classify_intent, IntentClassifier
from .resolver import resolve_query, ResolvedQuery
from .executor import execute_query
from .formatter import format_response
from .session import get_session_store
from .rate_limiter import get_rate_limiter
from .logger import log_query
from .llm import get_llm_provider
from .analytics import record_search_result
from .models.intent import IntentType
from .models.responses import (
    SearchResponse,
    DisambiguationPayload,
    error_response,
    disambiguation_response,
)


def search(
    query: str,
    session_id: Optional[str] = None,
    client_id: Optional[str] = None,
    season: Optional[int] = None,
    league_id: Optional[int] = None,
) -> SearchResponse:
    """
    Execute a search query and return a formatted response.

    This is the main entry point for the unified search system.

    Args:
        query: Raw search query from user
        session_id: Optional session ID for context continuity
        client_id: Optional client ID for rate limiting (IP address)
        season: Optional season override
        league_id: Optional league override

    Returns:
        SearchResponse with results, disambiguation, or error
    """
    start_time = time.time()

    # Use client_id for rate limiting, fall back to session_id
    rate_limit_id = client_id or session_id or "anonymous"

    # Step 1: Rate limiting check
    rate_limiter = get_rate_limiter()
    allowed, retry_after = rate_limiter.check(rate_limit_id)

    if not allowed:
        return error_response(
            error_type="rate_limited",
            message=f"Rate limit exceeded (60/min). Please wait.",
            retry_after=retry_after,
        )

    # Step 2: Get or create session
    session_store = get_session_store()
    session = session_store.get_or_create(session_id)

    # Step 3: Normalize query
    normalized, for_matching, time_modifier = normalize_query(query)

    # Handle empty query
    if not normalized.strip():
        return error_response(
            error_type="empty_query",
            message="Please enter a search term",
            suggestions=[
                "Try a team: 'Arsenal', 'Barcelona', 'Bayern'",
                "Try a league: 'La Liga standings', 'Serie A top scorers'",
                "Try a player: 'Salah', 'Mbappé', 'Bellingham'",
            ],
        )

    # Step 4: Extract entities
    alias_db = get_alias_database()
    entities = extract_entities(normalized, for_matching, alias_db, session)

    # Step 5: Classify intent (with LLM fallback if available)
    llm_provider = get_llm_provider()
    intent_result, _, _, _ = classify_intent(query, entities, session.to_dict(), llm_provider)

    # Attach time modifier if found during normalization
    if time_modifier and not intent_result.time_modifier:
        from .models.intent import IntentResult
        intent_result = IntentResult(
            intent_type=intent_result.intent_type,
            confidence=intent_result.confidence,
            time_modifier=time_modifier,
            used_llm=intent_result.used_llm,
            matched_pattern=intent_result.matched_pattern,
            raw_captures=intent_result.raw_captures,
        )

    # Step 6: Handle unknown/unsupported intent
    if intent_result.intent_type == IntentType.UNKNOWN:
        latency_ms = int((time.time() - start_time) * 1000)
        log_query(
            query=query,
            intent=None,
            intent_confidence=intent_result.confidence,
            entities_found=len(entities.all_entities),
            disambiguation_triggered=False,
            error_type="unknown_intent",
            latency_ms=latency_ms,
            used_llm=intent_result.used_llm,
        )
        # Record failed search for analytics
        record_search_result(
            query=query,
            success=False,
            error_reason="unknown_intent",
            error_message="Could not determine search intent",
            intent_detected=None,
            entities_found=[e.name for e in entities.all_entities] if entities.all_entities else None,
        )
        return error_response(
            error_type="unsupported_query",
            message="I'm not sure what you're looking for.",
            suggestions=[
                "Try a team: 'Real Madrid', 'Juventus', 'PSG'",
                "Try 'La Liga standings' or 'Bundesliga top scorers'",
                "Try 'Arsenal vs Chelsea' for head-to-head",
            ],
        )

    # Step 7: Resolve entities and check for disambiguation
    default_season = season or 2025
    default_league = league_id or 39

    resolved, disambiguation = resolve_query(
        intent_result,
        entities,
        session,
        default_league,
        default_season,
    )

    # Step 8: Handle disambiguation
    if disambiguation:
        latency_ms = int((time.time() - start_time) * 1000)
        log_query(
            query=query,
            intent=intent_result.intent_type.value,
            intent_confidence=intent_result.confidence,
            entities_found=len(entities.all_entities),
            disambiguation_triggered=True,
            error_type=None,
            latency_ms=latency_ms,
            used_llm=intent_result.used_llm,
        )
        return disambiguation_response(
            question=disambiguation.question,
            options=disambiguation.options,
        )

    # Step 9: Execute query
    result = execute_query(resolved, default_season)

    # Step 10: Format response
    latency_ms = int((time.time() - start_time) * 1000)
    response = format_response(
        resolved,
        result,
        query,
        normalized,
        latency_ms,
    )

    # Step 11: Update session
    if resolved.session_update:
        session_store.update(
            session.session_id,
            team_id=resolved.session_update.last_team_id,
            player_id=resolved.session_update.last_player_id,
            fixture_id=resolved.session_update.last_fixture_id,
            league_id=resolved.session_update.last_league_id,
            season=resolved.session_update.last_season,
            intent=resolved.session_update.last_intent,
        )

    # Step 12: Log query if needed
    log_query(
        query=query,
        intent=intent_result.intent_type.value,
        intent_confidence=intent_result.confidence,
        entities_found=len(entities.all_entities),
        disambiguation_triggered=False,
        error_type=result.error if not result.success else None,
        latency_ms=latency_ms,
        used_llm=intent_result.used_llm,
    )

    # Step 13: Record analytics
    if not result.success:
        record_search_result(
            query=query,
            success=False,
            error_reason=result.error or "execution_failed",
            error_message=str(result.data) if result.data else None,
            intent_detected=intent_result.intent_type.value,
            entities_found=[e.name for e in entities.all_entities] if entities.all_entities else None,
        )
    else:
        # Check for low confidence matches
        primary_entity = resolved.primary_player or resolved.primary_team
        if primary_entity and primary_entity.confidence < 0.85:
            record_search_result(
                query=query,
                success=True,
                result_type=response.type,
                confidence=primary_entity.confidence,
                matched_entity=primary_entity.name,
                entity_type="player" if resolved.primary_player else "team",
                match_method=primary_entity.match_method,
            )
        else:
            record_search_result(
                query=query,
                success=True,
                result_type=response.type,
            )

    return response


def search_with_session_id(
    query: str,
    session_id: str,
) -> tuple[SearchResponse, str]:
    """
    Search with explicit session handling.

    Returns tuple of (response, session_id) for session continuity.
    """
    response = search(query, session_id=session_id)

    # Extract session ID from response or return original
    if response.session_update:
        return response, session_id

    return response, session_id

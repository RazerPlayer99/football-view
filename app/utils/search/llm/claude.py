"""Claude LLM provider for search fallback.

IMPORTANT: Claude is ONLY used for:
- Intent classification when rule-based confidence < 0.7
- Entity extraction when fuzzy matching is ambiguous
- Pronoun resolution requiring context understanding

Claude is NEVER used for:
- Answering factual questions directly
- Generating match results, stats, or data
- Making predictions or opinions
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import LLMProvider
from ..models.intent import IntentType, IntentResult, TimeModifier
from ..models.entities import Entity, TeamEntity, PlayerEntity, CompetitionEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Prompt Templates
# ============================================================================

INTENT_CLASSIFICATION_PROMPT = """You are a search query classifier for a football/soccer statistics application.

TASK: Classify the user's query into exactly ONE of these intent types:
- STANDINGS: League table, standings, positions
- TOP_SCORERS: Goal scorers, golden boot, goal leaders
- TOP_ASSISTS: Assist leaders, playmakers
- MATCH_LOOKUP: Specific match, team vs team, fixture
- TEAM_LOOKUP: Team info, stats, form, squad
- PLAYER_LOOKUP: Player info, stats, profile
- SCHEDULE: Fixtures, upcoming/recent games
- COMPARISON: Comparing two teams or players
- CHART_REQUEST: Visualization, graph, chart
- UNKNOWN: Cannot determine

You must respond with ONLY a JSON object in this exact format:
{{"intent": "<INTENT_TYPE>", "confidence": <0.0-1.0>}}

RULES:
- Return ONLY the JSON object, no other text
- confidence should reflect how certain you are about the classification
- If the query is ambiguous, use UNKNOWN with low confidence
- DO NOT answer the query or provide any football facts

Query: {query}
{context_info}"""


ENTITY_EXTRACTION_PROMPT = """You are an entity extractor for a football/soccer statistics application.

TASK: Extract entity mentions from the query. Look for:
- team: Football team names (clubs, national teams)
- player: Football player names
- competition: League or tournament names

You must respond with ONLY a JSON array of entities:
[{{"type": "<entity_type>", "text": "<matched text>", "confidence": <0.0-1.0>}}]

RULES:
- Return ONLY the JSON array, no other text
- If no entities found, return empty array: []
- "text" should be the exact text from the query that mentions the entity
- DO NOT return entity IDs or look up real data
- DO NOT make up entity names that aren't in the query

{known_entities_info}

Query: {query}"""


PRONOUN_RESOLUTION_PROMPT = """You are resolving a pronoun reference in a football/soccer search query.

The user used the pronoun "{pronoun}" in their query.

Session context:
- Last team mentioned: {last_team} (ID: {last_team_id})
- Last player mentioned: {last_player} (ID: {last_player_id})
- Last fixture referenced: ID {last_fixture_id}
- Last competition: ID {last_league_id}

Query: {query}

TASK: Determine what the pronoun refers to from the context above.

Respond with ONLY a JSON object:
{{"entity_type": "<team|player|fixture|competition|null>", "entity_id": <id or null>}}

RULES:
- entity_type must be one of: team, player, fixture, competition, or null
- If the pronoun cannot be resolved from context, use null for both fields
- "he/him/his" usually refers to a player
- "they/them/their" usually refers to a team
- DO NOT make up references that aren't in the context"""


# ============================================================================
# Custom Exceptions
# ============================================================================

class ClaudeAPIError(Exception):
    """Raised when Claude API call fails."""
    pass


class ClaudeRateLimitError(ClaudeAPIError):
    """Raised when rate limited by Claude API."""
    pass


# ============================================================================
# ClaudeProvider Implementation
# ============================================================================

class ClaudeProvider(LLMProvider):
    """
    Claude LLM provider for search fallback.

    Uses Anthropic's Claude API for:
    - Intent classification (when rule-based < 0.70)
    - Entity extraction (when fuzzy matching is ambiguous)
    - Pronoun resolution (when session context is insufficient)
    """

    # Claude model to use - Haiku is fast and cheap for classification
    MODEL = "claude-3-haiku-20240307"

    # Max tokens for responses (classification tasks, not generation)
    MAX_TOKENS = 256

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Claude provider.

        Args:
            api_key: Anthropic API key. If not provided, reads from
                     ANTHROPIC_API_KEY environment variable.
        """
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        self._available = False

        if self._api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
                self._available = True
                logger.info("Claude provider initialized successfully")
            except ImportError:
                logger.warning("anthropic package not installed - LLM fallback disabled")
            except Exception as e:
                logger.warning(f"Failed to initialize Claude client: {e}")

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    # ========================================================================
    # Internal Methods
    # ========================================================================

    def _parse_json_response(self, response_text: str) -> Optional[Any]:
        """
        Parse JSON from Claude's response.

        Handles common issues like markdown code blocks.
        """
        text = response_text.strip()

        # Remove markdown code blocks if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```)
            lines = lines[1:]
            # Remove last line if it's ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Claude response as JSON: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ClaudeRateLimitError),
        reraise=True,
    )
    def _call_claude(self, prompt: str) -> str:
        """
        Make a call to Claude API with retry logic.

        Retries on rate limit errors with exponential backoff.
        Returns empty string on non-retryable errors.
        """
        if not self.is_available:
            return ""

        try:
            import anthropic

            message = self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )

            return message.content[0].text

        except anthropic.RateLimitError as e:
            logger.warning(f"Claude rate limit hit: {e}")
            raise ClaudeRateLimitError(str(e))

        except anthropic.APIConnectionError as e:
            logger.error(f"Claude connection error: {e}")
            return ""

        except anthropic.APIStatusError as e:
            logger.error(f"Claude API error: {e.status_code} - {e.message}")
            return ""

        except Exception as e:
            logger.error(f"Unexpected error calling Claude: {e}")
            return ""

    # ========================================================================
    # LLMProvider Interface Implementation
    # ========================================================================

    def classify_intent(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """Classify the intent of a search query using Claude."""
        context = context or {}

        # Build context info string
        context_info = ""
        if any(context.get(k) for k in ["last_team_id", "last_player_id", "last_intent"]):
            context_info = f"""
Context from session:
- Last team referenced: {context.get('last_team_name', 'None')}
- Last player referenced: {context.get('last_player_name', 'None')}
- Last intent: {context.get('last_intent', 'None')}"""

        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            query=query,
            context_info=context_info,
        )

        response = self._call_claude(prompt)
        if not response:
            # Graceful degradation - return low confidence UNKNOWN
            return IntentResult(
                intent_type=IntentType.UNKNOWN,
                confidence=0.0,
                used_llm=True,
            )

        # Parse response
        data = self._parse_json_response(response)
        if not data:
            return IntentResult(
                intent_type=IntentType.UNKNOWN,
                confidence=0.0,
                used_llm=True,
            )

        intent_str = data.get("intent", "UNKNOWN").upper()
        confidence = float(data.get("confidence", 0.5))

        try:
            intent_type = IntentType(intent_str)
        except ValueError:
            intent_type = IntentType.UNKNOWN
            confidence = min(confidence, 0.5)

        return IntentResult(
            intent_type=intent_type,
            confidence=confidence,
            used_llm=True,
        )

    def extract_entities(
        self,
        query: str,
        entity_types: List[str],
        known_entities: Optional[Dict[str, List[str]]] = None,
    ) -> List[Entity]:
        """Extract entity mentions from a query using Claude."""
        known_entities = known_entities or {}

        # Build known entities info
        known_info = ""
        if known_entities:
            teams = ", ".join(known_entities.get("teams", [])[:10])
            players = ", ".join(known_entities.get("players", [])[:10])
            competitions = ", ".join(known_entities.get("competitions", [])[:5])

            if teams or players or competitions:
                known_info = f"""
Known entities for reference (use these spellings if query is close):
Teams: {teams or 'None'}
Players: {players or 'None'}
Competitions: {competitions or 'None'}"""

        prompt = ENTITY_EXTRACTION_PROMPT.format(
            query=query,
            known_entities_info=known_info,
        )

        response = self._call_claude(prompt)
        if not response:
            return []

        data = self._parse_json_response(response)
        if not data or not isinstance(data, list):
            return []

        entities = []
        for item in data:
            entity_type = item.get("type", "").lower()
            text = item.get("text", "")
            confidence = float(item.get("confidence", 0.5))

            if not text or entity_type not in entity_types:
                continue

            if entity_type == "team":
                entities.append(TeamEntity(
                    team_id=0,  # Will be resolved later
                    name=text,
                    matched_text=text,
                    confidence=confidence,
                    match_method="llm_extraction",
                ))
            elif entity_type == "player":
                entities.append(PlayerEntity(
                    player_id=0,  # Will be resolved later
                    name=text,
                    matched_text=text,
                    confidence=confidence,
                    match_method="llm_extraction",
                ))
            elif entity_type == "competition":
                entities.append(CompetitionEntity(
                    league_id=0,  # Will be resolved later
                    name=text,
                    matched_text=text,
                    confidence=confidence,
                    match_method="llm_extraction",
                ))

        return entities

    def resolve_pronoun(
        self,
        pronoun: str,
        context: Dict[str, Any],
        query: str,
    ) -> Optional[tuple[str, int]]:
        """Resolve a pronoun to an entity using context."""
        prompt = PRONOUN_RESOLUTION_PROMPT.format(
            pronoun=pronoun,
            query=query,
            last_team=context.get("last_team_name", "None"),
            last_team_id=context.get("last_team_id", "None"),
            last_player=context.get("last_player_name", "None"),
            last_player_id=context.get("last_player_id", "None"),
            last_fixture_id=context.get("last_fixture_id", "None"),
            last_league_id=context.get("last_league_id", "None"),
        )

        response = self._call_claude(prompt)
        if not response:
            return None

        data = self._parse_json_response(response)
        if not data:
            return None

        entity_type = data.get("entity_type")
        entity_id = data.get("entity_id")

        if entity_type is None or entity_id is None or entity_type == "null":
            return None

        try:
            entity_id = int(entity_id)
        except (ValueError, TypeError):
            return None

        return (entity_type, entity_id)

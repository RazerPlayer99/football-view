"""
Live API client for API-Football
All data fetched directly from the API with validation and tiered caching
"""
import os
import logging
import time
import threading
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

from app.utils.search.entities import AliasDatabase, normalize_for_matching
from app.cache import get_cache_manager, CacheMeta
from config.settings import settings

load_dotenv()

# Configure logging for validation mismatches
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_client")

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
# Top 5 European Leagues
PREMIER_LEAGUE_ID = settings.premier_league_id
LA_LIGA_ID = 140
BUNDESLIGA_ID = 78
SERIE_A_ID = 135
LIGUE_1_ID = 61

# European Competitions
CHAMPIONS_LEAGUE_ID = 2

# All supported leagues for multi-league views
SUPPORTED_LEAGUES = {
    # Top 5 European Leagues
    PREMIER_LEAGUE_ID: "Premier League",
    LA_LIGA_ID: "La Liga",
    BUNDESLIGA_ID: "Bundesliga",
    SERIE_A_ID: "Serie A",
    LIGUE_1_ID: "Ligue 1",
    # European Competitions
    CHAMPIONS_LEAGUE_ID: "Champions League",
}

# Global semaphore to limit concurrent API requests across all parallel operations
# Prevents overwhelming the API when multiple ThreadPoolExecutors run simultaneously
_api_semaphore = threading.Semaphore(10)

# Response metadata storage (thread-local would be better for production)
_last_cache_meta: Optional[CacheMeta] = None

# Alias database for legacy API search helpers
_alias_db: Optional[AliasDatabase] = None


def _get_alias_db() -> AliasDatabase:
    """Get shared alias database for API client search helpers."""
    global _alias_db
    if _alias_db is None:
        _alias_db = AliasDatabase()
    return _alias_db


def _normalize_text(text: str) -> str:
    """Normalize text using the unified search normalizer."""
    return normalize_for_matching(text or "")


def _is_ambiguous_query(query: str) -> bool:
    """Check if a query is potentially ambiguous (very short or common name)."""
    normalized = _normalize_text(query)

    if len(normalized) <= 3:
        return True

    ambiguous_names = {
        "john", "james", "david", "michael", "chris", "christian",
        "daniel", "alex", "alexander", "martin", "marcus", "max",
        "ben", "jack", "joe", "sam", "matt", "luke", "ryan", "adam"
    }

    return normalized in ambiguous_names


def _score_player_match(player: Dict[str, Any], query: str) -> float:
    """Score how well a player matches the query."""
    normalized_query = _normalize_text(query)
    player_name = _normalize_text(player.get("name", ""))

    score = 0.0

    if player_name == normalized_query:
        score += 100
    elif player_name.startswith(normalized_query):
        score += 50
    elif normalized_query in player_name:
        score += 25

    appearances = player.get("appearances", 0) or 0
    score += min(appearances * 0.5, 20)

    goals = player.get("goals", 0) or 0
    assists = player.get("assists", 0) or 0
    score += min((goals + assists) * 0.3, 15)

    return score


def _rank_players(players: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Rank players by relevance to query."""
    scored = [(player, _score_player_match(player, query)) for player in players]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [player for player, score in scored]


def _cache_key(endpoint: str, params: dict) -> str:
    """Generate cache key from endpoint and params."""
    sorted_params = sorted((k, v) for k, v in params.items() if v is not None)
    return f"{endpoint}:{sorted_params}"


def _get_headers() -> dict:
    """Get API authentication headers."""
    return {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }


def _make_request(
    endpoint: str,
    params: dict,
    use_cache: bool = True,
    force_refresh: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Make API request with intelligent tiered caching.

    Args:
        endpoint: API endpoint path
        params: Query parameters
        use_cache: Whether to use caching (default True)
        force_refresh: Bypass cache and fetch fresh (default False)
        context: Additional context for TTL calculation (e.g., fixture_status)

    Returns:
        API response data
    """
    global _last_cache_meta

    cache_key = _cache_key(endpoint, params)
    cache_manager = get_cache_manager()

    def fetch():
        # Use semaphore to limit concurrent API requests globally
        with _api_semaphore:
            response = requests.get(
                f"{BASE_URL}/{endpoint}",
                headers=_get_headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

    if not use_cache:
        # No caching, but still coalesce concurrent requests
        data = cache_manager._coalescer.get_or_fetch(cache_key, fetch)
        _last_cache_meta = CacheMeta(
            last_updated=datetime.utcnow().isoformat() + "Z",
            cache_source="upstream",
        )
        return data

    # Use the full cache system
    data, meta = cache_manager.get(
        cache_key=cache_key,
        fetch_fn=fetch,
        endpoint=endpoint,
        params=params,
        force_refresh=force_refresh,
        context=context,
    )

    _last_cache_meta = meta
    return data


def get_last_cache_meta() -> Optional[CacheMeta]:
    """Get metadata from the most recent cache access."""
    return _last_cache_meta


def _safe_int(value, default: int = 0) -> int:
    """Safely convert value to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _validate_totals(
    player_id: int,
    totals: Dict[str, int],
    competitions: List[Dict[str, Any]],
    raw_response: Any = None
) -> Dict[str, Any]:
    """
    Validate that totals equal sum of competitions.
    Returns validation result with any mismatches logged.
    """
    sum_apps = sum(_safe_int(c.get("appearances")) for c in competitions)
    sum_goals = sum(_safe_int(c.get("goals")) for c in competitions)
    sum_assists = sum(_safe_int(c.get("assists")) for c in competitions)
    sum_minutes = sum(_safe_int(c.get("minutes")) for c in competitions)

    mismatches = []

    if totals["appearances"] != sum_apps:
        mismatches.append(f"appearances: total={totals['appearances']} vs sum={sum_apps}")
    if totals["goals"] != sum_goals:
        mismatches.append(f"goals: total={totals['goals']} vs sum={sum_goals}")
    if totals["assists"] != sum_assists:
        mismatches.append(f"assists: total={totals['assists']} vs sum={sum_assists}")
    if totals["minutes"] != sum_minutes:
        mismatches.append(f"minutes: total={totals['minutes']} vs sum={sum_minutes}")

    validation_result = {
        "valid": len(mismatches) == 0,
        "mismatches": mismatches,
    }

    if mismatches:
        logger.warning(
            f"VALIDATION MISMATCH - player_id={player_id}: {', '.join(mismatches)}"
        )
        if raw_response:
            logger.debug(f"Raw response for player_id={player_id}: {raw_response}")

    return validation_result


# ===== STANDINGS =====

def get_standings(
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get league standings for a season.

    Args:
        season: Season year (e.g., 2024 for 2024-25)
        league_id: League ID (default: Premier League)
        force_refresh: Bypass cache and fetch fresh data

    Returns:
        Dict with scope, season, league_id, and standings list
    """
    data = _make_request(
        "standings",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    response = data.get("response", [])
    if not response:
        return {
            "scope": "league_only",
            "season": season,
            "league_id": league_id,
            "standings": [],
        }

    standings_data = response[0].get("league", {}).get("standings", [[]])[0]

    standings = []
    for team in standings_data:
        all_stats = team.get("all", {})
        home_stats = team.get("home", {})
        away_stats = team.get("away", {})
        goals = all_stats.get("goals", {})
        home_goals = home_stats.get("goals", {})
        away_goals = away_stats.get("goals", {})

        standings.append({
            "position": team.get("rank"),
            "team": {
                "id": team.get("team", {}).get("id"),
                "name": team.get("team", {}).get("name"),
                "logo": team.get("team", {}).get("logo"),
            },
            "played": all_stats.get("played", 0),
            "won": all_stats.get("win", 0),
            "drawn": all_stats.get("draw", 0),
            "lost": all_stats.get("lose", 0),
            "goals_for": goals.get("for", 0),
            "goals_against": goals.get("against", 0),
            "goal_difference": team.get("goalsDiff", 0),
            "points": team.get("points", 0),
            "form": team.get("form"),
            # Home/Away splits
            "home": {
                "played": home_stats.get("played", 0),
                "won": home_stats.get("win", 0),
                "drawn": home_stats.get("draw", 0),
                "lost": home_stats.get("lose", 0),
                "goals_for": home_goals.get("for", 0),
                "goals_against": home_goals.get("against", 0),
            },
            "away": {
                "played": away_stats.get("played", 0),
                "won": away_stats.get("win", 0),
                "drawn": away_stats.get("draw", 0),
                "lost": away_stats.get("lose", 0),
                "goals_for": away_goals.get("for", 0),
                "goals_against": away_goals.get("against", 0),
            },
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "standings": standings,
    }


# ===== TEAMS =====

def get_teams(
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get all teams for a league/season.

    Returns:
        Dict with scope, season, league_id, and teams list
    """
    data = _make_request(
        "teams",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    teams = []
    for item in data.get("response", []):
        team = item.get("team", {})
        venue = item.get("venue", {})
        teams.append({
            "id": team.get("id"),
            "name": team.get("name"),
            "logo": team.get("logo"),
            "venue": venue.get("name"),
            "city": venue.get("city"),
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "teams": teams,
    }


def get_team_by_id(team_id: int) -> Optional[Dict[str, Any]]:
    """Get team details by ID."""
    data = _make_request("teams", {"id": team_id})

    response = data.get("response", [])
    if not response:
        return None

    item = response[0]
    team = item.get("team", {})
    venue = item.get("venue", {})

    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "logo": team.get("logo"),
        "venue": venue.get("name"),
        "city": venue.get("city"),
        "country": team.get("country"),
        "founded": team.get("founded"),
    }


# ===== MATCHES / FIXTURES =====

def get_matches(
    season: int,
    league_id: Optional[int] = PREMIER_LEAGUE_ID,
    team_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Get matches for a league/season.

    Args:
        season: Season year
        league_id: League ID to filter by. Pass None to get all leagues (requires team_id).
        team_id: Optional team ID to filter matches
        from_date: Optional start date (YYYY-MM-DD)
        to_date: Optional end date (YYYY-MM-DD)
        limit: Max matches to return

    Returns:
        Dict with scope, season, league_id, and matches list
    """
    params = {
        "season": season,
    }
    # Only add league filter if specified (allows cross-league team queries)
    if league_id is not None:
        params["league"] = league_id
    if team_id:
        params["team"] = team_id
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date

    data = _make_request("fixtures", params)

    matches = []
    for fixture in data.get("response", [])[:limit]:
        fixture_info = fixture.get("fixture", {})
        league_info = fixture.get("league", {})
        teams = fixture.get("teams", {})
        goals = fixture.get("goals", {})
        score = fixture.get("score", {})

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is not None and away_goals is not None:
            if home_goals > away_goals:
                result = "H"
            elif away_goals > home_goals:
                result = "A"
            else:
                result = "D"
        else:
            result = None

        matches.append({
            "id": fixture_info.get("id"),
            "date": fixture_info.get("date"),
            "venue": fixture_info.get("venue", {}).get("name"),
            "referee": fixture_info.get("referee"),
            "status": fixture_info.get("status", {}).get("long"),
            "home_team": {
                "id": teams.get("home", {}).get("id"),
                "name": teams.get("home", {}).get("name"),
                "logo": teams.get("home", {}).get("logo"),
            },
            "away_team": {
                "id": teams.get("away", {}).get("id"),
                "name": teams.get("away", {}).get("name"),
                "logo": teams.get("away", {}).get("logo"),
            },
            "home_goals": home_goals,
            "away_goals": away_goals,
            "result": result,
            "halftime": score.get("halftime"),
            "fulltime": score.get("fulltime"),
            "competition": league_info.get("name", SUPPORTED_LEAGUES.get(league_id, "Unknown")),
            "league_id": league_info.get("id", league_id),
            "league_logo": league_info.get("logo"),
            "round": league_info.get("round"),
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "matches": matches,
    }


def get_matches_multi_league(
    season: int,
    league_ids: Optional[List[int]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit_per_league: int = 50,
) -> Dict[str, Any]:
    """
    Get matches from multiple leagues in parallel.

    Args:
        season: Season year
        league_ids: List of league IDs to fetch (defaults to SUPPORTED_LEAGUES)
        from_date: Start date filter (YYYY-MM-DD)
        to_date: End date filter (YYYY-MM-DD)
        limit_per_league: Max matches per league

    Returns:
        Dict with matches grouped by competition and a flat all_matches list
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if league_ids is None:
        league_ids = list(SUPPORTED_LEAGUES.keys())

    all_matches = []
    by_competition = {}

    def fetch_league(league_id):
        return get_matches(
            season=season,
            league_id=league_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit_per_league,
        )

    # Fetch all leagues in parallel
    with ThreadPoolExecutor(max_workers=len(league_ids)) as executor:
        future_to_league = {
            executor.submit(fetch_league, lid): lid
            for lid in league_ids
        }

        for future in as_completed(future_to_league):
            league_id = future_to_league[future]
            try:
                result = future.result()
                matches = result.get("matches", [])

                # Add to flat list
                all_matches.extend(matches)

                # Group by competition name
                for match in matches:
                    comp_name = match.get("competition", SUPPORTED_LEAGUES.get(league_id, "Unknown"))
                    if comp_name not in by_competition:
                        by_competition[comp_name] = []
                    by_competition[comp_name].append(match)

            except Exception as e:
                logger.error(f"Error fetching league {league_id}: {e}")

    # Sort all matches by date
    all_matches.sort(key=lambda m: m.get("date", "") or "")

    # Sort matches within each competition by date
    for comp in by_competition:
        by_competition[comp].sort(key=lambda m: m.get("date", "") or "")

    return {
        "scope": "multi_league",
        "season": season,
        "league_ids": league_ids,
        "all_matches": all_matches,
        "by_competition": by_competition,
    }


def get_match_by_id(
    match_id: int,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Get match details by fixture ID.

    Returns enhanced match data including status codes, elapsed time, and league info.
    """
    data = _make_request(
        "fixtures",
        {"id": match_id},
        force_refresh=force_refresh,
    )

    response = data.get("response", [])
    if not response:
        return None

    fixture = response[0]
    fixture_info = fixture.get("fixture", {})
    teams = fixture.get("teams", {})
    goals = fixture.get("goals", {})
    score = fixture.get("score", {})
    league = fixture.get("league", {})
    status = fixture_info.get("status", {})

    home_goals = goals.get("home")
    away_goals = goals.get("away")

    if home_goals is not None and away_goals is not None:
        if home_goals > away_goals:
            result = "H"
        elif away_goals > home_goals:
            result = "A"
        else:
            result = "D"
    else:
        result = None

    # Determine live/finished status
    status_short = status.get("short", "")
    is_live = status_short in ("1H", "2H", "HT", "ET", "P", "BT", "LIVE")
    is_finished = status_short in ("FT", "AET", "PEN")

    return {
        "id": fixture_info.get("id"),
        "date": fixture_info.get("date"),
        "venue": fixture_info.get("venue", {}).get("name"),
        "referee": fixture_info.get("referee"),
        "status": status.get("long"),
        "status_short": status_short,
        "elapsed": status.get("elapsed"),
        "extra_time": status.get("extra"),
        "is_live": is_live,
        "is_finished": is_finished,
        "home_team": {
            "id": teams.get("home", {}).get("id"),
            "name": teams.get("home", {}).get("name"),
            "logo": teams.get("home", {}).get("logo"),
        },
        "away_team": {
            "id": teams.get("away", {}).get("id"),
            "name": teams.get("away", {}).get("name"),
            "logo": teams.get("away", {}).get("logo"),
        },
        "home_goals": home_goals,
        "away_goals": away_goals,
        "result": result,
        "halftime": score.get("halftime"),
        "fulltime": score.get("fulltime"),
        "league": {
            "id": league.get("id"),
            "name": league.get("name"),
            "logo": league.get("logo"),
            "round": league.get("round"),
        },
    }


def get_match_events(
    match_id: int,
    force_refresh: bool = False,
    fixture_status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get match events (goals, cards, substitutions) for a fixture.

    Args:
        match_id: The fixture ID
        force_refresh: Bypass cache
        fixture_status: Status for cache TTL determination (e.g., "FT", "1H")

    Returns:
        Dict with fixture_id and list of events
    """
    context = {"fixture_status": fixture_status} if fixture_status else {}

    data = _make_request(
        "fixtures/events",
        {"fixture": match_id},
        force_refresh=force_refresh,
        context=context,
    )

    events = []
    for event in data.get("response", []):
        time_data = event.get("time", {})
        team_data = event.get("team", {})
        player_data = event.get("player", {})
        assist_data = event.get("assist", {})

        events.append({
            "minute": time_data.get("elapsed"),
            "extra_time": time_data.get("extra"),
            "team_id": team_data.get("id"),
            "team_name": team_data.get("name"),
            "team_logo": team_data.get("logo"),
            "player_id": player_data.get("id"),
            "player_name": player_data.get("name"),
            "assist_id": assist_data.get("id"),
            "assist_name": assist_data.get("name"),
            "event_type": event.get("type"),  # Goal, Card, Subst, Var
            "detail": event.get("detail"),     # Normal Goal, Yellow Card, etc.
            "comments": event.get("comments"),
        })

    return {
        "fixture_id": match_id,
        "events": events,
    }


def get_match_lineups(
    match_id: int,
    force_refresh: bool = False,
    fixture_status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get match lineups (starting XI, substitutes, formation) for a fixture.

    Args:
        match_id: The fixture ID
        force_refresh: Bypass cache
        fixture_status: Status for cache TTL determination

    Returns:
        Dict with fixture_id and lineups for both teams
    """
    context = {"fixture_status": fixture_status} if fixture_status else {}

    data = _make_request(
        "fixtures/lineups",
        {"fixture": match_id},
        force_refresh=force_refresh,
        context=context,
    )

    lineups = []
    for team_lineup in data.get("response", []):
        team_data = team_lineup.get("team", {})
        coach_data = team_lineup.get("coach", {})

        # Parse starting XI
        starting_xi = []
        for player in team_lineup.get("startXI", []):
            p = player.get("player", {})
            starting_xi.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "number": p.get("number"),
                "position": p.get("pos"),
                "grid": p.get("grid"),  # Position on formation grid
            })

        # Parse substitutes
        substitutes = []
        for player in team_lineup.get("substitutes", []):
            p = player.get("player", {})
            substitutes.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "number": p.get("number"),
                "position": p.get("pos"),
            })

        lineups.append({
            "team_id": team_data.get("id"),
            "team_name": team_data.get("name"),
            "team_logo": team_data.get("logo"),
            "formation": team_lineup.get("formation"),
            "coach_id": coach_data.get("id"),
            "coach_name": coach_data.get("name"),
            "coach_photo": coach_data.get("photo"),
            "starting_xi": starting_xi,
            "substitutes": substitutes,
        })

    return {
        "fixture_id": match_id,
        "lineups": lineups,
    }


def get_match_statistics(
    match_id: int,
    force_refresh: bool = False,
    fixture_status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get match statistics (possession, shots, fouls, etc.) for a fixture.

    Args:
        match_id: The fixture ID
        force_refresh: Bypass cache
        fixture_status: Status for cache TTL determination

    Returns:
        Dict with fixture_id and statistics for both teams
    """
    context = {"fixture_status": fixture_status} if fixture_status else {}

    data = _make_request(
        "fixtures/statistics",
        {"fixture": match_id},
        force_refresh=force_refresh,
        context=context,
    )

    team_stats = []
    for team_data in data.get("response", []):
        team_info = team_data.get("team", {})

        # Convert statistics list to dict for easier access
        stats_dict = {}
        for stat in team_data.get("statistics", []):
            stat_type = stat.get("type")
            stat_value = stat.get("value")
            if stat_type:
                stats_dict[stat_type] = stat_value

        team_stats.append({
            "team_id": team_info.get("id"),
            "team_name": team_info.get("name"),
            "team_logo": team_info.get("logo"),
            "statistics": stats_dict,
        })

    return {
        "fixture_id": match_id,
        "team_statistics": team_stats,
    }


# ===== PLAYERS =====

def get_top_scorers(
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 20,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get top scorers for a league/season.

    Returns:
        Dict with scope, season, league_id, and players list
    """
    data = _make_request(
        "players/topscorers",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    players = []
    for item in data.get("response", [])[:limit]:
        player = item.get("player", {})
        stats = item.get("statistics", [{}])[0]
        games = stats.get("games", {})
        goals_data = stats.get("goals", {})
        cards = stats.get("cards", {})

        players.append({
            "id": player.get("id"),
            "name": player.get("name"),
            "photo": player.get("photo"),
            "nationality": player.get("nationality"),
            "age": player.get("age"),
            "team": {
                "id": stats.get("team", {}).get("id"),
                "name": stats.get("team", {}).get("name"),
                "logo": stats.get("team", {}).get("logo"),
            },
            "position": games.get("position"),
            "appearances": _safe_int(games.get("appearences")),
            "minutes_played": _safe_int(games.get("minutes")),
            "goals": _safe_int(goals_data.get("total")),
            "assists": _safe_int(goals_data.get("assists")),
            "yellow_cards": _safe_int(cards.get("yellow")),
            "red_cards": _safe_int(cards.get("red")),
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "players": players,
    }


def get_top_assists(
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 20,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get top assist providers for a league/season.

    Returns:
        Dict with scope, season, league_id, and players list
    """
    data = _make_request(
        "players/topassists",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    players = []
    for item in data.get("response", [])[:limit]:
        player = item.get("player", {})
        stats = item.get("statistics", [{}])[0]
        games = stats.get("games", {})
        goals_data = stats.get("goals", {})

        players.append({
            "id": player.get("id"),
            "name": player.get("name"),
            "photo": player.get("photo"),
            "nationality": player.get("nationality"),
            "age": player.get("age"),
            "team": {
                "id": stats.get("team", {}).get("id"),
                "name": stats.get("team", {}).get("name"),
                "logo": stats.get("team", {}).get("logo"),
            },
            "position": games.get("position"),
            "appearances": _safe_int(games.get("appearences")),
            "goals": _safe_int(goals_data.get("total")),
            "assists": _safe_int(goals_data.get("assists")),
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "players": players,
    }


def get_top_yellow_cards(
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 20,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get players with most yellow cards for a league/season.
    """
    data = _make_request(
        "players/topyellowcards",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    players = []
    for item in data.get("response", [])[:limit]:
        player = item.get("player", {})
        stats = item.get("statistics", [{}])[0]
        games = stats.get("games", {})
        cards = stats.get("cards", {})

        players.append({
            "id": player.get("id"),
            "name": player.get("name"),
            "photo": player.get("photo"),
            "team": {
                "id": stats.get("team", {}).get("id"),
                "name": stats.get("team", {}).get("name"),
                "logo": stats.get("team", {}).get("logo"),
            },
            "position": games.get("position"),
            "appearances": _safe_int(games.get("appearences")),
            "yellow_cards": _safe_int(cards.get("yellow")),
            "red_cards": _safe_int(cards.get("red")),
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "players": players,
    }


def get_top_red_cards(
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 20,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get players with most red cards for a league/season.
    """
    data = _make_request(
        "players/topredcards",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    players = []
    for item in data.get("response", [])[:limit]:
        player = item.get("player", {})
        stats = item.get("statistics", [{}])[0]
        games = stats.get("games", {})
        cards = stats.get("cards", {})

        players.append({
            "id": player.get("id"),
            "name": player.get("name"),
            "photo": player.get("photo"),
            "team": {
                "id": stats.get("team", {}).get("id"),
                "name": stats.get("team", {}).get("name"),
                "logo": stats.get("team", {}).get("logo"),
            },
            "position": games.get("position"),
            "appearances": _safe_int(games.get("appearences")),
            "yellow_cards": _safe_int(cards.get("yellow")),
            "red_cards": _safe_int(cards.get("red")),
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "players": players,
    }


def get_top_scorers_detailed(
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 20,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get top scorers with full detailed statistics including shots, passes, tackles, etc.
    """
    data = _make_request(
        "players/topscorers",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    players = []
    for item in data.get("response", [])[:limit]:
        player = item.get("player", {})
        stats = item.get("statistics", [{}])[0]
        games = stats.get("games", {})
        goals_data = stats.get("goals", {})
        cards = stats.get("cards", {})
        shots = stats.get("shots", {})
        passes = stats.get("passes", {})
        tackles = stats.get("tackles", {})
        duels = stats.get("duels", {})
        dribbles = stats.get("dribbles", {})
        fouls = stats.get("fouls", {})
        penalty = stats.get("penalty", {})

        players.append({
            "id": player.get("id"),
            "name": player.get("name"),
            "photo": player.get("photo"),
            "nationality": player.get("nationality"),
            "team": {
                "id": stats.get("team", {}).get("id"),
                "name": stats.get("team", {}).get("name"),
                "logo": stats.get("team", {}).get("logo"),
            },
            "position": games.get("position"),
            "rating": games.get("rating"),
            "appearances": _safe_int(games.get("appearences")),
            "minutes": _safe_int(games.get("minutes")),
            "goals": _safe_int(goals_data.get("total")),
            "assists": _safe_int(goals_data.get("assists")),
            "shots_total": _safe_int(shots.get("total")),
            "shots_on": _safe_int(shots.get("on")),
            "passes_total": _safe_int(passes.get("total")),
            "key_passes": _safe_int(passes.get("key")),
            "tackles": _safe_int(tackles.get("total")),
            "blocks": _safe_int(tackles.get("blocks")),
            "interceptions": _safe_int(tackles.get("interceptions")),
            "duels_total": _safe_int(duels.get("total")),
            "duels_won": _safe_int(duels.get("won")),
            "dribbles_attempts": _safe_int(dribbles.get("attempts")),
            "dribbles_success": _safe_int(dribbles.get("success")),
            "fouls_drawn": _safe_int(fouls.get("drawn")),
            "fouls_committed": _safe_int(fouls.get("committed")),
            "yellow_cards": _safe_int(cards.get("yellow")),
            "red_cards": _safe_int(cards.get("red")),
            "penalty_scored": _safe_int(penalty.get("scored")),
            "penalty_missed": _safe_int(penalty.get("missed")),
        })

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "players": players,
    }


# ===== INJURIES =====

def get_injuries_by_league(
    league_id: int = PREMIER_LEAGUE_ID,
    season: int = settings.current_season,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get all injuries for a league/season.

    Returns:
        Dict with scope, season, league_id, and injuries list
    """
    data = _make_request(
        "injuries",
        {"league": league_id, "season": season},
        force_refresh=force_refresh,
    )

    injuries = []
    for item in data.get("response", []):
        player = item.get("player", {})
        team = item.get("team", {})
        fixture = item.get("fixture", {})

        injuries.append({
            "player_id": player.get("id"),
            "player_name": player.get("name"),
            "player_photo": player.get("photo"),
            "player_type": player.get("type"),  # e.g., "Missing Fixture"
            "player_reason": player.get("reason"),  # e.g., "Knee Injury"
            "team_id": team.get("id"),
            "team_name": team.get("name"),
            "team_logo": team.get("logo"),
            "fixture_id": fixture.get("id"),
            "fixture_date": fixture.get("date"),
        })

    return {
        "scope": "league",
        "season": season,
        "league_id": league_id,
        "injuries": injuries,
        "count": len(injuries),
    }


def get_injuries_by_team(
    team_id: int,
    season: int = settings.current_season,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Get injuries for a specific team.

    Returns:
        Dict with scope, season, team_id, and injuries list
    """
    data = _make_request(
        "injuries",
        {"team": team_id, "season": season},
        force_refresh=force_refresh,
    )

    injuries = []
    injured_player_ids = set()

    for item in data.get("response", []):
        player = item.get("player", {})
        team = item.get("team", {})
        fixture = item.get("fixture", {})

        player_id = player.get("id")
        if player_id:
            injured_player_ids.add(player_id)

        injuries.append({
            "player_id": player_id,
            "player_name": player.get("name"),
            "player_photo": player.get("photo"),
            "injury_type": player.get("type"),  # e.g., "Missing Fixture"
            "injury_reason": player.get("reason"),  # e.g., "Knee Injury"
            "team_id": team.get("id"),
            "team_name": team.get("name"),
            "fixture_id": fixture.get("id"),
            "fixture_date": fixture.get("date"),
        })

    return {
        "scope": "team",
        "season": season,
        "team_id": team_id,
        "injuries": injuries,
        "injured_player_ids": list(injured_player_ids),
        "count": len(injuries),
    }


# ===== TEAM DASHBOARD HELPERS =====

def get_team_fixtures(
    team_id: int,
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 15,
) -> Dict[str, Any]:
    """
    Get team fixtures split into past and future matches.

    Returns:
        Dict with past, future, next_fixture, and last_5 results
    """
    from datetime import datetime

    result = get_matches(season, league_id, team_id=team_id, limit=limit * 2)
    all_matches = result.get("matches", [])

    now = datetime.now().isoformat()

    past = []
    future = []

    for match in all_matches:
        match_date = match.get("date", "")
        status = match.get("status", "")

        # Finished matches go to past
        if status in ("Match Finished", "FT", "AET", "PEN"):
            past.append(match)
        # Upcoming/scheduled matches go to future
        elif match_date > now or status in ("Not Started", "TBD", "NS"):
            future.append(match)
        else:
            # Live or other statuses - treat as past for now
            past.append(match)

    # Sort past by date descending (most recent first)
    past.sort(key=lambda m: m.get("date", ""), reverse=True)
    # Sort future by date ascending (soonest first)
    future.sort(key=lambda m: m.get("date", ""))

    # Limit results
    past = past[:limit]
    future = future[:limit]

    return {
        "team_id": team_id,
        "season": season,
        "past": past,
        "future": future,
        "next_fixture": future[0] if future else None,
        "last_5": past[:5],
    }


def get_team_top_scorers(
    team_id: int,
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Get top scorers filtered to a specific team.

    Returns:
        List of players with goals from the team
    """
    result = get_top_scorers(season, league_id, limit=50)
    players = result.get("players", [])

    team_players = [
        p for p in players
        if p.get("team", {}).get("id") == team_id
    ]

    return team_players[:limit]


def get_team_top_assists(
    team_id: int,
    season: int,
    league_id: int = PREMIER_LEAGUE_ID,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Get top assist providers filtered to a specific team.

    Returns:
        List of players with assists from the team
    """
    result = get_top_assists(season, league_id, limit=50)
    players = result.get("players", [])

    team_players = [
        p for p in players
        if p.get("team", {}).get("id") == team_id
    ]

    return team_players[:limit]


def get_player_by_id(
    player_id: int,
    season: int,
    scope: str = "all_competitions"
) -> Optional[Dict[str, Any]]:
    """
    Get detailed player stats by ID.

    Args:
        player_id: Player ID
        season: Season year
        scope: "all_competitions" or "league_only" (Premier League only)

    Returns:
        Dict with player info, validation status, and stats
    """
    data = _make_request("players", {
        "id": player_id,
        "season": season,
    })

    response = data.get("response", [])
    if not response:
        return None

    item = response[0]
    player = item.get("player", {})
    raw_stats = item.get("statistics", [])

    # Process all competitions
    total_goals = 0
    total_assists = 0
    total_apps = 0
    total_minutes = 0
    pl_stats = None

    competitions = []
    for stats in raw_stats:
        league = stats.get("league", {})
        games = stats.get("games", {})
        goals_data = stats.get("goals", {})
        cards = stats.get("cards", {})

        goals = _safe_int(goals_data.get("total"))
        assists = _safe_int(goals_data.get("assists"))
        apps = _safe_int(games.get("appearences"))
        minutes = _safe_int(games.get("minutes"))

        total_goals += goals
        total_assists += assists
        total_apps += apps
        total_minutes += minutes

        comp_stats = {
            "league_id": league.get("id"),
            "league": league.get("name"),
            "team_id": stats.get("team", {}).get("id"),
            "team": stats.get("team", {}).get("name"),
            "appearances": apps,
            "minutes": minutes,
            "goals": goals,
            "assists": assists,
            "yellow_cards": _safe_int(cards.get("yellow")),
            "red_cards": _safe_int(cards.get("red")),
            "shots": stats.get("shots", {}).get("total"),
            "shots_on_target": stats.get("shots", {}).get("on"),
            "key_passes": stats.get("passes", {}).get("key"),
            "dribbles_success": stats.get("dribbles", {}).get("success"),
            "dribbles_attempts": stats.get("dribbles", {}).get("attempts"),
        }
        competitions.append(comp_stats)

        # Store Premier League stats separately
        if league.get("id") == PREMIER_LEAGUE_ID:
            pl_stats = comp_stats

    # Build totals dict
    totals = {
        "appearances": total_apps,
        "minutes": total_minutes,
        "goals": total_goals,
        "assists": total_assists,
    }

    # Validate totals vs sum of competitions
    validation = _validate_totals(player_id, totals, competitions, item)

    # Filter to Premier League only if requested
    if scope == "league_only":
        competitions = [c for c in competitions if c.get("league_id") == PREMIER_LEAGUE_ID]
        if pl_stats:
            totals = {
                "appearances": pl_stats["appearances"],
                "minutes": pl_stats["minutes"],
                "goals": pl_stats["goals"],
                "assists": pl_stats["assists"],
            }
        else:
            totals = {"appearances": 0, "minutes": 0, "goals": 0, "assists": 0}

    return {
        "scope": scope,
        "season": season,
        "id": player.get("id"),
        "name": player.get("name"),
        "photo": player.get("photo"),
        "nationality": player.get("nationality"),
        "age": player.get("age"),
        "height": player.get("height"),
        "weight": player.get("weight"),
        "season_totals": totals,
        "premier_league": pl_stats,
        "competitions": competitions,
        "validation": validation,
    }


def get_team_players(
    team_id: int,
    season: int,
    league_id: Optional[int] = PREMIER_LEAGUE_ID
) -> Dict[str, Any]:
    """
    Get all players for a team in a season.

    Args:
        team_id: Team ID
        season: Season year
        league_id: League ID for stats. Pass None to get players across all leagues.

    Returns:
        Dict with scope, season, league_id, team_id, and players list
    """
    params = {
        "team": team_id,
        "season": season,
    }
    if league_id is not None:
        params["league"] = league_id

    data = _make_request("players", params)

    players = []
    for item in data.get("response", []):
        player = item.get("player", {})
        stats = item.get("statistics", [{}])[0]
        games = stats.get("games", {})
        goals_data = stats.get("goals", {})
        cards = stats.get("cards", {})

        players.append({
            "id": player.get("id"),
            "name": player.get("name"),
            "photo": player.get("photo"),
            "nationality": player.get("nationality"),
            "age": player.get("age"),
            "position": games.get("position"),
            "appearances": _safe_int(games.get("appearences")),
            "minutes_played": _safe_int(games.get("minutes")),
            "goals": _safe_int(goals_data.get("total")),
            "assists": _safe_int(goals_data.get("assists")),
            "yellow_cards": _safe_int(cards.get("yellow")),
            "red_cards": _safe_int(cards.get("red")),
        })

    players.sort(key=lambda p: p["appearances"], reverse=True)

    return {
        "scope": "league_only",
        "season": season,
        "league_id": league_id,
        "team_id": team_id,
        "players": players,
    }


# ===== PLAYER MATCH LOG (Phase B) =====

def get_player_match_log(
    player_id: int,
    season: int,
    league_id: Optional[int] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Get player's recent match appearances with per-game stats.

    Args:
        player_id: Player ID
        season: Season year
        league_id: Optional league filter (None = all competitions)
        limit: Max matches to return (default 10)

    Returns:
        Dict with scope, season, player_id, and matches list
    """
    params = {
        "id": player_id,
        "season": season,
    }
    if league_id:
        params["league"] = league_id

    # Use fixtures/players endpoint for player-specific fixture data
    data = _make_request("players/fixtures", params)

    # If that endpoint doesn't work, fallback to getting player's team fixtures
    # and checking their participation
    if not data.get("response"):
        # Get player info first to find their team
        player_data = _make_request("players", {"id": player_id, "season": season})
        player_response = player_data.get("response", [])

        if not player_response:
            return {
                "scope": "league_only" if league_id else "all_competitions",
                "season": season,
                "league_id": league_id,
                "player_id": player_id,
                "matches": [],
                "error": "Player not found",
            }

        # Get team ID from first stats entry
        stats = player_response[0].get("statistics", [])
        if not stats:
            return {
                "scope": "league_only" if league_id else "all_competitions",
                "season": season,
                "league_id": league_id,
                "player_id": player_id,
                "matches": [],
                "error": "No team found for player",
            }

        team_id = stats[0].get("team", {}).get("id")

        # Get team fixtures and filter for player
        fixture_params = {
            "team": team_id,
            "season": season,
            "status": "FT",  # Only finished matches
        }
        if league_id:
            fixture_params["league"] = league_id

        fixture_data = _make_request("fixtures", fixture_params)
        fixtures = fixture_data.get("response", [])

        # Sort fixtures by date (most recent first) before selecting
        fixtures.sort(key=lambda f: f.get("fixture", {}).get("date", ""), reverse=True)

        # Take only the most recent N fixtures
        recent_fixtures = fixtures[:limit]

        # Get player stats for each fixture in parallel for faster load times
        def fetch_fixture_stats(fixture: Dict) -> Optional[Dict]:
            """Fetch stats for a single fixture."""
            fixture_id = fixture.get("fixture", {}).get("id")
            if not fixture_id:
                return None
            try:
                return _get_player_fixture_stats(fixture_id, player_id, fixture)
            except Exception as e:
                logger.warning(f"Failed to get fixture {fixture_id} for player {player_id}: {e}")
                return None

        matches = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_fixture_stats, f): f for f in recent_fixtures}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    matches.append(result)

        # Re-sort by date since parallel execution doesn't preserve order
        matches.sort(key=lambda m: m.get("date", ""), reverse=True)

        return {
            "scope": "league_only" if league_id else "all_competitions",
            "season": season,
            "league_id": league_id,
            "player_id": player_id,
            "matches": matches,
        }

    # Process direct response
    matches = []
    for match in data.get("response", [])[:limit]:
        matches.append(_format_player_match(match))

    return {
        "scope": "league_only" if league_id else "all_competitions",
        "season": season,
        "league_id": league_id,
        "player_id": player_id,
        "matches": matches,
    }


def _get_player_fixture_stats(
    fixture_id: int,
    player_id: int,
    prefetched_fixture: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    Get player stats for a specific fixture.

    Args:
        fixture_id: The fixture ID
        player_id: The player ID to find stats for
        prefetched_fixture: Optional pre-fetched fixture data to avoid extra API call
    """
    # Get player stats for this fixture
    data = _make_request("fixtures/players", {
        "fixture": fixture_id,
    })

    response = data.get("response", [])
    if not response:
        return None

    # Find player in the fixture data
    for team_data in response:
        team = team_data.get("team", {})
        players = team_data.get("players", [])

        for p in players:
            if p.get("player", {}).get("id") == player_id:
                stats = p.get("statistics", [{}])[0]
                games = stats.get("games", {})
                goals_data = stats.get("goals", {})
                cards = stats.get("cards", {})

                # Use prefetched fixture data if available, otherwise fetch
                if prefetched_fixture:
                    fixture = prefetched_fixture
                else:
                    fixture_data = _make_request("fixtures", {"id": fixture_id})
                    fixture = fixture_data.get("response", [{}])[0] if fixture_data.get("response") else {}

                fixture_info = fixture.get("fixture", {})
                teams = fixture.get("teams", {})
                score = fixture.get("goals", {})
                league = fixture.get("league", {})

                return {
                    "fixture_id": fixture_id,
                    "date": fixture_info.get("date"),
                    "league": league.get("name"),
                    "league_id": league.get("id"),
                    "home_team": teams.get("home", {}).get("name"),
                    "away_team": teams.get("away", {}).get("name"),
                    "score": f"{score.get('home', 0)}-{score.get('away', 0)}",
                    "team": team.get("name"),
                    "position": games.get("position"),
                    "minutes": _safe_int(games.get("minutes")),
                    "rating": stats.get("games", {}).get("rating"),
                    "goals": _safe_int(goals_data.get("total")),
                    "assists": _safe_int(goals_data.get("assists")),
                    "yellow_cards": _safe_int(cards.get("yellow")),
                    "red_cards": _safe_int(cards.get("red")),
                    "shots": _safe_int(stats.get("shots", {}).get("total")),
                    "shots_on_target": _safe_int(stats.get("shots", {}).get("on")),
                    "passes": _safe_int(stats.get("passes", {}).get("total")),
                    "pass_accuracy": stats.get("passes", {}).get("accuracy"),
                    "key_passes": _safe_int(stats.get("passes", {}).get("key")),
                    "dribbles_attempts": _safe_int(stats.get("dribbles", {}).get("attempts")),
                    "dribbles_success": _safe_int(stats.get("dribbles", {}).get("success")),
                }

    return None


def _format_player_match(match: dict) -> Dict[str, Any]:
    """Format player match data."""
    fixture = match.get("fixture", {})
    league = match.get("league", {})
    teams = match.get("teams", {})
    goals = match.get("goals", {})
    stats = match.get("statistics", {})

    return {
        "fixture_id": fixture.get("id"),
        "date": fixture.get("date"),
        "league": league.get("name"),
        "league_id": league.get("id"),
        "home_team": teams.get("home", {}).get("name"),
        "away_team": teams.get("away", {}).get("name"),
        "score": f"{goals.get('home', 0)}-{goals.get('away', 0)}",
        "minutes": _safe_int(stats.get("minutes")),
        "rating": stats.get("rating"),
        "goals": _safe_int(stats.get("goals")),
        "assists": _safe_int(stats.get("assists")),
        "yellow_cards": _safe_int(stats.get("yellow_cards")),
        "red_cards": _safe_int(stats.get("red_cards")),
    }


# ===== SEARCH =====

def search_players(
    query: str,
    season: int,
    league_id: Optional[int] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Search for players by name with alias resolution.

    Supports nicknames like "salah", "mo salah", "kdb", etc.
    Returns top 5 matches for ambiguous queries.

    Returns:
        Dict with scope, season, league_id, query, players list, and alias info
    """
    # Check for player alias first
    alias_db = _get_alias_db()
    alias_matches = alias_db.match_player(query)
    canonical_name = alias_matches[0].name if alias_matches else None
    player_id = int(alias_matches[0].entity_id) if alias_matches else None

    alias_used = None
    if canonical_name:
        alias_used = {"original": query, "resolved_to": canonical_name, "player_id": player_id}
        # If we have an exact ID, fetch that player directly
        if player_id:
            player_data = get_player_by_id(player_id, season, scope="all_competitions")
            if player_data:
                competitions = player_data.get("competitions", [])
                primary_stats = player_data.get("premier_league") or (competitions[0] if competitions else {})
                players = [{
                    "id": player_data.get("id"),
                    "name": player_data.get("name"),
                    "photo": player_data.get("photo"),
                    "nationality": player_data.get("nationality"),
                    "team": {
                        "id": primary_stats.get("team_id"),
                        "name": primary_stats.get("team"),
                    },
                    "position": primary_stats.get("position"),
                    "goals": primary_stats.get("goals", 0),
                    "assists": primary_stats.get("assists", 0),
                    "appearances": primary_stats.get("appearances", 0),
                }]
                return {
                    "scope": "all_competitions",
                    "season": season,
                    "league_id": league_id,
                    "query": query,
                    "alias_used": alias_used,
                    "players": players,
                }
            alias_used["note"] = "Player not found in season, using text search"

    # Get search queries (may include canonical name)
    search_queries = [canonical_name, query] if canonical_name else [query]

    all_players = []
    seen_ids = set()

    for search_query in search_queries:
        params = {
            "search": search_query,
            "season": season,
        }
        if league_id is not None:
            params["league"] = league_id
        data = _make_request("players", params)

        for item in data.get("response", []):
            player = item.get("player", {})
            player_id = player.get("id")

            # Skip duplicates
            if player_id in seen_ids:
                continue
            seen_ids.add(player_id)

            stats = item.get("statistics", [{}])[0]
            games = stats.get("games", {})
            goals_data = stats.get("goals", {})

            all_players.append({
                "id": player_id,
                "name": player.get("name"),
                "photo": player.get("photo"),
                "nationality": player.get("nationality"),
                "team": {
                    "id": stats.get("team", {}).get("id"),
                    "name": stats.get("team", {}).get("name"),
                },
                "position": games.get("position"),
                "goals": _safe_int(goals_data.get("total")),
                "assists": _safe_int(goals_data.get("assists")),
                "appearances": _safe_int(games.get("appearences")),
            })

    # Rank players by relevance
    ranked_players = _rank_players(all_players, query)

    # For ambiguous queries, always return top 5
    if _is_ambiguous_query(query) and len(ranked_players) > 1:
        result_limit = min(5, len(ranked_players))
        ambiguous = True
    else:
        result_limit = limit
        ambiguous = False

    return {
        "scope": "league_only" if league_id is not None else "all_competitions",
        "season": season,
        "league_id": league_id,
        "query": query,
        "alias_used": alias_used,
        "ambiguous": ambiguous,
        "players": ranked_players[:result_limit],
    }


def search_teams(
    query: str,
    season: int,
    league_id: Optional[int] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Search for teams by name with alias resolution.

    Supports nicknames like "man utd", "spurs", "gunners", etc.

    Returns:
        Dict with scope, season, league_id, query, teams list, and alias info
    """
    # Check for team alias first
    alias_db = _get_alias_db()
    alias_matches = alias_db.match_team(query)
    canonical_name = alias_matches[0].name if alias_matches else None
    team_id = int(alias_matches[0].entity_id) if alias_matches else None

    alias_used = None
    if canonical_name:
        alias_used = {"original": query, "resolved_to": canonical_name, "team_id": team_id}
        # Use canonical name for search
        search_query = canonical_name
    else:
        search_query = query

    all_teams = []
    if league_id is not None:
        all_teams_data = get_teams(season, league_id)
        all_teams = all_teams_data.get("teams", [])
    else:
        for lid in SUPPORTED_LEAGUES.keys():
            league_teams_data = get_teams(season, lid)
            all_teams.extend(league_teams_data.get("teams", []))

    # Normalize search query
    normalized_query = _normalize_text(search_query)

    # Find matching teams
    matching = []
    for team in all_teams:
        team_name_normalized = _normalize_text(team.get("name", ""))

        # Exact match gets priority
        if team_name_normalized == normalized_query:
            matching.insert(0, team)
        # Partial match
        elif normalized_query in team_name_normalized:
            matching.append(team)

    # If we have a team_id from alias, prioritize that team
    if team_id:
        for i, team in enumerate(matching):
            if team.get("id") == team_id:
                # Move to front
                matching.insert(0, matching.pop(i))
                break
        else:
            # Team not in current results, try to find by ID
            for team in all_teams:
                if team.get("id") == team_id:
                    matching.insert(0, team)
                    break

    return {
        "scope": "league_only" if league_id is not None else "all_competitions",
        "season": season,
        "league_id": league_id,
        "query": query,
        "alias_used": alias_used,
        "teams": matching[:limit],
    }


# ===== CACHE MANAGEMENT =====

def clear_cache() -> int:
    """Clear all cached data. Returns number of entries cleared."""
    global _cache
    count = len(_cache)
    _cache = {}
    return count


def get_cache_stats() -> Dict[str, Any]:
    """Get comprehensive cache statistics."""
    cache_manager = get_cache_manager()
    return cache_manager.get_stats()

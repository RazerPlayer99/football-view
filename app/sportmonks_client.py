"""
Sportmonks API Client for Football View
Handles all Sportmonks v3 API interactions
"""
import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
import requests
from functools import lru_cache

from config.settings import settings

logger = logging.getLogger("sportmonks_client")

# API Configuration
SPORTMONKS_API_KEY = settings.sportmonks_api_key or os.getenv("SPORTMONKS_API_KEY", "")
SPORTMONKS_BASE_URL = "https://api.sportmonks.com/v3/football"

# Stat type IDs for quick reference
STAT_TYPES = {
    "POSSESSION": 45,
    "SHOTS_TOTAL": 42,
    "SHOTS_ON_TARGET": 86,
    "SHOTS_OFF_TARGET": 41,
    "CORNERS": 34,
    "FOULS": 56,
    "YELLOW_CARDS": 84,
    "RED_CARDS": 83,
    "ATTACKS": 43,
    "DANGEROUS_ATTACKS": 44,
    "OFFSIDES": 51,
    "SAVES": 57,
    "PASSES": 80,
    "PASSES_ACCURATE": 81,
    "PASSES_PERCENT": 82,
    "CROSSES": 98,
    "INTERCEPTIONS": 100,
    "CLEARANCES": 101,
    "FREE_KICKS": 55,
    "GOAL_KICKS": 53,
    "THROW_INS": 60,
    "RATING": 118,
}

# Event type IDs
EVENT_TYPES = {
    14: "goal",
    15: "own_goal",
    16: "penalty",
    17: "missed_penalty",
    18: "substitution",
    19: "yellowcard",
    20: "redcard",
    21: "yellowred",
    # VAR events
    22: "var_goal",
    23: "var_card",
    24: "penalty_confirmed",
    25: "penalty_cancelled",
}

# Match states
MATCH_STATES = {
    1: {"short": "NS", "long": "Not Started", "is_live": False, "is_finished": False},
    2: {"short": "1H", "long": "First Half", "is_live": True, "is_finished": False},
    3: {"short": "HT", "long": "Half Time", "is_live": True, "is_finished": False},
    4: {"short": "2H", "long": "Second Half", "is_live": True, "is_finished": False},
    5: {"short": "FT", "long": "Full Time", "is_live": False, "is_finished": True},
    6: {"short": "ET", "long": "Extra Time", "is_live": True, "is_finished": False},
    7: {"short": "PEN", "long": "Penalties", "is_live": True, "is_finished": False},
    8: {"short": "AET", "long": "After Extra Time", "is_live": False, "is_finished": True},
    9: {"short": "FT-PEN", "long": "Full Time - Penalties", "is_live": False, "is_finished": True},
    10: {"short": "SUSP", "long": "Suspended", "is_live": False, "is_finished": False},
    11: {"short": "INT", "long": "Interrupted", "is_live": False, "is_finished": False},
    12: {"short": "PST", "long": "Postponed", "is_live": False, "is_finished": False},
    13: {"short": "CANC", "long": "Cancelled", "is_live": False, "is_finished": False},
    14: {"short": "ABD", "long": "Abandoned", "is_live": False, "is_finished": False},
    15: {"short": "DELAY", "long": "Delayed", "is_live": False, "is_finished": False},
    17: {"short": "TBA", "long": "To Be Announced", "is_live": False, "is_finished": False},
    21: {"short": "LIVE", "long": "Live", "is_live": True, "is_finished": False},
    22: {"short": "BT", "long": "Break Time", "is_live": True, "is_finished": False},
}

# Sportmonks League IDs - All 25 Leagues in Plan
SUPPORTED_LEAGUES = {
    # European Competitions
    2: "Champions League",          # UEFA
    5: "Europa League",             # UEFA

    # Top 5 European Leagues
    8: "Premier League",            # England
    564: "La Liga",                 # Spain
    82: "Bundesliga",               # Germany
    384: "Serie A",                 # Italy
    301: "Ligue 1",                 # France

    # England
    9: "Championship",              # England 2nd tier
    24: "FA Cup",                   # England
    27: "Carabao Cup",              # England

    # Spain
    567: "La Liga 2",               # Spain 2nd tier
    570: "Copa Del Rey",            # Spain

    # Italy
    387: "Serie B",                 # Italy 2nd tier
    390: "Coppa Italia",            # Italy

    # Other Top European Leagues
    72: "Eredivisie",               # Netherlands
    462: "Liga Portugal",           # Portugal
    208: "Pro League",              # Belgium
    181: "Admiral Bundesliga",      # Austria
    591: "Super League",            # Switzerland
    600: "Super Lig",               # Turkey

    # Scandinavia
    271: "Superliga",               # Denmark
    444: "Eliteserien",             # Norway
    573: "Allsvenskan",             # Sweden

    # Eastern Europe
    453: "Ekstraklasa",             # Poland
    244: "1. HNL",                  # Croatia
    486: "Russian Premier League",  # Russia

    # UK
    501: "Premiership",             # Scotland
}


def _make_request(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    include: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Make a request to the Sportmonks API."""
    url = f"{SPORTMONKS_BASE_URL}/{endpoint}"

    request_params = {"api_token": SPORTMONKS_API_KEY}
    if params:
        request_params.update(params)
    if include:
        request_params["include"] = ";".join(include)

    try:
        response = requests.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Sportmonks API error: {e}")
        return {"data": None, "error": str(e)}


# =============================================================================
# FIXTURE / MATCH ENDPOINTS
# =============================================================================

def get_fixture_by_id(
    fixture_id: int,
    include_events: bool = True,
    include_statistics: bool = True,
    include_lineups: bool = True,
    include_scores: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Get detailed fixture data by ID.

    Returns processed match data ready for the UI.
    """
    includes = ["participants", "league", "venue", "state"]
    if include_events:
        includes.append("events")
    if include_statistics:
        includes.append("statistics")
    if include_lineups:
        includes.extend(["lineups.details", "formations"])
    if include_scores:
        includes.append("scores")

    data = _make_request(f"fixtures/{fixture_id}", include=includes)

    if not data.get("data"):
        return None

    return _process_fixture(data["data"])


def get_livescores(include_events: bool = True, include_statistics: bool = True) -> List[Dict[str, Any]]:
    """Get all current live matches."""
    includes = ["participants", "league", "state", "scores"]
    if include_events:
        includes.append("events")
    if include_statistics:
        includes.append("statistics")

    data = _make_request("livescores", include=includes)

    if not data.get("data"):
        return []

    return [_process_fixture(f) for f in data["data"]]


def get_fixtures_by_date(
    date: str,
    league_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Get fixtures for a specific date.

    Args:
        date: Date in YYYY-MM-DD format
        league_ids: Optional list of league IDs to filter
    """
    includes = ["participants", "league", "state", "scores", "venue"]

    params = {"per_page": 100}  # Request more items per page
    if league_ids:
        params["filters"] = f"fixtureLeagues:{','.join(map(str, league_ids))}"

    all_fixtures = []
    page = 1
    max_pages = 10  # Safety limit

    while page <= max_pages:
        params["page"] = page
        data = _make_request(f"fixtures/date/{date}", params=params, include=includes)

        if not data.get("data"):
            break

        all_fixtures.extend(data["data"])

        # Check pagination for more pages
        pagination = data.get("pagination", {})
        if not pagination.get("has_more", False):
            break

        page += 1

    logger.info(f"Fetched {len(all_fixtures)} fixtures for {date} across {page} page(s)")

    return [_process_fixture(f) for f in all_fixtures]


def get_head_to_head(team1_id: int, team2_id: int, limit: int = 5) -> Dict[str, Any]:
    """Get head-to-head record between two teams."""
    data = _make_request(
        f"fixtures/head-to-head/{team1_id}/{team2_id}",
        params={"per_page": limit},
        include=["participants", "scores"]
    )

    if not data.get("data"):
        return {"matches": [], "team1_wins": 0, "team2_wins": 0, "draws": 0}

    matches = []
    team1_wins = 0
    team2_wins = 0
    draws = 0

    for fixture in data["data"]:
        processed = _process_fixture(fixture)
        matches.append(processed)

        # Calculate winner
        home_goals = processed.get("home_score", 0) or 0
        away_goals = processed.get("away_score", 0) or 0
        home_id = processed.get("home_team", {}).get("id")
        away_id = processed.get("away_team", {}).get("id")

        if home_goals > away_goals:
            if home_id == team1_id:
                team1_wins += 1
            else:
                team2_wins += 1
        elif away_goals > home_goals:
            if away_id == team1_id:
                team1_wins += 1
            else:
                team2_wins += 1
        else:
            draws += 1

    return {
        "matches": matches,
        "team1_wins": team1_wins,
        "team2_wins": team2_wins,
        "draws": draws,
    }


# =============================================================================
# TEAM ENDPOINTS
# =============================================================================

def get_team_by_id(team_id: int, include_statistics: bool = False) -> Optional[Dict[str, Any]]:
    """Get team details by ID."""
    includes = ["venue", "country"]
    if include_statistics:
        includes.append("statistics.details")

    data = _make_request(f"teams/{team_id}", include=includes)

    if not data.get("data"):
        return None

    team = data["data"]
    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "short_code": team.get("short_code"),
        "logo": team.get("image_path"),
        "founded": team.get("founded"),
        "venue": team.get("venue", {}).get("name") if team.get("venue") else None,
        "country": team.get("country", {}).get("name") if team.get("country") else None,
    }


def get_team_form(team_id: int, limit: int = 5) -> List[str]:
    """
    Get team's recent form (W/D/L).

    Returns list like ["W", "W", "D", "L", "W"]
    """
    from datetime import datetime, timedelta

    # Use fixtures/between endpoint with date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)  # Look back 90 days

    data = _make_request(
        f"fixtures/between/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}/{team_id}",
        include=["participants", "scores", "state"]
    )

    if not data.get("data"):
        return []

    # Sort by date descending to get most recent first
    fixtures = sorted(
        data["data"],
        key=lambda x: x.get("starting_at", ""),
        reverse=True
    )

    form = []
    for fixture in fixtures:
        state_id = fixture.get("state_id", 0)
        state = MATCH_STATES.get(state_id, {})

        # Only count finished matches
        if not state.get("is_finished"):
            continue

        # Find team's score from participants
        participants = fixture.get("participants", [])
        scores = fixture.get("scores", [])

        team_goals = 0
        opponent_goals = 0

        for participant in participants:
            p_id = participant.get("id")
            # Find score for this participant
            for score in scores:
                if score.get("participant_id") == p_id and score.get("description") == "CURRENT":
                    goals = score.get("score", {}).get("goals", 0) or 0
                    if p_id == team_id:
                        team_goals = goals
                    else:
                        opponent_goals = goals

        if team_goals > opponent_goals:
            form.append("W")
        elif team_goals < opponent_goals:
            form.append("L")
        else:
            form.append("D")

        if len(form) >= limit:
            break

    return form[:limit]


# =============================================================================
# DATA PROCESSING HELPERS
# =============================================================================

def _process_fixture(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Process raw Sportmonks fixture into UI-friendly format."""
    # Basic info
    fixture_id = fixture.get("id")
    name = fixture.get("name", "")
    starting_at = fixture.get("starting_at")

    # State
    state_id = fixture.get("state_id", 1)
    state_info = MATCH_STATES.get(state_id, MATCH_STATES[1])

    # Participants (teams)
    participants = fixture.get("participants", [])
    home_team = None
    away_team = None

    for p in participants:
        team_data = {
            "id": p.get("id"),
            "name": p.get("name"),
            "short_code": p.get("short_code") or _get_short_code(p.get("name", "")),
            "logo": p.get("image_path"),
        }
        if p.get("meta", {}).get("location") == "home":
            home_team = team_data
        else:
            away_team = team_data

    # Scores - None for upcoming matches, actual values for live/finished
    scores = fixture.get("scores", [])
    home_score = None
    away_score = None
    halftime_home = None
    halftime_away = None

    for score in scores:
        participant_id = score.get("participant_id")
        score_data = score.get("score", {})
        goals = score_data.get("goals", 0) or 0
        description = score.get("description", "")

        if description == "CURRENT":
            if home_team and participant_id == home_team["id"]:
                home_score = goals
            elif away_team and participant_id == away_team["id"]:
                away_score = goals
        elif description == "1ST_HALF":
            if home_team and participant_id == home_team["id"]:
                halftime_home = goals
            elif away_team and participant_id == away_team["id"]:
                halftime_away = goals

    # For finished/live matches, ensure scores are set (default to 0 if no CURRENT score found)
    if state_info.get("is_finished") or state_info.get("is_live"):
        if home_score is None:
            home_score = 0
        if away_score is None:
            away_score = 0

    # Events
    events = []
    for event in fixture.get("events", []):
        events.append(_process_event(event, home_team, away_team))

    # Sort events by minute (most recent first)
    events.sort(key=lambda e: (e.get("minute", 0), e.get("sort_order", 0)), reverse=True)

    # Statistics
    statistics = _process_statistics(fixture.get("statistics", []), home_team, away_team)

    # Lineups
    lineups = _process_lineups(fixture.get("lineups", []), home_team, away_team)

    # Formations
    formations = {}
    for formation in fixture.get("formations", []):
        participant_id = formation.get("participant_id")
        formation_str = formation.get("formation")
        if home_team and participant_id == home_team["id"]:
            formations["home"] = formation_str
        elif away_team and participant_id == away_team["id"]:
            formations["away"] = formation_str

    # League info
    league = fixture.get("league", {})
    league_info = {
        "id": league.get("id"),
        "name": league.get("name"),
        "logo": league.get("image_path"),
    }

    # Venue info
    venue = fixture.get("venue", {})
    venue_info = {
        "id": venue.get("id"),
        "name": venue.get("name"),
        "city": venue.get("city_name"),
        "capacity": venue.get("capacity"),
        "surface": venue.get("surface"),
    } if venue else None

    # Calculate elapsed time from events if live
    elapsed = None
    if state_info["is_live"] and events:
        elapsed = max(e.get("minute", 0) for e in events)

    return {
        "id": fixture_id,
        "name": name,
        "starting_at": starting_at,
        "state": state_info,
        "state_id": state_id,
        "elapsed": elapsed,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "halftime": {"home": halftime_home, "away": halftime_away},
        "events": events,
        "statistics": statistics,
        "lineups": lineups,
        "formations": formations,
        "league": league_info,
        "venue": venue_info,
    }


def _process_event(event: Dict[str, Any], home_team: Optional[Dict], away_team: Optional[Dict]) -> Dict[str, Any]:
    """Process a single event."""
    type_id = event.get("type_id", 0)
    event_type = EVENT_TYPES.get(type_id, "unknown")

    # Determine which team
    participant_id = event.get("participant_id")
    is_home = home_team and participant_id == home_team["id"]
    team = home_team if is_home else away_team

    return {
        "id": event.get("id"),
        "minute": event.get("minute", 0),
        "extra_minute": event.get("extra_minute"),
        "type": event_type,
        "type_id": type_id,
        "player_name": event.get("player_name"),
        "player_id": event.get("player_id"),
        "related_player_name": event.get("related_player_name"),  # Assist or sub out
        "related_player_id": event.get("related_player_id"),
        "info": event.get("info"),  # "Header", "Right foot", "Foul", etc.
        "result": event.get("result"),  # Score after event like "1-0"
        "team": team,
        "is_home": is_home,
        "sort_order": event.get("sort_order", 0),
    }


def _process_statistics(
    statistics: List[Dict[str, Any]],
    home_team: Optional[Dict],
    away_team: Optional[Dict]
) -> Dict[str, Dict[str, Any]]:
    """Process statistics into home/away comparison format."""
    result = {}

    # Initialize all stat types
    for stat_name, type_id in STAT_TYPES.items():
        result[stat_name.lower()] = {"home": 0, "away": 0, "type_id": type_id}

    for stat in statistics:
        type_id = stat.get("type_id")
        participant_id = stat.get("participant_id")
        value = stat.get("data", {}).get("value", 0)

        # Find stat name
        stat_name = None
        for name, tid in STAT_TYPES.items():
            if tid == type_id:
                stat_name = name.lower()
                break

        if not stat_name:
            continue

        # Assign to home or away
        is_home = home_team and participant_id == home_team["id"]
        if is_home:
            result[stat_name]["home"] = value
        else:
            result[stat_name]["away"] = value

    return result


def _process_lineups(
    lineups: List[Dict[str, Any]],
    home_team: Optional[Dict],
    away_team: Optional[Dict]
) -> Dict[str, List[Dict[str, Any]]]:
    """Process lineups into home/away format."""
    result = {"home": [], "away": []}

    # Rating type ID in Sportmonks
    RATING_TYPE_ID = 118

    for player in lineups:
        participant_id = player.get("team_id") or player.get("participant_id")
        is_home = home_team and participant_id == home_team["id"]

        # Extract rating from details if available
        rating = None
        details = player.get("details", [])
        for detail in details:
            if detail.get("type_id") == RATING_TYPE_ID:
                rating = detail.get("data", {}).get("value")
                break

        player_data = {
            "id": player.get("player_id"),
            "name": player.get("player_name"),
            "number": player.get("jersey_number"),
            "position": player.get("position", {}).get("name") if isinstance(player.get("position"), dict) else player.get("position_id"),
            "position_id": player.get("position_id"),
            "formation_position": player.get("formation_position"),
            "type": player.get("type_id"),  # 11 = starting, 12 = sub
            "is_starter": player.get("type_id") == 11,
            "rating": rating,
        }

        if is_home:
            result["home"].append(player_data)
        else:
            result["away"].append(player_data)

    return result


def _get_short_code(team_name: str) -> str:
    """Generate a short code from team name."""
    if not team_name:
        return "???"

    # Common patterns
    words = team_name.split()
    if len(words) >= 2:
        # Take first letter of each word (up to 3)
        return "".join(w[0].upper() for w in words[:3])
    else:
        # Take first 3 letters
        return team_name[:3].upper()


# =============================================================================
# MOMENTUM / XG HELPERS (Placeholder for premium features)
# =============================================================================

def get_momentum_data(fixture_id: int) -> Optional[Dict[str, Any]]:
    """
    Get momentum data for a fixture.

    NOTE: Requires Momentum add-on ($20/mo).
    Returns None if not available, UI should fall back to attacks comparison.
    """
    # TODO: Implement when Momentum add-on is purchased
    # For now, return None to trigger fallback
    return None


def get_trends_data(fixture_id: int) -> Optional[Dict[str, Any]]:
    """
    Get minute-by-minute trends data for momentum chart visualization.

    Returns possession, attacks, dangerous attacks, and shots per minute
    for building a momentum wave chart.
    """
    data = _make_request(f"fixtures/{fixture_id}", include=["trends", "participants"])

    if not data.get("data"):
        return None

    fixture = data["data"]
    trends = fixture.get("trends", []) or []

    if not trends:
        return None

    # Get home and away team IDs
    participants = fixture.get("participants", [])
    home_team_id = None
    away_team_id = None
    for p in participants:
        meta = p.get("meta", {})
        if meta.get("location") == "home":
            home_team_id = p.get("id")
        elif meta.get("location") == "away":
            away_team_id = p.get("id")

    # Group trends by minute
    # Trends include possession, attacks, dangerous_attacks per minute
    minutes_data = {}

    for trend in trends:
        minute = trend.get("minute")
        participant_id = trend.get("participant_id")
        type_id = trend.get("type_id")
        value = trend.get("value", 0)

        if minute is None:
            continue

        if minute not in minutes_data:
            minutes_data[minute] = {
                "minute": minute,
                "home_possession": 50,
                "away_possession": 50,
                "home_attacks": 0,
                "away_attacks": 0,
                "home_dangerous": 0,
                "away_dangerous": 0,
            }

        # Type IDs: 45=possession, 43=attacks, 44=dangerous_attacks
        location = "home" if participant_id == home_team_id else "away"

        if type_id == 45:  # Possession
            minutes_data[minute][f"{location}_possession"] = value
        elif type_id == 43:  # Attacks
            minutes_data[minute][f"{location}_attacks"] = value
        elif type_id == 44:  # Dangerous attacks
            minutes_data[minute][f"{location}_dangerous"] = value

    # Sort by minute and return as list
    sorted_minutes = sorted(minutes_data.values(), key=lambda x: x["minute"])

    # Calculate momentum score per minute (weighted: possession + attacks*2 + dangerous*3)
    for m in sorted_minutes:
        home_score = m["home_possession"] + (m["home_attacks"] * 2) + (m["home_dangerous"] * 3)
        away_score = m["away_possession"] + (m["away_attacks"] * 2) + (m["away_dangerous"] * 3)
        total = home_score + away_score
        if total > 0:
            m["home_momentum"] = round((home_score / total) * 100)
            m["away_momentum"] = 100 - m["home_momentum"]
        else:
            m["home_momentum"] = 50
            m["away_momentum"] = 50

    return {
        "minutes": sorted_minutes,
        "total_minutes": len(sorted_minutes),
    }


def get_xg_data(fixture_id: int) -> Optional[Dict[str, Any]]:
    """
    Get expected goals data for a fixture.

    Fetches xG metrics using the xGFixture include.
    Type IDs:
        5304: xG (expected goals)
        5305: xGoT (expected goals on target)
        7943: npxG (non-penalty xG)
        9686: xGP (xG for)
        9687: xGA (xG against)
        7942: xGC (xG conceded)
        7944: xGSP (xG set piece)
        7945: xGOP (xG open play)
    """
    # xG Type ID mapping
    XG_TYPES = {
        5304: "xg",
        5305: "xgot",
        7943: "npxg",
        9686: "xgp",
        9687: "xga",
        7942: "xgc",
        7944: "xgsp",
        7945: "xgop",
    }

    data = _make_request(f"fixtures/{fixture_id}", include=["xGFixture", "participants"])

    if not data.get("data"):
        return None

    fixture = data["data"]
    # API returns lowercase 'xgfixture' not 'xGFixture'
    xg_fixture = fixture.get("xgfixture", []) or fixture.get("xGFixture", []) or []

    if not xg_fixture:
        return None

    # Initialize result
    result = {
        "home_xg": 0.0, "away_xg": 0.0,
        "home_xgot": 0.0, "away_xgot": 0.0,
        "home_npxg": 0.0, "away_npxg": 0.0,
        "home_xgp": 0.0, "away_xgp": 0.0,
        "home_xga": 0.0, "away_xga": 0.0,
        "home_xgc": 0.0, "away_xgc": 0.0,
        "home_xgsp": 0.0, "away_xgsp": 0.0,
        "home_xgop": 0.0, "away_xgop": 0.0,
    }

    # Parse xG data - API uses 'location' field (home/away) and 'data.value'
    for xg_item in xg_fixture:
        type_id = xg_item.get("type_id")
        location = xg_item.get("location")  # 'home' or 'away'

        # Get the actual xG value from data.value
        data_obj = xg_item.get("data", {})
        if isinstance(data_obj, dict):
            xg_val = data_obj.get("value", 0.0)
        else:
            xg_val = float(data_obj) if data_obj else 0.0

        # Map type ID to key name
        key_name = XG_TYPES.get(type_id)
        if not key_name or not location:
            continue

        # Use location directly (home/away)
        # Only use positive values (some metrics like xGP can be negative)
        if xg_val >= 0:
            result[f"{location}_{key_name}"] = round(xg_val, 2)

    return result


def calculate_attacks_momentum(statistics: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate momentum from attacks data as fallback for premium momentum.

    Uses dangerous attacks weighted more heavily than regular attacks.
    """
    attacks = statistics.get("attacks", {"home": 0, "away": 0})
    dangerous = statistics.get("dangerous_attacks", {"home": 0, "away": 0})

    # Weight: dangerous attacks count 2x
    home_weighted = attacks["home"] + (dangerous["home"] * 2)
    away_weighted = attacks["away"] + (dangerous["away"] * 2)

    total = home_weighted + away_weighted
    if total == 0:
        return {"home_percent": 50, "away_percent": 50, "dominant": None}

    home_percent = round((home_weighted / total) * 100)
    away_percent = 100 - home_percent

    dominant = None
    if home_percent > 55:
        dominant = "home"
    elif away_percent > 55:
        dominant = "away"

    return {
        "home_percent": home_percent,
        "away_percent": away_percent,
        "dominant": dominant,
        "home_attacks": attacks["home"],
        "away_attacks": attacks["away"],
        "home_dangerous": dangerous["home"],
        "away_dangerous": dangerous["away"],
    }


# =============================================================================
# TEAM HUB ENDPOINTS
# =============================================================================

def get_team_details(team_id: int) -> Optional[Dict[str, Any]]:
    """
    Get comprehensive team details for Team Hub.
    Includes venue, country, coach, and statistics.
    """
    includes = ["venue", "country", "coaches", "statistics.details"]
    data = _make_request(f"teams/{team_id}", include=includes)

    if not data.get("data"):
        return None

    team = data["data"]
    venue = team.get("venue", {}) or {}
    country = team.get("country", {}) or {}

    # Get current coach
    coaches = team.get("coaches", [])
    current_coach = None
    for coach in coaches:
        if coach.get("active"):
            current_coach = {
                "id": coach.get("coach_id"),
                "name": coach.get("common_name") or coach.get("fullname"),
                "image": coach.get("image_path"),
            }
            break

    # Process statistics
    statistics = _process_team_statistics(team.get("statistics", []))

    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "short_code": team.get("short_code") or _get_short_code(team.get("name", "")),
        "logo": team.get("image_path"),
        "founded": team.get("founded"),
        "country": country.get("name"),
        "country_flag": country.get("image_path"),
        "venue": {
            "id": venue.get("id"),
            "name": venue.get("name"),
            "city": venue.get("city_name"),
            "capacity": venue.get("capacity"),
            "surface": venue.get("surface"),
            "image": venue.get("image_path"),
        } if venue else None,
        "coach": current_coach,
        "statistics": statistics,
    }


def _process_team_statistics(statistics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Process team seasonal statistics from Sportmonks."""
    result = {
        "goals_scored": {"total": 0, "home": 0, "away": 0},
        "goals_conceded": {"total": 0, "home": 0, "away": 0},
        "clean_sheets": {"total": 0, "home": 0, "away": 0},
        "wins": {"total": 0, "home": 0, "away": 0},
        "draws": {"total": 0, "home": 0, "away": 0},
        "losses": {"total": 0, "home": 0, "away": 0},
        "scoring_minutes": {},
        "conceding_minutes": {},
    }

    for stat_season in statistics:
        details = stat_season.get("details", [])
        for detail in details:
            type_id = detail.get("type_id")
            value = detail.get("value", {})

            # Goals (type_id: 52)
            if type_id == 52:
                result["goals_scored"]["total"] = value.get("all", {}).get("count", 0)
                result["goals_scored"]["home"] = value.get("home", {}).get("count", 0)
                result["goals_scored"]["away"] = value.get("away", {}).get("count", 0)

            # Goals Conceded (type_id: 88)
            elif type_id == 88:
                result["goals_conceded"]["total"] = value.get("all", {}).get("count", 0)
                result["goals_conceded"]["home"] = value.get("home", {}).get("count", 0)
                result["goals_conceded"]["away"] = value.get("away", {}).get("count", 0)

            # Clean Sheets (type_id: 194)
            elif type_id == 194:
                result["clean_sheets"]["total"] = value.get("all", {}).get("count", 0)
                result["clean_sheets"]["home"] = value.get("home", {}).get("count", 0)
                result["clean_sheets"]["away"] = value.get("away", {}).get("count", 0)

            # Wins (type_id: 214)
            elif type_id == 214:
                result["wins"]["total"] = value.get("all", {}).get("count", 0)
                result["wins"]["home"] = value.get("home", {}).get("count", 0)
                result["wins"]["away"] = value.get("away", {}).get("count", 0)

            # Draws (type_id: 215)
            elif type_id == 215:
                result["draws"]["total"] = value.get("all", {}).get("count", 0)
                result["draws"]["home"] = value.get("home", {}).get("count", 0)
                result["draws"]["away"] = value.get("away", {}).get("count", 0)

            # Losses (type_id: 216)
            elif type_id == 216:
                result["losses"]["total"] = value.get("all", {}).get("count", 0)
                result["losses"]["home"] = value.get("home", {}).get("count", 0)
                result["losses"]["away"] = value.get("away", {}).get("count", 0)

            # Scoring Minutes (type_id: 196)
            elif type_id == 196:
                result["scoring_minutes"] = value

            # Conceding Minutes (type_id: 213)
            elif type_id == 213:
                result["conceding_minutes"] = value

    return result


def get_team_fixtures(
    team_id: int,
    limit: int = 10,
    upcoming: bool = False,
    finished: bool = True
) -> List[Dict[str, Any]]:
    """
    Get team's fixtures (past or upcoming).

    Args:
        team_id: Team ID
        limit: Max fixtures to return
        upcoming: If True, get upcoming fixtures
        finished: If True, get finished fixtures
    """
    from datetime import datetime, timedelta

    includes = ["participants", "scores", "league", "venue", "state"]

    # Use fixtures/between endpoint with date range
    now = datetime.now()
    if upcoming:
        start_date = now
        end_date = now + timedelta(days=60)  # Look ahead 60 days
    else:
        start_date = now - timedelta(days=90)  # Look back 90 days
        end_date = now

    data = _make_request(
        f"fixtures/between/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}/{team_id}",
        include=includes
    )

    if not data.get("data"):
        return []

    # Sort fixtures
    fixtures_data = sorted(
        data["data"],
        key=lambda x: x.get("starting_at", ""),
        reverse=not upcoming  # Descending for past, ascending for upcoming
    )

    fixtures = []
    for fixture in fixtures_data:
        processed = _process_fixture(fixture)

        # Filter by status
        state = processed.get("state", {})
        if upcoming and state.get("is_finished"):
            continue
        if finished and not upcoming and not state.get("is_finished"):
            continue

        fixtures.append(processed)

        if len(fixtures) >= limit:
            break

    return fixtures


def get_team_recent_matches(team_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get team's recent completed matches with full details.
    Returns matches formatted for the form section.
    """
    from datetime import datetime, timedelta

    # Use fixtures/between endpoint for team matches
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)  # Look back 90 days

    data = _make_request(
        f"fixtures/between/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}/{team_id}",
        include=["participants", "scores", "league", "venue", "state"]
    )

    if not data.get("data"):
        return []

    # Sort by date descending
    fixtures = sorted(
        data["data"],
        key=lambda x: x.get("starting_at", ""),
        reverse=True
    )

    matches = []
    for fixture in fixtures:
        state_id = fixture.get("state_id", 0)
        state = MATCH_STATES.get(state_id, {})

        if not state.get("is_finished"):
            continue

        processed = _process_fixture(fixture)

        # Determine result from team's perspective
        home_team = processed.get("home_team", {})
        away_team = processed.get("away_team", {})
        home_score = processed.get("home_score", 0) or 0
        away_score = processed.get("away_score", 0) or 0

        is_home = home_team.get("id") == team_id
        opponent = away_team if is_home else home_team
        team_score = home_score if is_home else away_score
        opponent_score = away_score if is_home else home_score

        if team_score > opponent_score:
            result = "W"
        elif team_score < opponent_score:
            result = "L"
        else:
            result = "D"

        matches.append({
            "id": processed.get("id"),
            "date": processed.get("starting_at"),
            "opponent": opponent,
            "is_home": is_home,
            "team_score": team_score,
            "opponent_score": opponent_score,
            "result": result,
            "league": processed.get("league"),
            "venue": processed.get("venue"),
        })

        if len(matches) >= limit:
            break

    return matches


def get_team_next_match(team_id: int) -> Optional[Dict[str, Any]]:
    """Get team's next upcoming match."""
    from datetime import datetime, timedelta

    # Use fixtures/between for upcoming matches
    start_date = datetime.now()
    end_date = start_date + timedelta(days=30)  # Look ahead 30 days

    data = _make_request(
        f"fixtures/between/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}/{team_id}",
        include=["participants", "league", "venue", "state"]
    )

    if not data.get("data"):
        return None

    for fixture in data["data"]:
        state_id = fixture.get("state_id", 0)
        state = MATCH_STATES.get(state_id, {})

        if not state.get("is_finished") and not state.get("is_live"):
            return _process_fixture(fixture)

    return None


def get_standings(
    season_id: int = None,
    league_id: int = None
) -> List[Dict[str, Any]]:
    """
    Get league standings.

    Args:
        season_id: Season ID (optional)
        league_id: League ID (optional, used if no season_id)
    """
    if season_id:
        endpoint = f"standings/seasons/{season_id}"
    elif league_id:
        endpoint = f"standings/live/leagues/{league_id}"
    else:
        return []

    data = _make_request(endpoint, include=["participant", "details"])

    if not data.get("data"):
        return []

    standings = []
    for row in data["data"]:
        participant = row.get("participant", {})

        # Extract stats from details array (Sportmonks stores stats in details)
        details = row.get("details", [])
        stats = {}
        for detail in details:
            type_id = detail.get("type_id")
            value = detail.get("value")
            # Sportmonks standing type IDs (from live standings):
            # 129=games_played, 130=won, 131=draw, 132=lost, 133=goals_for, 134=goals_against
            # 138=position, 139=wins_home, 140=wins_away, 141=draws_home, 142=draws_away
            # 143=lost_home, 144=lost_away, 145=goals_scored_home, 146=goals_scored_away
            # 147=goals_conceded_home, 148=goals_conceded_away, 179=goal_diff
            if type_id == 129:
                stats["played"] = value
            elif type_id == 130:
                stats["won"] = value
            elif type_id == 131:
                stats["drawn"] = value
            elif type_id == 132:
                stats["lost"] = value
            elif type_id == 133:
                stats["goals_for"] = value
            elif type_id == 134:
                stats["goals_against"] = value
            elif type_id == 179:
                stats["goal_diff"] = value
            # Also capture home/away breakdowns for totals if main fields missing
            elif type_id == 139:  # wins_home
                stats.setdefault("won_home", value)
            elif type_id == 140:  # wins_away
                stats.setdefault("won_away", value)
            elif type_id == 145:  # goals_scored_home
                stats.setdefault("goals_for_home", value)
            elif type_id == 146:  # goals_scored_away
                stats.setdefault("goals_for_away", value)
            elif type_id == 147:  # goals_conceded_home
                stats.setdefault("goals_against_home", value)
            elif type_id == 148:  # goals_conceded_away
                stats.setdefault("goals_against_away", value)

        # Fall back to direct fields if details are empty, or calculate from home/away
        won = stats.get("won") or row.get("won") or row.get("wins")
        if won is None and "won_home" in stats and "won_away" in stats:
            won = (stats.get("won_home") or 0) + (stats.get("won_away") or 0)

        drawn = stats.get("drawn") or row.get("draw") or row.get("draws")
        lost = stats.get("lost") or row.get("lost") or row.get("losses")

        goals_for = stats.get("goals_for") or row.get("goals_scored") or row.get("goals_for")
        if goals_for is None and "goals_for_home" in stats and "goals_for_away" in stats:
            goals_for = (stats.get("goals_for_home") or 0) + (stats.get("goals_for_away") or 0)

        goals_against = stats.get("goals_against") or row.get("goals_conceded") or row.get("goals_against")
        if goals_against is None and "goals_against_home" in stats and "goals_against_away" in stats:
            goals_against = (stats.get("goals_against_home") or 0) + (stats.get("goals_against_away") or 0)

        played = stats.get("played") or row.get("played") or row.get("games_played")
        # Calculate played from W+D+L if not directly available
        if played is None and won is not None and drawn is not None and lost is not None:
            played = (won or 0) + (drawn or 0) + (lost or 0)

        goal_diff = stats.get("goal_diff") or row.get("goal_difference")

        # Calculate goal diff if not provided
        if goal_diff is None and goals_for is not None and goals_against is not None:
            goal_diff = (goals_for or 0) - (goals_against or 0)

        standings.append({
            "position": row.get("position"),
            "team_id": participant.get("id"),
            "team_name": participant.get("name"),
            "team_short": participant.get("short_code") or _get_short_code(participant.get("name", "")),
            "team_logo": participant.get("image_path"),
            "played": played,
            "won": won,
            "drawn": drawn,
            "lost": lost,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "goal_diff": goal_diff,
            "points": row.get("points"),
            "form": row.get("recent_form"),
        })

    # Sort by position
    standings.sort(key=lambda x: x.get("position") or 999)
    return standings


def get_team_squad(team_id: int, season_id: int = None) -> List[Dict[str, Any]]:
    """
    Get team's current squad.

    Args:
        team_id: Team ID
        season_id: Season ID (optional, uses current if not provided)
    """
    if season_id:
        endpoint = f"squads/seasons/{season_id}/teams/{team_id}"
    else:
        endpoint = f"squads/teams/{team_id}"

    data = _make_request(endpoint, include=["player"])

    if not data.get("data"):
        return []

    players = []
    for item in data["data"]:
        player = item.get("player", {})
        details = item.get("details", [])

        # Extract stats from details
        stats = {}
        for detail in details:
            type_info = detail.get("type", {})
            type_name = type_info.get("developer_name", "")
            value = detail.get("value", {})

            if type_name == "GOALS":
                stats["goals"] = value.get("total", 0)
            elif type_name == "ASSISTS":
                stats["assists"] = value.get("total", 0)
            elif type_name == "RATING":
                stats["rating"] = value.get("average", 0)
            elif type_name == "APPEARANCES":
                stats["appearances"] = value.get("total", 0)

        # Map position_id to position name
        position_map = {
            24: "G",  # Goalkeeper
            25: "D",  # Defender
            26: "M",  # Midfielder
            27: "F",  # Forward/Attacker
        }
        position_id = item.get("position_id") or player.get("position_id")
        position = position_map.get(position_id, "M")  # Default to Midfielder

        players.append({
            "id": player.get("id"),
            "name": player.get("common_name") or player.get("display_name") or player.get("name"),
            "image": player.get("image_path"),
            "position": position,
            "position_id": position_id,
            "number": item.get("jersey_number"),
            "nationality": player.get("nationality_id"),
            "is_captain": item.get("is_captain", False),
            "stats": stats,
        })

    return players


def get_team_top_scorers(team_id: int, season_id: int = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Get team's top scorers for the season."""
    squad = get_team_squad(team_id, season_id)

    # Sort by goals
    scorers = sorted(squad, key=lambda p: p.get("stats", {}).get("goals", 0), reverse=True)
    return scorers[:limit]


def get_current_streak(team_id: int) -> Dict[str, Any]:
    """
    Calculate team's current streak (e.g., W4, D2, L1).

    Returns:
        Dict with streak_type ("W", "D", "L") and count
    """
    form = get_team_form(team_id, limit=10)

    if not form:
        return {"type": None, "count": 0, "display": "-"}

    current_result = form[0]
    count = 0

    for result in form:
        if result == current_result:
            count += 1
        else:
            break

    return {
        "type": current_result,
        "count": count,
        "display": f"{current_result}{count}",
    }


def get_team_league_info(team_id: int) -> Optional[Dict[str, Any]]:
    """
    Get the primary league info for a team.
    Returns league details and team's current standing.
    """
    data = _make_request(
        f"teams/{team_id}/current-leagues",
        include=["currentSeason"]
    )

    if not data.get("data"):
        return None

    # Find primary domestic league (not cups)
    for league in data["data"]:
        league_type = league.get("type")
        if league_type == "league":
            season = league.get("currentSeason", {})
            return {
                "id": league.get("id"),
                "name": league.get("name"),
                "logo": league.get("image_path"),
                "country": league.get("country", {}).get("name") if league.get("country") else None,
                "season_id": season.get("id"),
                "season_name": season.get("name"),
            }

    # Fallback to first league
    if data["data"]:
        league = data["data"][0]
        season = league.get("currentSeason", {})
        return {
            "id": league.get("id"),
            "name": league.get("name"),
            "logo": league.get("image_path"),
            "country": league.get("country", {}).get("name") if league.get("country") else None,
            "season_id": season.get("id"),
            "season_name": season.get("name"),
        }

    return None


def get_league_fixtures(
    league_id: int,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Get fixtures for a league (recent and upcoming).
    Uses the fixtures/between endpoint to get fixtures filtered by league.

    Returns:
        Dict with 'fixtures', 'recent_fixtures', and 'current_round'
    """
    from datetime import datetime, timedelta

    # Get fixtures - Sportmonks allows max 35 day range per request
    # We'll make multiple requests to cover sufficient range
    now = datetime.now()

    # Past fixtures - fetch in 35-day chunks going back ~120 days (half a season)
    # This ensures historical rounds (like 20-23) have their actual fixture data
    past_start_4 = (now - timedelta(days=120)).strftime('%Y-%m-%d')
    past_end_4 = (now - timedelta(days=105)).strftime('%Y-%m-%d')

    past_start_3 = (now - timedelta(days=105)).strftime('%Y-%m-%d')
    past_end_3 = (now - timedelta(days=70)).strftime('%Y-%m-%d')

    past_start_2 = (now - timedelta(days=70)).strftime('%Y-%m-%d')
    past_end_2 = (now - timedelta(days=35)).strftime('%Y-%m-%d')

    # Recent fixtures (past 35 days)
    recent_start = (now - timedelta(days=35)).strftime('%Y-%m-%d')
    recent_end = now.strftime('%Y-%m-%d')

    # Upcoming fixtures - two 35-day chunks to get ~60 days ahead (2+ weekends guaranteed)
    upcoming_start = now.strftime('%Y-%m-%d')
    upcoming_mid = (now + timedelta(days=35)).strftime('%Y-%m-%d')
    upcoming_end = (now + timedelta(days=60)).strftime('%Y-%m-%d')

    # Fetch fixtures from both date ranges
    all_raw_fixtures = []
    seen_ids = set()

    # Helper to fetch from a date range
    def fetch_range(start, end):
        page = 1
        max_pages = 5
        while page <= max_pages:
            data = _make_request(
                f"fixtures/between/{start}/{end}",
                params={"per_page": 100, "page": page},
                include=["participants", "scores", "state", "round", "league"]
            )
            if not data.get("data"):
                break

            # Filter for this league
            for fixture in data["data"]:
                fid = fixture.get("id")
                if fid and fid not in seen_ids:
                    if fixture.get("league_id") == league_id or fixture.get("league", {}).get("id") == league_id:
                        all_raw_fixtures.append(fixture)
                        seen_ids.add(fid)

            # Check pagination
            pagination = data.get("pagination", {})
            if page >= pagination.get("last_page", 1):
                break
            page += 1

    # Fetch past fixtures (4 chunks going back 120 days)
    fetch_range(past_start_4, past_end_4)
    fetch_range(past_start_3, past_end_3)
    fetch_range(past_start_2, past_end_2)
    fetch_range(recent_start, recent_end)

    # Fetch upcoming fixtures (2 chunks for 60 days ahead)
    fetch_range(upcoming_start, upcoming_mid)
    fetch_range(upcoming_mid, upcoming_end)

    if not all_raw_fixtures:
        return {"fixtures": [], "recent_fixtures": [], "current_round": None}

    all_fixtures = []
    current_round = None

    for fixture in all_raw_fixtures:
        # Parse the fixture date
        starting_at = fixture.get("starting_at")
        if not starting_at:
            continue

        try:
            fixture_dt = datetime.fromisoformat(starting_at.replace("Z", "+00:00"))
            fixture_date = fixture_dt.date()
        except:
            continue

        # Get participants
        participants = fixture.get("participants", [])
        home_team = None
        away_team = None
        for p in participants:
            meta = p.get("meta", {})
            if meta.get("location") == "home":
                home_team = p
            else:
                away_team = p

        if not home_team or not away_team:
            continue

        # Get scores
        scores = fixture.get("scores", [])
        home_score = None
        away_score = None
        for score in scores:
            desc = score.get("description", "")
            if desc in ["CURRENT", "2ND_HALF", "LIVE"]:
                participant_id = score.get("participant_id")
                if participant_id == home_team.get("id"):
                    home_score = score.get("score", {}).get("goals")
                elif participant_id == away_team.get("id"):
                    away_score = score.get("score", {}).get("goals")

        # Get match state
        state = fixture.get("state", {})
        state_id = state.get("id") if state else fixture.get("state_id")
        match_state = MATCH_STATES.get(state_id, {"short": "NS", "is_live": False, "is_finished": False})

        # Get round info
        round_info = fixture.get("round", {})
        round_number = round_info.get("name") or round_info.get("id")

        # Track current round (latest round with finished/live matches)
        if match_state["is_finished"] or match_state["is_live"]:
            if round_number:
                try:
                    round_num = int(round_number)
                    if current_round is None or round_num > current_round:
                        current_round = round_num
                except:
                    pass

        # Format time
        time_str = fixture_dt.strftime("%H:%M")
        time_period = "PM" if fixture_dt.hour >= 12 else "AM"

        # Day name
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        date_str = f"{days[fixture_date.weekday()]}, {months[fixture_date.month - 1]} {fixture_date.day}"

        fixture_data = {
            "id": fixture.get("id"),
            "date": fixture_date.isoformat(),
            "date_str": date_str,
            "time_str": time_str,
            "time_period": time_period,
            "home_id": home_team.get("id"),
            "home_name": home_team.get("name"),
            "home_short": home_team.get("short_code") or home_team.get("name", "")[:3].upper(),
            "home_logo": home_team.get("image_path"),
            "home_score": home_score,
            "away_id": away_team.get("id"),
            "away_name": away_team.get("name"),
            "away_short": away_team.get("short_code") or away_team.get("name", "")[:3].upper(),
            "away_logo": away_team.get("image_path"),
            "away_score": away_score,
            "status_short": match_state["short"],
            "is_live": match_state["is_live"],
            "is_finished": match_state["is_finished"],
            "round": round_number,
        }

        all_fixtures.append(fixture_data)

    # Sort by date
    all_fixtures.sort(key=lambda x: x["date"])

    # Split into recent (finished) and upcoming/all
    recent_fixtures = [f for f in all_fixtures if f["is_finished"]]
    recent_fixtures = recent_fixtures[-10:]  # Last 10 finished
    recent_fixtures.reverse()  # Most recent first

    # Group fixtures by round
    fixtures_by_round = {}
    available_rounds = set()
    for f in all_fixtures:
        r = f.get("round")
        if r:
            try:
                round_num = int(r)
                available_rounds.add(round_num)
                if round_num not in fixtures_by_round:
                    fixtures_by_round[round_num] = []
                fixtures_by_round[round_num].append(f)
            except (ValueError, TypeError):
                pass

    # Sort available rounds
    available_rounds = sorted(available_rounds)

    # Fill in missing rounds sequentially between min and max
    # This ensures navigation goes 19, 20, 21, 22, 23, 24 instead of jumping
    if available_rounds:
        min_round = min(available_rounds)
        max_round = max(available_rounds)
        # Create sequential list from min to max
        available_rounds = list(range(min_round, max_round + 1))
        # Add empty entries for missing rounds in fixtures_by_round
        for r in available_rounds:
            if r not in fixtures_by_round:
                fixtures_by_round[r] = []

    # Determine current round (latest round with any finished or live matches)
    current_round = None
    for r in reversed(available_rounds):
        round_fixtures = fixtures_by_round.get(r, [])
        if any(f["is_finished"] or f["is_live"] for f in round_fixtures):
            current_round = r
            break

    # If no current round found, use the earliest upcoming round
    if current_round is None and available_rounds:
        current_round = available_rounds[0]

    return {
        "fixtures": all_fixtures,
        "recent_fixtures": recent_fixtures,
        "current_round": current_round,
        "fixtures_by_round": fixtures_by_round,
        "available_rounds": available_rounds,
    }

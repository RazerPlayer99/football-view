"""
Football View (Pre-Alpha) - Main FastAPI Application
All data fetched LIVE from API-Football - no local database
"""
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from app import api_client
from app.utils.search.pipeline import search as unified_search
from app.utils.search.models.responses import SearchResponse
from app.view_models import (
    TeamView, StandingRowView, MatchCardView, PlayerView,
    standings_to_view_models, matches_to_view_models, players_to_view_models
)
from config.settings import settings

# Version tracking
APP_VERSION = "v0.2.4"
APP_NAME = "Football View"
APP_STAGE = "Pre-Alpha"

app = FastAPI(
    title=f"{APP_NAME} ({APP_STAGE})",
    description="Live Premier League data from API-Football",
    version=APP_VERSION
)

# Use centralized season config
CURRENT_SEASON = settings.current_season


def parse_season(season_str: str) -> int:
    """Convert '2024-25' or '2024' to season year (2024)."""
    if "-" in season_str:
        return int(season_str.split("-")[0])
    return int(season_str)


def get_refresh_interval(status_short: str, elapsed: Optional[int], is_live: bool, is_finished: bool, match_date: str) -> Optional[int]:
    """
    Calculate adaptive refresh interval in seconds based on match state.

    Returns None if no refresh needed.
    """
    from datetime import datetime, timezone, timedelta

    # Finished matches: brief refresh for final stats, then stop
    if is_finished:
        return None  # No auto-refresh for finished matches

    # Live match refresh based on elapsed time
    if is_live:
        # Halftime: slower refresh
        if status_short in ("HT",):
            return 30
        # High action periods (start, end of halves)
        if elapsed is not None:
            if elapsed <= 15 or (elapsed >= 40 and elapsed <= 45):
                return 10
            elif elapsed >= 75:
                return 10
            elif elapsed >= 45 and elapsed <= 50:
                return 10  # Start of second half
        return 15  # Default live refresh

    # Pre-match refresh based on time to kickoff
    if match_date:
        try:
            kickoff = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            minutes_to_kickoff = (kickoff - now).total_seconds() / 60

            if minutes_to_kickoff > 60:
                return 300  # 5 minutes (waiting)
            elif minutes_to_kickoff > 30:
                return 120  # 2 minutes (lineups may appear)
            elif minutes_to_kickoff > 15:
                return 60  # 1 minute (lineups likely)
            elif minutes_to_kickoff > 0:
                return 30  # 30 seconds (imminent kickoff)
            else:
                return 15  # Past kickoff time, waiting for live status
        except:
            return 60  # Fallback

    return None


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "source": "api-football", "mode": "live"}


@app.get("/version")
def version_info():
    """Version information endpoint."""
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "stage": APP_STAGE,
        "full": f"{APP_NAME} {APP_VERSION} ({APP_STAGE})"
    }


@app.get("/cache/stats")
def cache_stats():
    """Get cache statistics."""
    return api_client.get_cache_stats()


@app.get("/api/analytics")
def search_analytics():
    """
    Get search analytics summary.

    Shows failed queries, low confidence matches, etc.
    Use this to identify areas for improvement.
    """
    from app.utils.search.analytics import get_analytics
    analytics = get_analytics()
    return analytics.get_summary()


@app.get("/api/analytics/failed")
def failed_searches(min_count: int = Query(1, description="Minimum failure count")):
    """Get failed search queries for review."""
    from app.utils.search.analytics import get_analytics
    analytics = get_analytics()
    return {"failed_queries": analytics.get_failed_queries(min_count=min_count)}


@app.get("/api/analytics/low-confidence")
def low_confidence_searches(max_confidence: float = Query(0.85, description="Maximum confidence")):
    """Get low confidence matches for review."""
    from app.utils.search.analytics import get_analytics
    analytics = get_analytics()
    return {"low_confidence_queries": analytics.get_low_confidence_queries(max_confidence=max_confidence)}


@app.get("/api/analytics/export")
def export_analytics():
    """Export all analytics data for offline review."""
    from app.utils.search.analytics import get_analytics
    analytics = get_analytics()
    return analytics.export_for_review()


# =============================================================================
# DASHBOARD API
# =============================================================================

@app.get("/api/dashboard")
def api_dashboard(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format, defaults to today"),
    season: int = Query(default=settings.current_season, description="Season year"),
):
    """
    Get dashboard data: matches for a specific date across all leagues.

    Returns matches grouped by competition for the landing page.
    Uses MatchCardPayload for stable UI contract.
    """
    from datetime import datetime, timedelta
    from app.view_models import MatchCardPayload

    # Parse date or use today
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            target_date = datetime.now().date()
    else:
        target_date = datetime.now().date()

    date_str = target_date.strftime("%Y-%m-%d")

    try:
        # Fetch matches for all supported leagues on this date
        result = api_client.get_matches_multi_league(
            season=season,
            from_date=date_str,
            to_date=date_str,
            limit_per_league=20,
        )

        # Convert raw matches to stable MatchCardPayload
        raw_matches = result.get("all_matches", [])
        match_payloads = [MatchCardPayload.from_raw_match(m).to_dict() for m in raw_matches]

        # Also convert by_competition
        by_competition_payloads = {}
        for comp_name, comp_matches in result.get("by_competition", {}).items():
            by_competition_payloads[comp_name] = [
                MatchCardPayload.from_raw_match(m).to_dict() for m in comp_matches
            ]

        return {
            "date": date_str,
            "season": season,
            "by_competition": by_competition_payloads,
            "all_matches": match_payloads,
            "total_matches": len(match_payloads),
        }
    except Exception as e:
        return {
            "date": date_str,
            "season": season,
            "by_competition": {},
            "all_matches": [],
            "total_matches": 0,
            "error": str(e),
        }


@app.get("/api/config")
def api_config():
    """Expose runtime configuration for the dashboard UI."""
    leagues = [
        {
            "id": league_id,
            "name": name,
        }
        for league_id, name in api_client.SUPPORTED_LEAGUES.items()
    ]
    return {
        "current_season": settings.current_season,
        "leagues": leagues,
    }


# =============================================================================
# UNIFIED SEARCH API
# =============================================================================

class SearchRequest(BaseModel):
    """Request body for search endpoint."""
    query: str
    session_id: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


@app.post("/api/search")
def api_search(request: SearchRequest, req: Request):
    """
    Unified search endpoint.

    Single search bar that handles all query types:
    - Team lookups: "Arsenal", "Man United"
    - Player lookups: "Salah", "Haaland"
    - Match lookups: "Arsenal vs Chelsea", "next Arsenal game"
    - Standings: "table", "standings"
    - Top scorers/assists: "top scorers", "golden boot"
    - Schedule: "games this weekend", "fixtures tomorrow"
    - Comparisons: "Salah vs Haaland", "compare Arsenal Chelsea"

    Returns structured response with:
    - type: Response type (table, team_card, player_card, match_card, etc.)
    - data: Type-specific payload
    - as_of: Data freshness timestamp
    - sources_used: Data sources consulted
    - assumptions: Any defaults applied
    - missing_capabilities: Data not yet available

    Rate limited to 60 requests/minute per client.
    """
    # Get client IP for rate limiting
    client_ip = req.client.host if req.client else None

    # Extract options
    season = None
    league_id = None
    if request.options:
        season = request.options.get("season")
        league_id = request.options.get("league_id")

    # Execute search
    response = unified_search(
        query=request.query,
        session_id=request.session_id,
        client_id=client_ip,
        season=season,
        league_id=league_id,
    )

    # Check for rate limiting
    if response.type == "error" and response.data.error_type == "rate_limited":
        return JSONResponse(
            status_code=429,
            content=response.to_dict(),
            headers={"Retry-After": str(response.data.retry_after_seconds or 30)},
        )

    return response.to_dict()


@app.get("/api/search")
def api_search_get(
    q: str = Query(..., description="Search query"),
    session_id: Optional[str] = Query(None, description="Session ID for context"),
    season: Optional[int] = Query(None, description="Season year override"),
    league_id: Optional[int] = Query(None, description="League ID override"),
    req: Request = None,
):
    """
    GET version of search endpoint for simple queries.

    Example: /api/search?q=Arsenal&season=2024
    """
    client_ip = req.client.host if req and req.client else None

    response = unified_search(
        query=q,
        session_id=session_id,
        client_id=client_ip,
        season=season,
        league_id=league_id,
    )

    if response.type == "error" and response.data.error_type == "rate_limited":
        return JSONResponse(
            status_code=429,
            content=response.to_dict(),
            headers={"Retry-After": str(response.data.retry_after_seconds or 30)},
        )

    return response.to_dict()


@app.get("/api/search/suggest")
def api_search_suggest(
    q: str = Query(..., min_length=2, description="Partial search query"),
    limit: int = Query(8, ge=1, le=20, description="Max suggestions"),
):
    """
    Autocomplete suggestions endpoint with token-based matching.

    Returns quick suggestions for players and teams based on partial query.
    Uses forgiving token matching - tolerates typos and partial matches.

    Example: /api/search/suggest?q=sho
    Returns: {"suggestions": [{"name": "Luke Shaw", "type": "player", ...}]}
    """
    from app.utils.search.entities import (
        AliasDatabase, fuzzy_match, get_fuzzy_threshold, normalize_for_matching,
        tokenize_query, get_entity_tokens, multi_token_match_score, token_match_score
    )

    query = q.strip().lower()
    suggestions = []
    seen_ids = set()

    # Load alias database
    alias_db = AliasDatabase()
    threshold = max(0.50, get_fuzzy_threshold(query) - 0.10)  # More lenient for autocomplete

    # Tokenize query for smarter matching
    tokens = get_entity_tokens(query) or [query]  # Fallback to full query if no entity tokens

    # Search players in aliases with token-based matching
    for player_id, player_data in alias_db.players.items():
        canonical = player_data["canonical"]
        aliases = player_data.get("aliases", [])

        # Use multi-token matching (forgiving)
        best_match = multi_token_match_score(tokens, canonical, aliases)

        # BONUS: Direct containment check (typing partial names)
        canonical_lower = canonical.lower()
        for token in tokens:
            if token in canonical_lower:
                best_match = max(best_match, 0.85)
            # Check last name match specifically
            name_parts = canonical_lower.split()
            if len(name_parts) > 1:
                last_name = name_parts[-1]
                if token == last_name:
                    best_match = max(best_match, 0.95)
                elif last_name.startswith(token) and len(token) >= 2:
                    best_match = max(best_match, 0.80)

        # Check aliases for containment
        for alias in aliases:
            alias_lower = alias.lower()
            for token in tokens:
                if token in alias_lower or alias_lower.startswith(token):
                    best_match = max(best_match, 0.85)

        if best_match >= threshold and f"player_{player_id}" not in seen_ids:
            suggestions.append({
                "id": int(player_id),
                "name": canonical,
                "type": "player",
                "team_id": player_data.get("team_id"),
                "confidence": round(best_match, 3),
            })
            seen_ids.add(f"player_{player_id}")

    # Search teams in aliases with token-based matching
    for team_id, team_data in alias_db.teams.items():
        canonical = team_data["canonical"]
        aliases = team_data.get("aliases", [])

        # Use multi-token matching
        best_match = multi_token_match_score(tokens, canonical, aliases)

        # BONUS: Direct containment check
        canonical_lower = canonical.lower()
        for token in tokens:
            if token in canonical_lower:
                best_match = max(best_match, 0.85)

        # Check aliases for containment
        for alias in aliases:
            alias_lower = alias.lower()
            for token in tokens:
                if token in alias_lower or alias_lower.startswith(token):
                    best_match = max(best_match, 0.85)

        if best_match >= threshold and f"team_{team_id}" not in seen_ids:
            suggestions.append({
                "id": int(team_id),
                "name": canonical,
                "type": "team",
                "confidence": round(best_match, 3),
            })
            seen_ids.add(f"team_{team_id}")

    # Also search API for players (catches players not in aliases)
    if len(query) >= 3:
        try:
            # Use API search for broader coverage
            result = api_client.search_players(query, season=CURRENT_SEASON, limit=10)
            api_players = result.get("players", [])
            for p in api_players:
                player_id = p.get("id")
                if f"player_{player_id}" not in seen_ids:
                    # Score API results using token matching too
                    api_name = p.get("name", "")
                    api_score = multi_token_match_score(tokens, api_name, [])
                    api_score = max(api_score, 0.75)  # Minimum score for API matches

                    suggestions.append({
                        "id": player_id,
                        "name": api_name,
                        "type": "player",
                        "team": p.get("team", {}).get("name"),
                        "team_id": p.get("team", {}).get("id"),
                        "photo": p.get("photo"),
                        "confidence": round(api_score, 3),
                    })
                    seen_ids.add(f"player_{player_id}")
        except Exception:
            pass  # API search is best-effort

    # Sort by confidence and limit
    suggestions.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    suggestions = suggestions[:limit]

    return {"suggestions": suggestions, "query": q}


@app.get("/api/predicted-xi")
def api_predicted_xi(
    fixture_id: int = Query(..., description="Fixture/match ID"),
    home_team_id: Optional[int] = Query(None, description="Home team ID (optional, will be fetched if not provided)"),
    away_team_id: Optional[int] = Query(None, description="Away team ID (optional, will be fetched if not provided)"),
):
    """
    Get predicted starting XI for a match.

    Returns predicted lineups for both home and away teams including:
    - Formation
    - Predicted players with positions
    - Confidence scores
    """
    from app.predicted_xi import get_predicted_xi_provider
    from concurrent.futures import ThreadPoolExecutor

    # If team IDs not provided, try to fetch match data to get them
    if not home_team_id or not away_team_id:
        try:
            match_data = client.get_fixture(fixture_id)
            if match_data:
                home_team_id = home_team_id or match_data.get("teams", {}).get("home", {}).get("id")
                away_team_id = away_team_id or match_data.get("teams", {}).get("away", {}).get("id")
        except Exception:
            pass

    if not home_team_id and not away_team_id:
        return {"home": None, "away": None, "error": "Could not determine team IDs"}

    try:
        predicted_provider = get_predicted_xi_provider()

        result = {"home": None, "away": None}

        # Fetch predictions in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            if home_team_id:
                futures["home"] = executor.submit(
                    predicted_provider.get_or_generate_prediction,
                    match_id=fixture_id,
                    team_id=home_team_id,
                )
            if away_team_id:
                futures["away"] = executor.submit(
                    predicted_provider.get_or_generate_prediction,
                    match_id=fixture_id,
                    team_id=away_team_id,
                )

            for key, future in futures.items():
                prediction = future.result()
                if prediction:
                    result[key] = {
                        "formation": prediction.formation,
                        "formation_confidence": prediction.formation_confidence,
                        "players": [
                            {
                                "name": p.player_name,
                                "position": p.position,
                                "confidence": p.confidence,
                                "player_id": p.player_id,
                            }
                            for p in prediction.starting_xi
                        ],
                        "bench": [
                            {
                                "name": p.player_name,
                                "position": p.position,
                                "player_id": p.player_id,
                            }
                            for p in (prediction.bench or [])
                        ],
                        "overall_confidence": prediction.overall_confidence,
                    }

        return result
    except Exception as e:
        return {"home": None, "away": None, "error": str(e)}


@app.get("/api/pre-match/{match_id}")
def api_pre_match(match_id: int):
    """
    Get comprehensive pre-match data for an upcoming fixture.
    Returns PreMatchPayload - a stable contract the UI depends on.
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.predicted_xi import get_predicted_xi_provider
    from app.view_models import (
        H2HPayload, SeasonStatsPayload, LineupPayload, LineupPlayerPayload,
        PreMatchTeamPayload, get_team_form, find_team_in_standings
    )

    # Get match data first
    match_data = api_client.get_match_by_id(match_id)
    if not match_data:
        raise HTTPException(status_code=404, detail="Match not found")

    home_team = match_data.get("home_team", {}) or {}
    away_team = match_data.get("away_team", {}) or {}
    home_team_id = home_team.get("id")
    away_team_id = away_team.get("id")
    league_id = match_data.get("league", {}).get("id")

    # Initialize result with stable payload structure
    result = {
        "match": {
            "id": match_id,
            "date": match_data.get("date"),
            "venue": match_data.get("venue"),
            "referee": match_data.get("referee"),
            "status": match_data.get("status"),
            "league": match_data.get("league", {}).get("name"),
            "round": match_data.get("league", {}).get("round"),
            "league_id": league_id,
        },
        "home_team": {
            "id": home_team_id,
            "name": home_team.get("name"),
            "logo": home_team.get("logo"),
            "form": [],
            "season_stats": None,
        },
        "away_team": {
            "id": away_team_id,
            "name": away_team.get("name"),
            "logo": away_team.get("logo"),
            "form": [],
            "season_stats": None,
        },
        "h2h": {
            "total_matches": 0,
            "home_wins": 0,
            "away_wins": 0,
            "draws": 0,
            "recent_matches": [],
        },
        "lineups": {"home": None, "away": None},
    }

    # Fetch data in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}

        # Get team fixtures for form
        if home_team_id:
            futures["home_fixtures"] = executor.submit(
                api_client.get_team_fixtures,
                home_team_id, CURRENT_SEASON, league_id or 39, 10
            )
        if away_team_id:
            futures["away_fixtures"] = executor.submit(
                api_client.get_team_fixtures,
                away_team_id, CURRENT_SEASON, league_id or 39, 10
            )

        # Get standings for season stats
        if league_id:
            futures["standings"] = executor.submit(
                api_client.get_standings,
                CURRENT_SEASON, league_id
            )

        # Get H2H matches
        if home_team_id and away_team_id:
            futures["h2h"] = executor.submit(
                api_client.get_matches,
                CURRENT_SEASON, league_id, home_team_id, 30
            )

        # Get predicted lineups from prediction engine
        predicted_provider = get_predicted_xi_provider()
        if home_team_id:
            futures["home_lineup"] = executor.submit(
                predicted_provider.get_or_generate_prediction,
                match_id=match_id, team_id=home_team_id
            )
        if away_team_id:
            futures["away_lineup"] = executor.submit(
                predicted_provider.get_or_generate_prediction,
                match_id=match_id, team_id=away_team_id
            )

        # Process results using view_models helpers
        try:
            if "home_fixtures" in futures:
                home_fix = futures["home_fixtures"].result()
                result["home_team"]["form"] = get_team_form(
                    home_team_id, home_fix.get("past", [])
                )
        except Exception:
            pass

        try:
            if "away_fixtures" in futures:
                away_fix = futures["away_fixtures"].result()
                result["away_team"]["form"] = get_team_form(
                    away_team_id, away_fix.get("past", [])
                )
        except Exception:
            pass

        try:
            if "standings" in futures:
                standings_data = futures["standings"].result()
                standings = standings_data.get("standings", [])

                home_stats = find_team_in_standings(standings, home_team_id)
                if home_stats:
                    result["home_team"]["season_stats"] = home_stats.to_dict()

                away_stats = find_team_in_standings(standings, away_team_id)
                if away_stats:
                    result["away_team"]["season_stats"] = away_stats.to_dict()
        except Exception:
            pass

        try:
            if "h2h" in futures:
                h2h_data = futures["h2h"].result()
                all_matches = h2h_data.get("matches", [])
                # Filter to only matches between these two teams
                h2h_matches = [
                    m for m in all_matches
                    if (m.get("home_team", {}).get("id") == away_team_id or
                        m.get("away_team", {}).get("id") == away_team_id)
                ]
                # Use payload contract for H2H aggregation
                h2h_payload = H2HPayload.aggregate(h2h_matches, home_team_id, away_team_id)
                result["h2h"] = h2h_payload.to_dict()
        except Exception:
            pass

        # Process predicted lineups - UI doesn't care about source
        try:
            if "home_lineup" in futures:
                prediction = futures["home_lineup"].result()
                if prediction and prediction.starting_xi:
                    result["lineups"]["home"] = {
                        "formation": prediction.formation,
                        "players": [
                            {
                                "name": p.player_name,
                                "position": p.position,
                                "player_id": p.player_id,
                                "number": getattr(p, 'squad_number', None),
                            }
                            for p in prediction.starting_xi
                        ],
                    }
        except Exception:
            pass

        try:
            if "away_lineup" in futures:
                prediction = futures["away_lineup"].result()
                if prediction and prediction.starting_xi:
                    result["lineups"]["away"] = {
                        "formation": prediction.formation,
                        "players": [
                            {
                                "name": p.player_name,
                                "position": p.position,
                                "player_id": p.player_id,
                                "number": getattr(p, 'squad_number', None),
                            }
                            for p in prediction.starting_xi
                        ],
                    }
        except Exception:
            pass

    return result


@app.get("/", response_class=HTMLResponse)
def home():
    """Dashboard landing page with matches and league stats."""
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    else:
        # Fallback if template doesn't exist
        return HTMLResponse(content="<h1>Dashboard template not found</h1>", status_code=500)


@app.get("/v4", response_class=HTMLResponse)
def dashboard_v4():
    """New mobile-first dashboard design (v4)."""
    template_path = Path(__file__).parent / "templates" / "dashboard-v4.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    else:
        return HTMLResponse(content="<h1>Dashboard V4 template not found</h1>", status_code=500)


@app.get("/old-home", response_class=HTMLResponse)
def old_home():
    """Legacy simple welcome page with API links."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Football View - Developer</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 { color: #2c3e50; }
            .status { color: #27ae60; font-weight: bold; }
            .live-badge {
                background: #e74c3c;
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                margin-left: 10px;
            }
            ul { line-height: 1.8; }
            a { color: #3498db; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>⚽ Football View <span class="live-badge">LIVE DATA</span></h1>
            <p class="status">✓ Server is running - fetching live data from API-Football</p>
            <h2>UI Pages:</h2>
            <ul>
                <li><strong><a href="/">/ - Dashboard (NEW)</a></strong></li>
                <li><strong><a href="/ui/search">/ui/search</a> - Search Teams & Players</strong></li>
                <li><a href="/ui/standings">/ui/standings</a> - League Standings Table</li>
                <li><a href="/ui/matches">/ui/matches</a> - Match Results</li>
                <li><a href="/ui/top-scorers">/ui/top-scorers</a> - Top Scorers</li>
            </ul>
            <h2>API Endpoints:</h2>
            <ul>
                <li><a href="/health">/health</a> - Health check</li>
                <li><a href="/docs">/docs</a> - Interactive API documentation</li>
                <li><a href="/api/dashboard">/api/dashboard</a> - Dashboard data (JSON)</li>
                <li><a href="/teams?season=__CURRENT_SEASON__">/teams</a> - Teams (JSON)</li>
                <li><a href="/standings?season=__CURRENT_SEASON__">/standings</a> - League standings (JSON)</li>
                <li><a href="/matches?season=__CURRENT_SEASON__&limit=10">/matches</a> - Matches (JSON)</li>
                <li><a href="/players/top-scorers?season=__CURRENT_SEASON__&limit=20">/players/top-scorers</a> - Top scorers (JSON)</li>
            </ul>
            <p><em>All data fetched live from API-Football</em></p>
        </div>
    </body>
    </html>
    """
    return html_content.replace("__CURRENT_SEASON__", str(settings.current_season))


# ===== STANDINGS =====
# NOTE: Standalone standings page is disabled. Standings are now accessed
# through the search system (e.g., "premier league standings", "la liga table")
# which returns league-specific results with proper context.

@app.get("/standings")
def get_standings(
    season: str = Query(default=str(settings.current_season), description="Season year (e.g., '2024' for 2024-25)"),
    league: int = Query(default=settings.premier_league_id, description="League ID (see /api/config)"),
    forceRefresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get live standings for any supported league.
    Returns scope, season, league_id, standings list, and cache metadata.

    This endpoint is primarily used by the search system. For direct access,
    use the search: "premier league standings", "la liga table", etc.
    """
    try:
        season_year = parse_season(season)
        result = api_client.get_standings(season_year, league_id=league, force_refresh=forceRefresh)
        if not result or not result.get("standings"):
            raise HTTPException(status_code=404, detail=f"No standings found for season {season}, league {league}")
        # Add cache metadata
        meta = api_client.get_last_cache_meta()
        if meta:
            result["_meta"] = meta.to_dict()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== TEAMS =====

@app.get("/teams")
def list_teams(
    season: str = Query(default=str(settings.current_season), description="Season year")
):
    """Get all Premier League teams for a season."""
    try:
        season_year = parse_season(season)
        result = api_client.get_teams(season_year)
        result["count"] = len(result.get("teams", []))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/teams/{team_id}")
def get_team(team_id: int):
    """Get team details by ID."""
    try:
        team = api_client.get_team_by_id(team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        return team
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/teams/{team_id}/players")
def get_team_players(
    team_id: int,
    season: str = Query(default=str(settings.current_season), description="Season year")
):
    """Get all players for a team."""
    try:
        season_year = parse_season(season)
        result = api_client.get_team_players(team_id, season_year)
        result["count"] = len(result.get("players", []))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== MATCHES =====

@app.get("/matches")
def get_matches(
    season: str = Query(default=str(settings.current_season), description="Season year"),
    team_id: Optional[int] = Query(None, description="Filter by team ID"),
    from_date: Optional[str] = Query(None, description="From date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="To date (YYYY-MM-DD)"),
    limit: int = Query(default=50, description="Max results"),
):
    """Get Premier League matches."""
    try:
        season_year = parse_season(season)
        result = api_client.get_matches(
            season_year,
            team_id=team_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
        result["count"] = len(result.get("matches", []))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/matches/{match_id}")
def get_match(match_id: int):
    """Get match details by ID."""
    try:
        match = api_client.get_match_by_id(match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        return match
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== PLAYERS =====

@app.get("/players/top-scorers")
def get_top_scorers(
    season: str = Query(default=str(settings.current_season), description="Season year"),
    league: int = Query(default=settings.premier_league_id, description="League ID (see /api/config)"),
    limit: int = Query(default=20, description="Number of top scorers"),
):
    """Get top scorers for a season and league."""
    try:
        season_year = parse_season(season)
        result = api_client.get_top_scorers(season_year, league_id=league, limit=limit)
        if not result or not result.get("players"):
            raise HTTPException(status_code=404, detail=f"No players found for season {season}")
        result["count"] = len(result.get("players", []))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/players/top-assists")
def get_top_assists(
    season: str = Query(default=str(settings.current_season), description="Season year"),
    limit: int = Query(default=20, description="Number of top assist providers"),
):
    """Get top assist providers for a season."""
    try:
        season_year = parse_season(season)
        result = api_client.get_top_assists(season_year, limit=limit)
        if not result or not result.get("players"):
            raise HTTPException(status_code=404, detail=f"No players found for season {season}")
        result["count"] = len(result.get("players", []))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/players/{player_id}")
def get_player(
    player_id: int,
    season: str = Query(default=str(settings.current_season), description="Season year"),
    scope: str = Query(default="all_competitions", description="all_competitions or league_only"),
):
    """Get detailed player stats by ID."""
    try:
        season_year = parse_season(season)
        player = api_client.get_player_by_id(player_id, season_year, scope=scope)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        return player
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/players/{player_id}/matches")
def get_player_matches(
    player_id: int,
    season: str = Query(default=str(settings.current_season), description="Season year"),
    league_id: Optional[int] = Query(None, description="Filter by league ID (see /api/config)"),
    limit: int = Query(default=10, description="Number of matches to return"),
):
    """
    Get player's recent match appearances with per-game stats.
    Returns last N matches with minutes, position, goals, assists, cards, and rating.
    """
    try:
        season_year = parse_season(season)
        match_log = api_client.get_player_match_log(
            player_id=player_id,
            season=season_year,
            league_id=league_id,
            limit=limit,
        )
        return match_log
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== SEARCH =====

@app.get("/search")
def search(
    q: str = Query(..., min_length=2, description="Search query"),
    season: str = Query(default=str(settings.current_season), description="Season year"),
    limit: int = Query(default=20, description="Max results per category"),
):
    """Search for teams and players."""
    try:
        season_year = parse_season(season)
        teams_result = api_client.search_teams(q, season_year, limit=limit)
        players_result = api_client.search_players(q, season_year, limit=limit)

        teams = teams_result.get("teams", [])
        players = players_result.get("players", [])

        return {
            "scope": "league_only",
            "query": q,
            "season": season_year,
            "teams": teams,
            "players": players,
            "team_count": len(teams),
            "player_count": len(players),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== UI PAGES =====

@app.get("/ui/search", response_class=HTMLResponse)
def search_ui_v2():
    """Search UI page - redesigned with FotMob/Apple aesthetics."""
    template_path = Path(__file__).parent / "templates" / "search_v2.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    # Fallback to old search if template not found
    return search_ui_legacy()


@app.get("/ui/search-legacy", response_class=HTMLResponse)
def search_ui_legacy():
    """Legacy search UI page (old design)."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Search - Football View</title>
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                max-width: 900px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f0f2f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            h1 { color: #2c3e50; margin-bottom: 20px; }
            .live-badge {
                background: #e74c3c;
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                animation: pulse 2s infinite;
            }
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.7; }
            }
            .search-box {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            .search-wrapper {
                position: relative;
                flex: 1;
                min-width: 0;
            }
            #search-input {
                display: block;
                width: 100%;
                padding: 14px 18px;
                font-size: 16px;
                border: 2px solid #ddd;
                border-radius: 8px;
                outline: none;
                transition: border-color 0.2s;
                box-sizing: border-box;
            }
            #search-input:focus { border-color: #3498db; }
            .autocomplete-dropdown {
                position: absolute;
                top: 100%;
                left: 0;
                right: 0;
                background: white;
                border: 1px solid #ddd;
                border-top: none;
                border-radius: 0 0 8px 8px;
                max-height: 300px;
                overflow-y: auto;
                z-index: 1000;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                display: none;
            }
            .autocomplete-dropdown.active { display: block; }
            .autocomplete-item {
                padding: 12px 16px;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 12px;
                border-bottom: 1px solid #f0f0f0;
            }
            .autocomplete-item:last-child { border-bottom: none; }
            .autocomplete-item:hover, .autocomplete-item.selected {
                background: #f5f8fa;
            }
            .autocomplete-item img {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                object-fit: cover;
            }
            .autocomplete-item .name {
                font-weight: 500;
                color: #2c3e50;
            }
            .autocomplete-item .meta {
                font-size: 12px;
                color: #7f8c8d;
            }
            .autocomplete-item .type-badge {
                font-size: 10px;
                padding: 2px 6px;
                border-radius: 4px;
                text-transform: uppercase;
                margin-left: auto;
            }
            .autocomplete-item .type-badge.player { background: #e8f5e9; color: #2e7d32; }
            .autocomplete-item .type-badge.team { background: #e3f2fd; color: #1565c0; }
            #search-btn {
                padding: 14px 28px;
                background: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-size: 16px;
                font-weight: 500;
                transition: background 0.2s;
            }
            #search-btn:hover { background: #2980b9; }
            .search-hints {
                font-size: 13px;
                color: #7f8c8d;
                margin-bottom: 20px;
            }
            .search-hints code {
                background: #ecf0f1;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: monospace;
            }

            /* Results */
            .results-section { margin-top: 20px; }
            .results-section h2 {
                color: #2c3e50;
                border-bottom: 2px solid #eee;
                padding-bottom: 10px;
                font-size: 18px;
            }
            .result-item {
                padding: 14px;
                margin: 10px 0;
                background: #f9f9f9;
                border-radius: 8px;
                border-left: 4px solid #3498db;
                display: flex;
                align-items: center;
                gap: 14px;
                transition: background 0.2s;
            }
            .result-item:hover { background: #f0f0f0; }
            .result-item img {
                width: 48px;
                height: 48px;
                object-fit: contain;
            }
            .result-item a { color: #2c3e50; text-decoration: none; font-weight: 600; }
            .result-item a:hover { text-decoration: underline; }
            .result-meta { color: #666; font-size: 14px; margin-top: 4px; }
            .stats { color: #27ae60; font-weight: 600; }

            /* Disambiguation */
            .disambiguation {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 20px;
                border-radius: 12px;
                color: white;
                margin-bottom: 20px;
            }
            .disambiguation h3 { margin: 0 0 15px 0; }
            .disambiguation-options { display: flex; flex-wrap: wrap; gap: 10px; }
            .disambiguation-option {
                background: white;
                color: #2c3e50;
                padding: 10px 16px;
                border-radius: 6px;
                cursor: pointer;
                font-weight: 500;
                transition: transform 0.2s;
            }
            .disambiguation-option:hover { transform: scale(1.02); }

            /* Comparison */
            .comparison-container { margin-top: 20px; }
            .comparison-header {
                display: flex;
                justify-content: space-around;
                align-items: center;
                margin-bottom: 20px;
            }
            .comparison-entity {
                text-align: center;
            }
            .comparison-entity img {
                width: 80px;
                height: 80px;
                object-fit: contain;
                margin-bottom: 10px;
            }
            .comparison-entity h3 { margin: 0; color: #2c3e50; }
            .comparison-vs {
                font-size: 24px;
                font-weight: bold;
                color: #e74c3c;
            }
            .comparison-metrics { margin-top: 20px; }
            .comparison-metric {
                display: flex;
                align-items: center;
                padding: 12px 0;
                border-bottom: 1px solid #eee;
            }
            .metric-label {
                flex: 1;
                text-align: center;
                font-weight: 500;
                color: #7f8c8d;
            }
            .metric-value {
                flex: 1;
                text-align: center;
                font-size: 18px;
                font-weight: 600;
            }
            .metric-value.winner { color: #27ae60; }

            /* Error */
            .error-message {
                background: #fff3cd;
                border: 1px solid #ffc107;
                padding: 20px;
                border-radius: 8px;
                color: #856404;
            }
            .error-message h3 { margin: 0 0 10px 0; }
            .suggestions { margin-top: 15px; }
            .suggestions a {
                display: inline-block;
                background: #3498db;
                color: white;
                padding: 8px 14px;
                border-radius: 6px;
                text-decoration: none;
                margin: 5px 5px 5px 0;
                font-size: 14px;
            }

            /* Table */
            .data-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }
            .data-table th, .data-table td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #eee;
            }
            .data-table th {
                background: #f8f9fa;
                font-weight: 600;
                color: #2c3e50;
            }
            .data-table tr:hover { background: #f9f9f9; }

            .no-results { color: #999; font-style: italic; padding: 20px; text-align: center; }
            .back-link { margin-bottom: 20px; }
            .back-link a { color: #3498db; text-decoration: none; }
            #loading { display: none; color: #666; padding: 20px; text-align: center; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="back-link"><a href="/">← Back to Home</a></div>
            <h1>Search <span class="live-badge">LIVE</span></h1>
            <p class="search-hints">
                Try: <code>Arsenal</code>, <code>Salah stats</code>, <code>top scorers</code>,
                <code>Haaland vs Salah</code>, <code>next Arsenal match</code>
            </p>

            <div class="search-box">
                <div class="search-wrapper">
                    <input type="text" id="search-input" placeholder="Ask anything about football..." autofocus autocomplete="off">
                    <div id="autocomplete-dropdown" class="autocomplete-dropdown"></div>
                </div>
                <button id="search-btn">Search</button>
            </div>

            <div id="loading">Searching...</div>
            <div id="results"></div>
        </div>

        <script>
            const searchInput = document.getElementById('search-input');
            const searchBtn = document.getElementById('search-btn');
            const resultsDiv = document.getElementById('results');
            const loadingDiv = document.getElementById('loading');
            const currentSeason = __CURRENT_SEASON__;

            async function doSearch(query) {
                // Always hide dropdown when searching
                const dd = document.getElementById('autocomplete-dropdown');
                if (dd) {
                    dd.classList.remove('active');
                    dd.innerHTML = '';
                }

                query = query || searchInput.value.trim();
                if (query.length < 2) {
                    resultsDiv.innerHTML = '<p class="no-results">Please enter at least 2 characters</p>';
                    return;
                }

                // Update input with query (for disambiguation clicks)
                searchInput.value = query;
                loadingDiv.style.display = 'block';
                resultsDiv.innerHTML = '';

                try {
                    const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&season=${currentSeason}`);
                    const data = await response.json();

                    loadingDiv.style.display = 'none';
                    resultsDiv.innerHTML = renderResponse(data);

                } catch (error) {
                    loadingDiv.style.display = 'none';
                    resultsDiv.innerHTML = '<p class="no-results">Error fetching data. Please try again.</p>';
                }
            }

            function renderResponse(data) {
                switch (data.type) {
                    case 'disambiguation':
                        return renderDisambiguation(data.data);
                    case 'comparison':
                        return renderComparison(data.data);
                    case 'player_card':
                        return renderPlayerCard(data.data);
                    case 'team_card':
                        return renderTeamCard(data.data);
                    case 'table':
                        return renderTable(data.data);
                    case 'error':
                        return renderError(data.data);
                    default:
                        return `<p class="no-results">Unknown response type: ${data.type}</p>`;
                }
            }

            function renderDisambiguation(data) {
                let html = `<div class="disambiguation">
                    <h3>${data.question || 'Which did you mean?'}</h3>
                    <div class="disambiguation-options">`;

                data.options.forEach(opt => {
                    html += `<div class="disambiguation-option" onclick="doSearch('${opt.value}')">${opt.label}</div>`;
                });

                html += '</div></div>';
                return html;
            }

            function renderComparison(data) {
                const e1 = data.entities[0];
                const e2 = data.entities[1];
                const p1 = e1.player || e1.team || {};
                const p2 = e2.player || e2.team || {};

                let html = `<div class="comparison-container">
                    <div class="comparison-header">
                        <div class="comparison-entity">
                            <img src="${p1.photo || p1.logo || ''}" alt="">
                            <h3><a href="/ui/${data.entity_type}s/${p1.id}">${p1.name}</a></h3>
                            ${p1.team ? `<div class="result-meta">${p1.team.name || ''}</div>` : ''}
                        </div>
                        <div class="comparison-vs">VS</div>
                        <div class="comparison-entity">
                            <img src="${p2.photo || p2.logo || ''}" alt="">
                            <h3><a href="/ui/${data.entity_type}s/${p2.id}">${p2.name}</a></h3>
                            ${p2.team ? `<div class="result-meta">${p2.team.name || ''}</div>` : ''}
                        </div>
                    </div>
                    <div class="comparison-metrics">`;

                data.comparison_metrics.forEach(metric => {
                    const v1Class = metric.winner_index === 0 ? 'winner' : '';
                    const v2Class = metric.winner_index === 1 ? 'winner' : '';
                    html += `<div class="comparison-metric">
                        <div class="metric-value ${v1Class}">${metric.values[0]}</div>
                        <div class="metric-label">${metric.label}</div>
                        <div class="metric-value ${v2Class}">${metric.values[1]}</div>
                    </div>`;
                });

                html += '</div></div>';
                return html;
            }

            function renderPlayerCard(data) {
                const p = data.player;
                const stats = data.season_stats || {};
                return `<div class="results-section">
                    <div class="result-item" style="border-left-color: #27ae60;">
                        <img src="${p.photo || ''}" alt="">
                        <div>
                            <a href="/ui/players/${p.id}">${p.name}</a>
                            <div class="result-meta">
                                ${p.team?.name || ''} | ${p.position || ''}
                            </div>
                            <div class="stats" style="margin-top: 8px;">
                                ${stats.goals || p.goals || 0} goals,
                                ${stats.assists || p.assists || 0} assists
                            </div>
                        </div>
                    </div>
                </div>`;
            }

            function renderTeamCard(data) {
                const t = data.team;
                return `<div class="results-section">
                    <div class="result-item" style="border-left-color: #9b59b6;">
                        <img src="${t.logo || ''}" alt="">
                        <div>
                            <a href="/ui/teams/${t.id}">${t.name}</a>
                            <div class="result-meta">${t.venue || ''}</div>
                            ${data.standings_position ? `<div class="stats">Position: ${data.standings_position}</div>` : ''}
                        </div>
                    </div>
                </div>`;
            }

            function renderTable(data) {
                let html = `<div class="results-section">
                    <h2>${data.title}</h2>
                    <table class="data-table">
                        <thead><tr>`;

                data.columns.forEach(col => {
                    html += `<th>${col.label}</th>`;
                });
                html += '</tr></thead><tbody>';

                data.rows.forEach(row => {
                    html += '<tr>';
                    data.columns.forEach(col => {
                        const val = row[col.key] ?? '';
                        // Make player/team names clickable
                        if (col.key === 'name' && row.id) {
                            const type = row.position ? 'players' : 'teams';
                            html += `<td><a href="/ui/${type}/${row.id}">${val}</a></td>`;
                        } else {
                            html += `<td>${val}</td>`;
                        }
                    });
                    html += '</tr>';
                });

                html += '</tbody></table></div>';
                return html;
            }

            function renderError(data) {
                let html = `<div class="error-message">
                    <h3>${data.message}</h3>`;

                if (data.suggestions && data.suggestions.length > 0) {
                    html += '<div class="suggestions">';
                    data.suggestions.forEach(s => {
                        html += `<a href="#" onclick="doSearch('${s}'); return false;">${s}</a>`;
                    });
                    html += '</div>';
                }

                html += '</div>';
                return html;
            }

            // Autocomplete functionality
            const dropdown = document.getElementById('autocomplete-dropdown');
            let debounceTimer = null;
            let selectedIndex = -1;
            let suggestions = [];

            async function fetchSuggestions(query) {
                if (query.length < 2) {
                    hideDropdown();
                    return;
                }

                try {
                    const response = await fetch(`/api/search/suggest?q=${encodeURIComponent(query)}`);
                    const data = await response.json();
                    suggestions = data.suggestions || [];
                    renderSuggestions();
                } catch (error) {
                    hideDropdown();
                }
            }

            function renderSuggestions() {
                if (suggestions.length === 0) {
                    hideDropdown();
                    return;
                }

                dropdown.innerHTML = suggestions.map((s, i) => `
                    <div class="autocomplete-item${i === selectedIndex ? ' selected' : ''}" data-index="${i}">
                        ${s.photo ? `<img src="${s.photo}" alt="">` : '<div style="width:32px;height:32px;background:#ddd;border-radius:50%;"></div>'}
                        <div>
                            <div class="name">${s.name}</div>
                            ${s.team ? `<div class="meta">${s.team}</div>` : ''}
                        </div>
                        <span class="type-badge ${s.type}">${s.type}</span>
                    </div>
                `).join('');

                dropdown.classList.add('active');

                // Add click handlers
                dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
                    item.addEventListener('click', () => {
                        const idx = parseInt(item.dataset.index);
                        selectSuggestion(idx);
                    });
                });
            }

            function selectSuggestion(index) {
                const s = suggestions[index];
                if (s) {
                    // Hide dropdown immediately and clear state
                    dropdown.classList.remove('active');
                    dropdown.innerHTML = '';
                    selectedIndex = -1;
                    suggestions = [];

                    // Navigate directly to entity page instead of searching
                    if (s.id && s.type) {
                        const entityPath = s.type === 'player' ? 'players' : 'teams';
                        window.location.href = `/ui/${entityPath}/${s.id}`;
                    } else {
                        // Fallback to search if no ID
                        searchInput.value = s.name;
                        doSearch(s.name);
                    }
                }
            }

            function hideDropdown() {
                dropdown.classList.remove('active');
                dropdown.innerHTML = '';  // Clear content to prevent stale items
                selectedIndex = -1;
                suggestions = [];
            }

            searchInput.addEventListener('input', (e) => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    fetchSuggestions(e.target.value.trim());
                }, 200); // 200ms debounce
            });

            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown' && dropdown.classList.contains('active')) {
                    e.preventDefault();
                    selectedIndex = Math.min(selectedIndex + 1, suggestions.length - 1);
                    renderSuggestions();
                } else if (e.key === 'ArrowUp' && dropdown.classList.contains('active')) {
                    e.preventDefault();
                    selectedIndex = Math.max(selectedIndex - 1, -1);
                    renderSuggestions();
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    hideDropdown();  // Always hide dropdown on Enter
                    if (selectedIndex >= 0 && suggestions.length > 0) {
                        selectSuggestion(selectedIndex);
                    } else {
                        doSearch();
                    }
                } else if (e.key === 'Escape') {
                    hideDropdown();
                }
            });

            // Hide dropdown when clicking outside
            document.addEventListener('click', (e) => {
                if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
                    hideDropdown();
                }
            });

            // Also hide on blur (when input loses focus)
            searchInput.addEventListener('blur', (e) => {
                // Delay to allow click on dropdown item to register
                setTimeout(() => {
                    if (!dropdown.contains(document.activeElement)) {
                        hideDropdown();
                    }
                }, 150);
            });

            searchBtn.addEventListener('click', () => { hideDropdown(); doSearch(); });
        </script>
    </body>
    </html>
    """
    return html_content


@app.get("/ui/teams/{team_id}", response_class=HTMLResponse)
def team_dashboard_ui(team_id: int, season: str = Query(default=str(settings.current_season))):
    """Team dashboard page with comprehensive team information."""
    from concurrent.futures import ThreadPoolExecutor
    from app.view_models import TeamDashboardView

    try:
        season_year = parse_season(season)

        # Fetch all data in parallel
        with ThreadPoolExecutor(max_workers=7) as executor:
            team_future = executor.submit(api_client.get_team_by_id, team_id)
            standings_future = executor.submit(api_client.get_standings, season_year)
            fixtures_future = executor.submit(api_client.get_team_fixtures, team_id, season_year)
            squad_future = executor.submit(api_client.get_team_players, team_id, season_year)
            scorers_future = executor.submit(api_client.get_team_top_scorers, team_id, season_year)
            assists_future = executor.submit(api_client.get_team_top_assists, team_id, season_year)
            injuries_future = executor.submit(api_client.get_injuries_by_team, team_id, season_year)

            team = team_future.result()
            standings = standings_future.result()
            fixtures = fixtures_future.result()
            squad = squad_future.result()
            top_scorers = scorers_future.result()
            top_assists = assists_future.result()
            injuries = injuries_future.result()

        if not team:
            return HTMLResponse(
                content="<h1>Team not found</h1><a href='/ui/search'>Back to Search</a>",
                status_code=404
            )

        # Build view model
        view = TeamDashboardView.from_data(
            team_info=team,
            standings_data=standings,
            fixtures_data=fixtures,
            squad_data=squad,
            top_scorers=top_scorers,
            top_assists=top_assists,
            injuries_data=injuries,
        )

        # Build next fixture HTML
        next_fixture_html = ""
        if view.next_fixture:
            nf = view.next_fixture
            opponent = nf.away_team_name if nf.home_team_id == team_id else nf.home_team_name
            opponent_logo = nf.away_team_logo if nf.home_team_id == team_id else nf.home_team_logo
            home_away = "Home" if nf.home_team_id == team_id else "Away"
            next_fixture_html = f"""
            <div class="next-fixture">
                <h3>Next Fixture</h3>
                <a href="/ui/matches/{nf.id}" class="fixture-card">
                    <img src="{opponent_logo}" alt="" class="opponent-logo">
                    <div class="fixture-info">
                        <span class="opponent-name">vs {opponent}</span>
                        <span class="fixture-details">{nf.date_formatted} | {home_away}</span>
                    </div>
                </a>
            </div>
            """
        else:
            next_fixture_html = '<div class="next-fixture"><h3>Next Fixture</h3><p class="no-data">No upcoming fixtures</p></div>'

        # Build last 5 results HTML
        last_5_html = ""
        for match in view.last_5_results:
            is_home = match.home_team_id == team_id
            team_goals = match.home_goals if is_home else match.away_goals
            opp_goals = match.away_goals if is_home else match.home_goals
            opponent = match.away_team_name if is_home else match.home_team_name
            opponent_logo = match.away_team_logo if is_home else match.home_team_logo

            if team_goals is not None and opp_goals is not None:
                if team_goals > opp_goals:
                    result_class = "result-win"
                    result_letter = "W"
                elif team_goals < opp_goals:
                    result_class = "result-loss"
                    result_letter = "L"
                else:
                    result_class = "result-draw"
                    result_letter = "D"
                score = f"{team_goals}-{opp_goals}"
            else:
                result_class = ""
                result_letter = "—"
                score = "—"

            last_5_html += f"""
            <a href="/ui/matches/{match.id}" class="result-card {result_class}">
                <span class="result-score">{score}</span>
                <span class="result-letter">{result_letter}</span>
                <img src="{opponent_logo}" alt="{opponent}" class="result-opponent-logo" title="{opponent}">
            </a>
            """

        if not last_5_html:
            last_5_html = '<p class="no-data">No recent results</p>'

        # Build top scorers HTML
        scorers_html = ""
        for i, p in enumerate(view.top_scorers[:5], 1):
            scorers_html += f"""
            <div class="contributor-row">
                <span class="contributor-rank">{i}.</span>
                <a href="/ui/players/{p['id']}" class="contributor-name">{p['name']}</a>
                <span class="contributor-stat">{p.get('goals', 0)} goals</span>
            </div>
            """
        if not scorers_html:
            scorers_html = '<p class="no-data">No scorers data</p>'

        # Build top assists HTML
        assists_html = ""
        for i, p in enumerate(view.top_assists[:5], 1):
            assists_html += f"""
            <div class="contributor-row">
                <span class="contributor-rank">{i}.</span>
                <a href="/ui/players/{p['id']}" class="contributor-name">{p['name']}</a>
                <span class="contributor-stat">{p.get('assists', 0)} assists</span>
            </div>
            """
        if not assists_html:
            assists_html = '<p class="no-data">No assists data</p>'

        # Build squad by position HTML
        squad_html = ""
        for position, players in view.squad_by_position.items():
            squad_html += f'<div class="position-group"><h4>{position} ({len(players)})</h4>'
            for p in players[:10]:  # Limit to 10 per position
                apps = p.get('appearances', 0)
                goals = p.get('goals', 0)
                assists = p.get('assists', 0)
                stats = f"{apps} apps"
                if goals > 0:
                    stats += f", {goals}G"
                if assists > 0:
                    stats += f", {assists}A"
                squad_html += f"""
                <div class="player-row">
                    <a href="/ui/players/{p['id']}" class="player-name">{p['name']}</a>
                    <span class="player-stats">{stats}</span>
                </div>
                """
            squad_html += '</div>'

        # Form display with colored letters
        form_html = ""
        for letter in view.form:
            if letter == "W":
                form_html += '<span class="form-w">W</span>'
            elif letter == "D":
                form_html += '<span class="form-d">D</span>'
            elif letter == "L":
                form_html += '<span class="form-l">L</span>'

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{view.name} - Football View</title>
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 1000px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .back-link {{ margin-bottom: 20px; }}
                .back-link a {{ color: #3498db; text-decoration: none; }}

                /* Team Header */
                .team-header {{
                    display: flex;
                    align-items: center;
                    gap: 20px;
                    margin-bottom: 25px;
                    padding-bottom: 20px;
                    border-bottom: 2px solid #eee;
                }}
                .team-logo {{ width: 80px; height: 80px; object-fit: contain; }}
                .team-info h1 {{ margin: 0 0 8px 0; color: #2c3e50; }}
                .team-meta {{ color: #666; font-size: 14px; margin: 4px 0; }}
                .team-position {{ font-size: 18px; font-weight: bold; color: #2c3e50; }}
                .team-form {{ margin-top: 8px; }}
                .form-w {{ background: #27ae60; color: white; padding: 2px 6px; margin: 0 2px; border-radius: 3px; font-size: 12px; }}
                .form-d {{ background: #95a5a6; color: white; padding: 2px 6px; margin: 0 2px; border-radius: 3px; font-size: 12px; }}
                .form-l {{ background: #e74c3c; color: white; padding: 2px 6px; margin: 0 2px; border-radius: 3px; font-size: 12px; }}
                .team-stats {{ font-size: 13px; color: #666; margin-top: 5px; }}

                /* Home/Away Splits */
                .home-away-splits {{
                    display: flex;
                    gap: 15px;
                    margin-top: 8px;
                    font-size: 12px;
                }}
                .split {{
                    padding: 4px 10px;
                    border-radius: 4px;
                    cursor: help;
                }}
                .home-split {{
                    background: #e8f5e9;
                    color: #2e7d32;
                }}
                .away-split {{
                    background: #e3f2fd;
                    color: #1565c0;
                }}
                .split-icon {{
                    margin-right: 4px;
                }}

                /* Injury Alert */
                .injury-alert {{
                    margin-top: 8px;
                    padding: 6px 12px;
                    background: #fff3e0;
                    color: #e65100;
                    border-radius: 4px;
                    font-size: 12px;
                    display: inline-block;
                }}
                .injury-icon {{
                    margin-right: 4px;
                }}

                /* Next Fixture */
                .next-fixture {{ margin-bottom: 25px; }}
                .next-fixture h3 {{ margin: 0 0 10px 0; color: #2c3e50; font-size: 16px; }}
                .fixture-card {{
                    display: flex;
                    align-items: center;
                    gap: 15px;
                    padding: 15px;
                    background: #f8f9fa;
                    border-radius: 8px;
                    text-decoration: none;
                    color: inherit;
                    transition: background 0.2s;
                }}
                .fixture-card:hover {{ background: #e9ecef; }}
                .opponent-logo {{ width: 40px; height: 40px; object-fit: contain; }}
                .opponent-name {{ font-weight: bold; color: #2c3e50; display: block; }}
                .fixture-details {{ font-size: 13px; color: #666; }}

                /* Last 5 Results */
                .last-5 {{ margin-bottom: 25px; }}
                .last-5 h3 {{ margin: 0 0 10px 0; color: #2c3e50; font-size: 16px; }}
                .results-strip {{ display: flex; gap: 10px; flex-wrap: wrap; }}
                .result-card {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    padding: 10px 15px;
                    border-radius: 8px;
                    text-decoration: none;
                    min-width: 70px;
                    transition: transform 0.2s;
                }}
                .result-card:hover {{ transform: scale(1.05); }}
                .result-win {{ background: #d4edda; }}
                .result-draw {{ background: #e2e3e5; }}
                .result-loss {{ background: #f8d7da; }}
                .result-score {{ font-weight: bold; color: #2c3e50; font-size: 16px; }}
                .result-letter {{ font-size: 12px; font-weight: bold; margin: 3px 0; }}
                .result-win .result-letter {{ color: #155724; }}
                .result-draw .result-letter {{ color: #383d41; }}
                .result-loss .result-letter {{ color: #721c24; }}
                .result-opponent-logo {{ width: 25px; height: 25px; object-fit: contain; }}

                /* Two Column Layout */
                .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 20px; }}
                @media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

                /* Contributors Section */
                .contributors h3 {{ margin: 0 0 15px 0; color: #2c3e50; font-size: 16px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
                .contributor-section {{ margin-bottom: 20px; }}
                .contributor-section h4 {{ margin: 0 0 10px 0; color: #666; font-size: 14px; }}
                .contributor-row {{
                    display: flex;
                    align-items: center;
                    padding: 8px 0;
                    border-bottom: 1px solid #f0f0f0;
                }}
                .contributor-rank {{ width: 25px; color: #999; font-size: 13px; }}
                .contributor-name {{ flex: 1; color: #3498db; text-decoration: none; }}
                .contributor-name:hover {{ text-decoration: underline; }}
                .contributor-stat {{ color: #666; font-size: 13px; }}

                /* Squad Section */
                .squad h3 {{ margin: 0 0 15px 0; color: #2c3e50; font-size: 16px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
                .position-group {{ margin-bottom: 20px; }}
                .position-group h4 {{ margin: 0 0 10px 0; color: #666; font-size: 13px; text-transform: uppercase; }}
                .player-row {{
                    display: flex;
                    justify-content: space-between;
                    padding: 6px 0;
                    border-bottom: 1px solid #f0f0f0;
                    font-size: 14px;
                }}
                .player-name {{ color: #3498db; text-decoration: none; }}
                .player-name:hover {{ text-decoration: underline; }}
                .player-stats {{ color: #999; font-size: 12px; }}

                .no-data {{ color: #999; font-style: italic; }}
                a {{ color: #3498db; text-decoration: none; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="back-link"><a href="/">← Back to Home</a></div>

                <div class="team-header">
                    <img src="{view.logo}" alt="{view.name}" class="team-logo">
                    <div class="team-info">
                        <h1>{view.name}</h1>
                        <p class="team-meta">{view.venue}{f', {view.city}' if view.city else ''}{f' | Founded: {view.founded}' if view.founded else ''}</p>
                        <p class="team-position">{view.position_suffix} in Premier League | {view.points} pts</p>
                        <div class="team-form">{form_html if form_html else '<span class="no-data">No form data</span>'}</div>
                        <p class="team-stats">P{view.played} W{view.won} D{view.drawn} L{view.lost} | GF:{view.goals_for} GA:{view.goals_against} GD:{view.goal_difference:+d}</p>
                        <div class="home-away-splits">
                            <span class="split home-split" title="Home: {view.home_goals_for} scored, {view.home_goals_against} conceded">
                                <span class="split-icon">🏠</span> {view.home_record_display} ({view.home_ppg} PPG)
                            </span>
                            <span class="split away-split" title="Away: {view.away_goals_for} scored, {view.away_goals_against} conceded">
                                <span class="split-icon">✈️</span> {view.away_record_display} ({view.away_ppg} PPG)
                            </span>
                        </div>
                        {f'<div class="injury-alert"><span class="injury-icon">🏥</span> {view.injury_count} player{"s" if view.injury_count != 1 else ""} injured/unavailable</div>' if view.injury_count > 0 else ''}
                    </div>
                </div>

                {next_fixture_html}

                <div class="last-5">
                    <h3>Last 5 Results</h3>
                    <div class="results-strip">
                        {last_5_html}
                    </div>
                </div>

                <div class="two-col">
                    <div class="contributors">
                        <h3>Top Contributors</h3>
                        <div class="contributor-section">
                            <h4>Goals</h4>
                            {scorers_html}
                        </div>
                        <div class="contributor-section">
                            <h4>Assists</h4>
                            {assists_html}
                        </div>
                    </div>

                    <div class="squad">
                        <h3>Squad</h3>
                        {squad_html if squad_html else '<p class="no-data">No squad data</p>'}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        return html_content

    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<h1>Error loading team: {e}</h1><a href='/'>Back to Home</a>", status_code=500)


@app.get("/ui/players/{player_id}", response_class=HTMLResponse)
def player_detail_ui(player_id: int, season: str = Query(default=None)):
    """Player detail page with comprehensive statistics."""
    try:
        # Determine season
        if season:
            season_year = int(season)
        else:
            season_year = CURRENT_SEASON

        player = api_client.get_player_by_id(player_id, season_year)
        if not player:
            return HTMLResponse(
                content="<h1>Player not found</h1><a href='/ui/search'>Back to Search</a>",
                status_code=404
            )

        # Extract player info
        name = player.get("name", "Unknown")
        photo = player.get("photo", "")
        nationality = player.get("nationality", "")
        age = player.get("age", "")
        height = player.get("height", "")
        weight = player.get("weight", "")

        totals = player.get("season_totals", {})
        pl_stats = player.get("premier_league", {})
        validation = player.get("validation", {})

        # Get Premier League specific stats
        pl_team = pl_stats.get("team", "")
        pl_appearances = pl_stats.get("appearances", 0) or 0
        pl_minutes = pl_stats.get("minutes", 0) or 0
        pl_goals = pl_stats.get("goals", 0) or 0
        pl_assists = pl_stats.get("assists", 0) or 0
        pl_yellows = pl_stats.get("yellow_cards", 0) or 0
        pl_reds = pl_stats.get("red_cards", 0) or 0
        pl_shots = pl_stats.get("shots", 0) or 0
        pl_shots_on = pl_stats.get("shots_on_target", 0) or 0
        pl_key_passes = pl_stats.get("key_passes", 0) or 0
        pl_dribbles_success = pl_stats.get("dribbles_success", 0) or 0
        pl_dribbles_attempts = pl_stats.get("dribbles_attempts", 0) or 0

        # Calculate per 90 stats
        if pl_minutes > 0:
            goals_per_90 = round((pl_goals / pl_minutes) * 90, 2)
            assists_per_90 = round((pl_assists / pl_minutes) * 90, 2)
            ga_per_90 = round(((pl_goals + pl_assists) / pl_minutes) * 90, 2)
        else:
            goals_per_90 = assists_per_90 = ga_per_90 = 0

        # Build competition breakdown with more columns
        comp_rows = ""
        for comp in player.get("competitions", []):
            comp_rows += f"""
            <tr>
                <td>{comp.get('league', 'N/A')}</td>
                <td>{comp.get('team', 'N/A')}</td>
                <td class="stat-cell">{comp.get('appearances', 0)}</td>
                <td class="stat-cell">{comp.get('minutes', 0)}</td>
                <td class="stat-cell goals-cell">{comp.get('goals', 0)}</td>
                <td class="stat-cell">{comp.get('assists', 0)}</td>
                <td class="stat-cell">{comp.get('yellow_cards', 0)}</td>
                <td class="stat-cell">{comp.get('red_cards', 0)}</td>
            </tr>
            """

        # Season totals row
        total_apps = totals.get("appearances", 0) or 0
        total_mins = totals.get("minutes", 0) or 0
        total_goals = totals.get("goals", 0) or 0
        total_assists = totals.get("assists", 0) or 0
        total_yellows = totals.get("yellow_cards", 0) or 0
        total_reds = totals.get("red_cards", 0) or 0

        # Fetch match log (5 recent matches for quick display)
        match_log_data = api_client.get_player_match_log(player_id, season_year, limit=5)
        matches = match_log_data.get("matches", [])

        # Build match log rows
        match_rows = ""
        for match in matches:
            # Format date
            date_str = match.get("date", "N/A")
            if date_str and date_str != "N/A":
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    date_str = dt.strftime("%b %d")
                except:
                    date_str = date_str[:10] if len(date_str) > 10 else date_str

            # Format rating
            rating = match.get("rating")
            rating_display = f"{float(rating):.1f}" if rating else "-"
            rating_class = ""
            if rating:
                try:
                    rating_val = float(rating)
                    if rating_val >= 7.5:
                        rating_class = "rating-high"
                    elif rating_val >= 6.5:
                        rating_class = "rating-mid"
                    else:
                        rating_class = "rating-low"
                except:
                    pass

            # Goals/assists display
            goals = match.get("goals", 0)
            assists = match.get("assists", 0)
            ga_display = []
            if goals > 0:
                ga_display.append(f"{goals}G")
            if assists > 0:
                ga_display.append(f"{assists}A")
            ga_str = " ".join(ga_display) if ga_display else "-"

            # Cards display
            yellow = match.get("yellow_cards", 0)
            red = match.get("red_cards", 0)
            cards_display = []
            if yellow > 0:
                cards_display.append(f"<span class='yellow-card'>{yellow}</span>")
            if red > 0:
                cards_display.append(f"<span class='red-card'>{red}</span>")
            cards_str = " ".join(cards_display) if cards_display else "-"

            match_rows += f"""
            <tr>
                <td>{date_str}</td>
                <td class="match-info">{match.get('home_team', 'N/A')} vs {match.get('away_team', 'N/A')}</td>
                <td>{match.get('score', 'N/A')}</td>
                <td>{match.get('minutes', 0)}'</td>
                <td class="ga-col">{ga_str}</td>
                <td>{cards_str}</td>
                <td class="{rating_class}">{rating_display}</td>
            </tr>
            """

        if not match_rows:
            match_rows = "<tr><td colspan='7' class='no-data'>No match data available</td></tr>"

        # Validation display
        validation_html = ""
        if not validation.get("valid", True):
            mismatches = validation.get("mismatches", [])
            validation_html = f"""
            <div class="validation-warning">
                Data validation: {', '.join(mismatches)}
            </div>
            """

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{name} - Player Stats</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
                .container {{ max-width: 1000px; margin: 0 auto; }}
                .back-link {{ margin-bottom: 20px; }}
                .back-link a {{ color: #3498db; text-decoration: none; }}

                /* Player Header */
                .player-header {{
                    background: white;
                    border-radius: 12px;
                    padding: 24px;
                    display: flex;
                    gap: 24px;
                    align-items: center;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                .player-photo {{
                    width: 120px;
                    height: 120px;
                    border-radius: 50%;
                    object-fit: cover;
                    border: 4px solid #3498db;
                }}
                .player-info h1 {{
                    font-size: 28px;
                    margin-bottom: 8px;
                    color: #2c3e50;
                }}
                .player-meta {{
                    color: #666;
                    font-size: 14px;
                }}
                .player-meta span {{
                    margin-right: 16px;
                }}
                .player-team {{
                    margin-top: 8px;
                    font-size: 16px;
                    color: #3498db;
                }}
                .live-badge {{
                    background: #e74c3c;
                    color: white;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                    margin-left: 8px;
                    vertical-align: middle;
                }}

                /* Key Stats Row */
                .key-stats {{
                    display: grid;
                    grid-template-columns: repeat(4, 1fr);
                    gap: 16px;
                    margin-bottom: 20px;
                }}
                .key-stat {{
                    background: white;
                    border-radius: 12px;
                    padding: 20px;
                    text-align: center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                .key-stat .value {{
                    font-size: 32px;
                    font-weight: bold;
                    color: #2c3e50;
                }}
                .key-stat .label {{
                    font-size: 12px;
                    color: #999;
                    text-transform: uppercase;
                    margin-top: 4px;
                }}
                .key-stat.goals .value {{ color: #27ae60; }}
                .key-stat.assists .value {{ color: #3498db; }}

                /* Per 90 Stats */
                .per90-stats {{
                    background: white;
                    border-radius: 12px;
                    padding: 20px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                .per90-stats h3 {{
                    margin-bottom: 16px;
                    color: #2c3e50;
                }}
                .per90-grid {{
                    display: grid;
                    grid-template-columns: repeat(3, 1fr);
                    gap: 16px;
                }}
                .per90-item {{
                    text-align: center;
                    padding: 12px;
                    background: #f8f9fa;
                    border-radius: 8px;
                }}
                .per90-item .value {{
                    font-size: 24px;
                    font-weight: bold;
                    color: #2c3e50;
                }}
                .per90-item .label {{
                    font-size: 11px;
                    color: #999;
                    text-transform: uppercase;
                }}

                /* Detailed Stats */
                .detailed-stats {{
                    background: white;
                    border-radius: 12px;
                    padding: 20px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                .detailed-stats h3 {{
                    margin-bottom: 16px;
                    color: #2c3e50;
                }}
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 12px;
                }}
                .stat-row {{
                    display: flex;
                    justify-content: space-between;
                    padding: 10px 12px;
                    background: #f8f9fa;
                    border-radius: 6px;
                }}
                .stat-row .label {{ color: #666; }}
                .stat-row .value {{ font-weight: 600; }}

                /* Section Cards */
                .section-card {{
                    background: white;
                    border-radius: 12px;
                    padding: 20px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                .section-card h3 {{
                    margin-bottom: 16px;
                    color: #2c3e50;
                    border-bottom: 2px solid #eee;
                    padding-bottom: 10px;
                }}

                /* Tables */
                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                th, td {{
                    padding: 12px 8px;
                    text-align: left;
                    border-bottom: 1px solid #eee;
                }}
                th {{
                    font-size: 11px;
                    color: #999;
                    text-transform: uppercase;
                    background: #f8f9fa;
                }}
                tr:hover {{ background: #f9f9f9; }}
                .stat-cell {{ text-align: center; }}
                .goals-cell {{ color: #27ae60; font-weight: bold; }}
                tr.totals {{
                    background: #f8f9fa;
                    font-weight: bold;
                }}
                tr.totals td {{
                    border-top: 2px solid #ddd;
                }}

                /* Match Log Styling */
                .match-info {{ font-size: 13px; }}
                .ga-col {{ font-weight: bold; color: #27ae60; }}
                .yellow-card {{
                    background: #f1c40f;
                    color: #333;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-size: 11px;
                }}
                .red-card {{
                    background: #e74c3c;
                    color: white;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-size: 11px;
                }}
                .rating-high {{ color: #27ae60; font-weight: bold; }}
                .rating-mid {{ color: #f39c12; font-weight: bold; }}
                .rating-low {{ color: #e74c3c; font-weight: bold; }}
                .no-data {{ text-align: center; color: #999; font-style: italic; }}

                .validation-warning {{
                    background: #fff3cd;
                    border: 1px solid #ffc107;
                    color: #856404;
                    padding: 10px 15px;
                    border-radius: 4px;
                    margin-bottom: 20px;
                    font-size: 13px;
                }}

                @media (max-width: 600px) {{
                    .player-header {{ flex-direction: column; text-align: center; }}
                    .key-stats {{ grid-template-columns: repeat(2, 1fr); }}
                    .per90-grid {{ grid-template-columns: 1fr; }}
                    .stats-grid {{ grid-template-columns: 1fr; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="back-link"><a href="/ui/top-scorers">← Back to Top Scorers</a></div>

                <div class="player-header">
                    <img src="{photo}" alt="{name}" class="player-photo">
                    <div class="player-info">
                        <h1>{name} <span class="live-badge">LIVE</span></h1>
                        <div class="player-meta">
                            <span>{nationality}</span>
                            <span>Age: {age}</span>
                            {f'<span>{height}</span>' if height else ''}
                            {f'<span>{weight}</span>' if weight else ''}
                        </div>
                        <div class="player-team">{pl_team}</div>
                    </div>
                </div>

                {validation_html}

                <div class="key-stats">
                    <div class="key-stat goals">
                        <div class="value">{pl_goals}</div>
                        <div class="label">Goals (PL)</div>
                    </div>
                    <div class="key-stat assists">
                        <div class="value">{pl_assists}</div>
                        <div class="label">Assists (PL)</div>
                    </div>
                    <div class="key-stat">
                        <div class="value">{pl_appearances}</div>
                        <div class="label">Appearances</div>
                    </div>
                    <div class="key-stat">
                        <div class="value">{pl_minutes}</div>
                        <div class="label">Minutes</div>
                    </div>
                </div>

                <div class="per90-stats">
                    <h3>Per 90 Minutes (Premier League)</h3>
                    <div class="per90-grid">
                        <div class="per90-item">
                            <div class="value">{goals_per_90}</div>
                            <div class="label">Goals / 90</div>
                        </div>
                        <div class="per90-item">
                            <div class="value">{assists_per_90}</div>
                            <div class="label">Assists / 90</div>
                        </div>
                        <div class="per90-item">
                            <div class="value">{ga_per_90}</div>
                            <div class="label">G+A / 90</div>
                        </div>
                    </div>
                </div>

                <div class="detailed-stats">
                    <h3>Detailed Stats (Premier League)</h3>
                    <div class="stats-grid">
                        <div class="stat-row">
                            <span class="label">Shots</span>
                            <span class="value">{pl_shots}</span>
                        </div>
                        <div class="stat-row">
                            <span class="label">Shots on Target</span>
                            <span class="value">{pl_shots_on}</span>
                        </div>
                        <div class="stat-row">
                            <span class="label">Key Passes</span>
                            <span class="value">{pl_key_passes}</span>
                        </div>
                        <div class="stat-row">
                            <span class="label">Dribbles</span>
                            <span class="value">{pl_dribbles_success}/{pl_dribbles_attempts}</span>
                        </div>
                        <div class="stat-row">
                            <span class="label">Yellow Cards</span>
                            <span class="value">{pl_yellows}</span>
                        </div>
                        <div class="stat-row">
                            <span class="label">Red Cards</span>
                            <span class="value">{pl_reds}</span>
                        </div>
                    </div>
                </div>

                <div class="section-card">
                    <h3>Recent Matches (Last 10)</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Match</th>
                                <th>Score</th>
                                <th>Mins</th>
                                <th>G/A</th>
                                <th>Cards</th>
                                <th>Rating</th>
                            </tr>
                        </thead>
                        <tbody>
                            {match_rows}
                        </tbody>
                    </table>
                </div>

                <div class="section-card">
                    <h3>All Competitions {season_year}-{str(season_year + 1)[-2:]}</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Competition</th>
                                <th>Team</th>
                                <th class="stat-cell">Apps</th>
                                <th class="stat-cell">Mins</th>
                                <th class="stat-cell">Goals</th>
                                <th class="stat-cell">Assists</th>
                                <th class="stat-cell">YC</th>
                                <th class="stat-cell">RC</th>
                            </tr>
                        </thead>
                        <tbody>
                            {comp_rows}
                            <tr class="totals">
                                <td colspan="2"><strong>Season Totals</strong></td>
                                <td class="stat-cell">{total_apps}</td>
                                <td class="stat-cell">{total_mins}</td>
                                <td class="stat-cell goals-cell">{total_goals}</td>
                                <td class="stat-cell">{total_assists}</td>
                                <td class="stat-cell">{total_yellows}</td>
                                <td class="stat-cell">{total_reds}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
        """
        return html_content
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


@app.get("/ui/standings", response_class=HTMLResponse)
def standings_ui(season: str = Query(default=str(settings.current_season), description="Season year")):
    """
    Standings UI page - DISABLED.
    Standings are now accessed through the search system for each specific league.
    Use search queries like: "premier league standings", "la liga table", etc.
    """
    # Return a redirect/info page pointing users to search
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Standings - Football View</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 100px auto;
                padding: 20px;
                text-align: center;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            }
            h1 { color: #2c3e50; margin-bottom: 20px; }
            p { color: #666; font-size: 16px; line-height: 1.6; }
            .search-examples {
                background: #f8f9fa;
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                text-align: left;
            }
            .search-examples code {
                background: #e9ecef;
                padding: 4px 8px;
                border-radius: 4px;
                font-family: monospace;
            }
            .search-link {
                display: inline-block;
                margin-top: 20px;
                padding: 12px 24px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                font-weight: bold;
            }
            .search-link:hover { background: #2980b9; }
            .back-link { margin-top: 20px; }
            .back-link a { color: #3498db; text-decoration: none; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏆 League Standings</h1>
            <p>The standalone standings page has been redesigned!</p>
            <p>Standings are now accessed through our <strong>unified search system</strong>,
               allowing you to view any league's table with a simple search.</p>

            <div class="search-examples">
                <p><strong>Try searching for:</strong></p>
                <ul>
                    <li><code>premier league standings</code> - English Premier League</li>
                    <li><code>la liga table</code> - Spanish La Liga</li>
                    <li><code>bundesliga standings</code> - German Bundesliga</li>
                    <li><code>serie a table</code> - Italian Serie A</li>
                    <li><code>ligue 1 standings</code> - French Ligue 1</li>
                </ul>
            </div>

            <a href="/" class="search-link">Go to Search →</a>

            <div class="back-link">
                <a href="/">← Back to Home</a>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(
        content=html_content.replace("__CURRENT_SEASON__", str(settings.current_season))
    )


@app.get("/ui/matches", response_class=HTMLResponse)
def matches_ui(
    season: str = Query(default=str(settings.current_season), description="Season year"),
    date: Optional[str] = Query(default=None, description="Date (YYYY-MM-DD), defaults to today"),
):
    """Matches UI page with date-based navigation."""
    from datetime import timedelta

    try:
        season_year = parse_season(season)

        # Default to today if no date specified
        if date:
            try:
                selected_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                selected_date = datetime.now().date()
        else:
            selected_date = datetime.now().date()

        # Calculate prev/next dates
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)

        # Format dates for display
        today = datetime.now().date()
        if selected_date == today:
            date_display = "Today"
        elif selected_date == today - timedelta(days=1):
            date_display = "Yesterday"
        elif selected_date == today + timedelta(days=1):
            date_display = "Tomorrow"
        else:
            date_display = selected_date.strftime("%A, %B %d")

        full_date_display = selected_date.strftime("%Y-%m-%d")

        # Fetch matches for the selected date from all supported leagues
        date_str = selected_date.strftime("%Y-%m-%d")
        result = api_client.get_matches_multi_league(
            season_year,
            from_date=date_str,
            to_date=date_str,
            limit_per_league=20
        )
        by_competition = result.get("by_competition", {})
        all_matches = result.get("all_matches", [])

        # Build match cards grouped by competition
        cards_html = ""
        total_matches = 0

        # Define competition order (Premier League first, then Champions League, then others)
        competition_order = ["Premier League", "UEFA Champions League", "Champions League"]
        sorted_competitions = sorted(
            by_competition.keys(),
            key=lambda c: (competition_order.index(c) if c in competition_order else 999, c)
        )

        for comp_name in sorted_competitions:
            comp_matches = by_competition[comp_name]
            if not comp_matches:
                continue

            total_matches += len(comp_matches)
            matches = matches_to_view_models(comp_matches)

            # Add competition header
            cards_html += f'<div class="competition-group">'
            cards_html += f'<h3 class="competition-header">{comp_name}</h3>'
            cards_html += '<div class="competition-matches">'

            for match in matches:
                cards_html += match.to_html_card()

            cards_html += '</div></div>'

        if not cards_html:
            cards_html = "<p class='no-data'>No matches on this date</p>"

        # Build navigation URLs
        prev_url = f"/ui/matches?season={season}&date={prev_date.strftime('%Y-%m-%d')}"
        next_url = f"/ui/matches?season={season}&date={next_date.strftime('%Y-%m-%d')}"
        today_url = f"/ui/matches?season={season}"

        # Is today button needed?
        is_today = selected_date == today

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Matches - Football View</title>
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                h1 {{ color: #2c3e50; margin-bottom: 5px; }}
                .live-badge {{
                    background: #e74c3c;
                    color: white;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                }}
                .back-link {{ margin-bottom: 20px; }}
                .back-link a {{ color: #3498db; text-decoration: none; }}

                /* Date Navigation */
                .date-nav {{
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 20px;
                    margin: 20px 0;
                    padding: 15px;
                    background: #f8f9fa;
                    border-radius: 8px;
                }}
                .date-nav > a {{
                    text-decoration: none;
                    color: #3498db;
                    font-size: 24px;
                    padding: 8px 16px;
                    border-radius: 4px;
                    transition: background 0.2s;
                }}
                .date-nav > a:hover {{
                    background: #e8f4fc;
                }}
                .date-display {{
                    text-align: center;
                    min-width: 200px;
                }}
                .date-main {{
                    font-size: 24px;
                    font-weight: bold;
                    color: #2c3e50;
                }}
                .date-sub {{
                    font-size: 14px;
                    color: #666;
                    margin-top: 4px;
                }}
                a.today-btn {{
                    display: inline-block;
                    margin-top: 10px;
                    padding: 6px 16px;
                    background-color: #ffffff !important;
                    color: #2c3e50 !important;
                    border: 2px solid #3498db;
                    border-radius: 4px;
                    text-decoration: none !important;
                    font-size: 13px;
                    font-weight: 500;
                }}
                a.today-btn:hover {{
                    background-color: #3498db !important;
                    color: #ffffff !important;
                }}
                .match-count {{
                    text-align: center;
                    color: #666;
                    margin-bottom: 20px;
                    font-size: 14px;
                }}

                .match-card-link {{
                    display: block;
                    text-decoration: none;
                    color: inherit;
                }}
                .match-card {{
                    border: 1px solid #eee;
                    border-radius: 8px;
                    margin: 15px 0;
                    padding: 15px;
                    background: #fafafa;
                    cursor: pointer;
                    transition: border-color 0.2s, box-shadow 0.2s;
                }}
                .match-card-link:hover .match-card {{
                    border-color: #3498db;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                .match-header {{
                    display: flex;
                    justify-content: space-between;
                    font-size: 12px;
                    color: #666;
                    margin-bottom: 10px;
                }}
                .match-teams {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }}
                .match-team {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    width: 35%;
                    text-align: center;
                }}
                .match-team img {{
                    width: 48px;
                    height: 48px;
                    object-fit: contain;
                    margin-bottom: 8px;
                }}
                .match-team .team-name {{
                    color: #2c3e50;
                    font-weight: 500;
                }}
                .team-winner {{
                    font-weight: bold;
                }}
                .team-winner .team-name {{
                    color: #27ae60;
                }}
                .match-score {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    width: 30%;
                }}
                .score-display {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #2c3e50;
                }}
                .match-status {{
                    font-size: 11px;
                    padding: 3px 8px;
                    border-radius: 4px;
                    margin-top: 5px;
                }}
                .status-finished {{
                    background: #e8f5e9;
                    color: #27ae60;
                }}
                .status-upcoming {{
                    background: #e3f2fd;
                    color: #1976d2;
                }}
                .match-footer {{
                    margin-top: 10px;
                    padding-top: 10px;
                    border-top: 1px solid #eee;
                    font-size: 12px;
                    color: #666;
                    text-align: center;
                    display: flex;
                    justify-content: center;
                    gap: 15px;
                    flex-wrap: wrap;
                }}
                .match-referee {{
                    color: #888;
                }}
                .no-data {{
                    text-align: center;
                    color: #999;
                    font-style: italic;
                    padding: 40px;
                }}

                /* Competition Groups */
                .competition-group {{
                    margin-bottom: 30px;
                }}
                .competition-header {{
                    font-size: 16px;
                    font-weight: 600;
                    color: #2c3e50;
                    margin: 0 0 15px 0;
                    padding: 10px 15px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border-radius: 6px;
                }}
                .competition-matches {{
                    /* matches container */
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="back-link"><a href="/">← Back to Home</a></div>
                <h1>Matches <span class="live-badge">LIVE</span></h1>

                <div class="date-nav">
                    <a href="{prev_url}" title="Previous day">←</a>
                    <div class="date-display">
                        <div class="date-main">{date_display}</div>
                        <div class="date-sub">{full_date_display}</div>
                        {'<a href="' + today_url + '" class="today-btn">Go to Today</a>' if not is_today else ''}
                    </div>
                    <a href="{next_url}" title="Next day">→</a>
                </div>

                <p class="match-count">{total_matches} match{'es' if total_matches != 1 else ''} on this date</p>

                <div class="matches-list">
                    {cards_html}
                </div>
            </div>
        </body>
        </html>
        """
        return html_content
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


@app.get("/ui/top-scorers", response_class=HTMLResponse)
def top_scorers_ui(
    season: str = Query(default=str(settings.current_season), description="Season year"),
    limit: int = Query(default=20, description="Number of players")
):
    """Top scorers UI page with proper table rendering."""
    try:
        season_year = parse_season(season)
        result = api_client.get_top_scorers(season_year, limit=limit)
        players_data = result.get("players", [])

        # Convert to view models
        players = players_to_view_models(players_data)

        # Build table rows
        rows_html = ""
        for i, player in enumerate(players, 1):
            rows_html += f"""
            <tr>
                <td class="rank-cell">{i}</td>
                <td class="player-cell">
                    <img src="{player.photo}" alt="" class="player-mini-photo">
                    <a href="/ui/players/{player.id}">{player.name}</a>
                </td>
                <td><a href="/ui/teams/{player.team_id}">{player.team_name}</a></td>
                <td class="stat-cell goals-cell">{player.goals}</td>
                <td class="stat-cell">{player.assists}</td>
                <td class="stat-cell">{player.appearances}</td>
            </tr>
            """

        if not rows_html:
            rows_html = "<tr><td colspan='6' class='no-data'>No player data available</td></tr>"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Top Scorers - Football View</title>
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                h1 {{ color: #2c3e50; margin-bottom: 5px; }}
                .live-badge {{
                    background: #e74c3c;
                    color: white;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                }}
                .subtitle {{
                    color: #666;
                    margin-bottom: 20px;
                }}
                .back-link {{ margin-bottom: 20px; }}
                .back-link a {{ color: #3498db; text-decoration: none; }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 20px;
                }}
                th, td {{
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #eee;
                }}
                th {{
                    background: #f8f9fa;
                    font-weight: bold;
                    color: #2c3e50;
                    font-size: 12px;
                    text-transform: uppercase;
                }}
                tr:hover {{ background: #f9f9f9; }}
                .rank-cell {{
                    width: 50px;
                    font-weight: bold;
                    color: #666;
                }}
                .player-cell {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}
                .player-mini-photo {{
                    width: 36px;
                    height: 36px;
                    border-radius: 50%;
                    object-fit: cover;
                }}
                .stat-cell {{
                    text-align: center;
                    font-weight: 500;
                }}
                .goals-cell {{
                    font-size: 18px;
                    font-weight: bold;
                    color: #27ae60;
                }}
                a {{ color: #3498db; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
                .no-data {{
                    text-align: center;
                    color: #999;
                    font-style: italic;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="back-link"><a href="/">← Back to Home</a></div>
                <h1>Top Scorers <span class="live-badge">LIVE</span></h1>
                <p class="subtitle">Premier League {season_year}-{str(season_year + 1)[-2:]}</p>

                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Player</th>
                            <th>Team</th>
                            <th style="text-align:center;">Goals</th>
                            <th style="text-align:center;">Assists</th>
                            <th style="text-align:center;">Apps</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </body>
        </html>
        """
        return html_content
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


# ===== MATCH CENTER =====

@app.get("/ui/matches/{match_id}", response_class=HTMLResponse)
def match_center_ui(
    match_id: int,
    forceRefresh: bool = Query(default=False, description="Force refresh data"),
):
    """
    Live Match Center page with events, lineups, and statistics.
    Scoreboard header with tabbed content layout.
    """
    from app.live_match import get_live_match_provider
    from app.view_models import MatchDetailView

    try:
        # Fetch match data via provider
        provider = get_live_match_provider()
        match_data = provider.get_match(match_id, force_refresh=forceRefresh)

        # Convert to view model
        view = MatchDetailView.from_live_match_data(match_data)

        # Build events HTML
        events_html = ""
        if view.has_events:
            for event in sorted(view.events, key=lambda e: (e.minute, e.extra_time or 0)):
                events_html += event.to_timeline_html()
        else:
            events_html = '<p class="no-data">No events recorded</p>'

        # Build lineups HTML (with predicted lineup fallback for upcoming matches)
        lineups_html = ""
        is_predicted_lineup = False
        if view.has_lineups:
            lineups_html = f"""
            <div class="lineups-container">
                {view.home_lineup.to_html()}
                {view.away_lineup.to_html()}
            </div>
            """
        else:
            # Try to get predicted lineups for upcoming matches
            from app.predicted_xi import get_predicted_xi_provider
            from app.view_models import predicted_lineup_to_view
            from concurrent.futures import ThreadPoolExecutor

            predicted_provider = get_predicted_xi_provider()

            # Fetch both predictions in parallel for faster load times
            with ThreadPoolExecutor(max_workers=2) as executor:
                home_future = executor.submit(
                    predicted_provider.get_or_generate_prediction,
                    match_id=view.id,
                    team_id=view.home_team_id,
                )
                away_future = executor.submit(
                    predicted_provider.get_or_generate_prediction,
                    match_id=view.id,
                    team_id=view.away_team_id,
                )
                home_prediction = home_future.result()
                away_prediction = away_future.result()

            if home_prediction or away_prediction:
                is_predicted_lineup = True
                home_lineup_html = ""
                away_lineup_html = ""

                if home_prediction:
                    home_view = predicted_lineup_to_view(
                        home_prediction,
                        team_logo=view.home_team_logo,
                    )
                    home_lineup_html = home_view.to_html()
                else:
                    home_lineup_html = f'<div class="team-lineup"><p class="no-data">{view.home_team_name} lineup unavailable</p></div>'

                if away_prediction:
                    away_view = predicted_lineup_to_view(
                        away_prediction,
                        team_logo=view.away_team_logo,
                    )
                    away_lineup_html = away_view.to_html()
                else:
                    away_lineup_html = f'<div class="team-lineup"><p class="no-data">{view.away_team_name} lineup unavailable</p></div>'

                lineups_html = f"""
                <div class="predicted-lineup-notice">
                    <span class="prediction-icon">🔮</span>
                    <span>Predicted lineups based on historical patterns. Official lineup will appear when announced.</span>
                </div>
                <div class="lineups-container">
                    {home_lineup_html}
                    {away_lineup_html}
                </div>
                """
            else:
                lineups_html = '<p class="no-data">Lineups not available</p>'

        # Build statistics HTML with 3-state model
        stats_html = ""
        if view.has_statistics:
            # READY state: Stats available, show them
            priority_stats = ["Ball Possession", "Total Shots", "Shots on Goal", "Corner Kicks", "Fouls"]
            ordered_stats = []
            other_stats = []
            for stat in view.statistics:
                if stat.stat_type in priority_stats:
                    ordered_stats.append((priority_stats.index(stat.stat_type), stat))
                else:
                    other_stats.append(stat)
            ordered_stats.sort(key=lambda x: x[0])
            all_stats = [s[1] for s in ordered_stats] + other_stats

            for stat in all_stats[:12]:  # Limit to 12 stats
                stats_html += stat.to_stat_bar_html()
        elif view.is_live:
            # WARMING_UP state: Match is live but stats not yet available
            stats_html = '''
            <div class="stats-warming">
                <div class="warming-icon">📊</div>
                <p>Collecting live statistics...</p>
                <p class="warming-hint">Stats typically appear after the first few minutes of play</p>
            </div>
            '''
        else:
            # UNAVAILABLE state: Not live, no stats
            if view.is_finished:
                stats_html = '<p class="no-data">Statistics not available for this match</p>'
            else:
                stats_html = '<p class="no-data">Statistics will be available after kickoff</p>'

        # Adaptive auto-refresh based on match state
        auto_refresh_meta = ""
        refresh_interval = get_refresh_interval(
            status_short=view.status_short,
            elapsed=view.elapsed,
            is_live=view.is_live,
            is_finished=view.is_finished,
            match_date=view.date
        )
        if refresh_interval:
            auto_refresh_meta = f'<meta http-equiv="refresh" content="{refresh_interval}">'

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{view.home_team_name} vs {view.away_team_name} - Match Center</title>
            {auto_refresh_meta}
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f0f2f5;
                }}
                a {{ color: #2c3e50; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
                .container {{
                    background: white;
                    border-radius: 12px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                .back-link {{
                    padding: 15px 20px;
                    border-bottom: 1px solid #eee;
                    font-size: 14px;
                }}
                .back-link a {{ color: #3498db; }}

                /* Scoreboard */
                .match-scoreboard {{
                    background: linear-gradient(135deg, #2c3e50 0%, #1a252f 100%);
                    color: white;
                    padding: 30px 20px;
                    text-align: center;
                }}
                .scoreboard-header {{
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 10px;
                    margin-bottom: 20px;
                    font-size: 14px;
                    opacity: 0.9;
                }}
                .league-logo {{ width: 24px; height: 24px; }}
                .scoreboard-main {{
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 30px;
                }}
                .scoreboard-team {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 10px;
                    min-width: 120px;
                }}
                .team-logo-large {{ width: 80px; height: 80px; }}
                .scoreboard-team .team-name {{
                    font-size: 16px;
                    font-weight: 600;
                    color: white;
                }}
                .scoreboard-score {{
                    text-align: center;
                }}
                .score-main {{
                    font-size: 48px;
                    font-weight: bold;
                    letter-spacing: 8px;
                }}
                .halftime {{
                    font-size: 14px;
                    opacity: 0.8;
                    margin-top: 5px;
                }}
                .status-badge {{
                    display: inline-block;
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 12px;
                    font-weight: 600;
                    margin-top: 10px;
                }}
                .status-live {{
                    background: #e74c3c;
                    animation: pulse 2s infinite;
                }}
                .status-finished {{
                    background: #27ae60;
                }}
                .status-upcoming {{
                    background: #3498db;
                }}
                @keyframes pulse {{
                    0%, 100% {{ opacity: 1; }}
                    50% {{ opacity: 0.7; }}
                }}
                .scoreboard-meta {{
                    margin-top: 20px;
                    font-size: 13px;
                    opacity: 0.8;
                    display: flex;
                    justify-content: center;
                    gap: 20px;
                    flex-wrap: wrap;
                }}

                /* Tabs */
                .tabs {{
                    display: flex;
                    border-bottom: 2px solid #eee;
                }}
                .tab {{
                    flex: 1;
                    padding: 15px;
                    text-align: center;
                    cursor: pointer;
                    font-weight: 500;
                    color: #7f8c8d;
                    border-bottom: 3px solid transparent;
                    margin-bottom: -2px;
                    transition: all 0.2s;
                }}
                .tab:hover {{ color: #2c3e50; }}
                .tab.active {{
                    color: #3498db;
                    border-bottom-color: #3498db;
                }}
                .tab-content {{
                    display: none;
                    padding: 20px;
                }}
                .tab-content.active {{ display: block; }}

                /* Events Timeline */
                .timeline-event {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 12px 15px;
                    border-bottom: 1px solid #f0f0f0;
                }}
                .timeline-event:last-child {{ border-bottom: none; }}
                .event-time {{
                    font-weight: 600;
                    font-size: 14px;
                    min-width: 50px;
                    color: #7f8c8d;
                }}
                .event-icon {{
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 28px;
                    height: 28px;
                    border-radius: 50%;
                    font-size: 12px;
                    font-weight: bold;
                }}
                .event-goal {{
                    background: #27ae60;
                    color: white;
                }}
                .event-own-goal {{
                    background: #e74c3c;
                    color: white;
                }}
                .event-yellow {{
                    background: #f1c40f;
                    width: 18px;
                    height: 24px;
                    border-radius: 3px;
                }}
                .event-red {{
                    background: #e74c3c;
                    width: 18px;
                    height: 24px;
                    border-radius: 3px;
                }}
                .event-sub {{
                    background: #3498db;
                    color: white;
                }}
                .event-player {{ font-size: 14px; }}
                .event-home {{ background: rgba(52, 152, 219, 0.05); }}
                .event-away {{ background: rgba(231, 76, 60, 0.05); }}

                /* Lineups */
                .lineups-container {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 20px;
                }}
                .team-lineup {{
                    border: 1px solid #eee;
                    border-radius: 8px;
                    overflow: hidden;
                }}
                .lineup-header {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 15px;
                    background: #f8f9fa;
                }}
                .lineup-team-logo {{ width: 40px; height: 40px; }}
                .lineup-team-info h4 {{ margin: 0 0 4px 0; }}
                .formation {{ color: #7f8c8d; font-size: 13px; }}
                .starting-xi, .substitutes {{ padding: 15px; }}
                .starting-xi h5, .substitutes h5 {{
                    margin: 0 0 10px 0;
                    font-size: 12px;
                    text-transform: uppercase;
                    color: #7f8c8d;
                }}
                .lineup-player {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 8px 0;
                    border-bottom: 1px solid #f5f5f5;
                    font-size: 14px;
                }}
                .lineup-player:last-child {{ border-bottom: none; }}
                .player-number {{
                    font-weight: 600;
                    color: #7f8c8d;
                    min-width: 25px;
                }}
                .player-position {{
                    margin-left: auto;
                    font-size: 12px;
                    color: #95a5a6;
                }}
                .substitutes {{ border-top: 1px solid #eee; }}
                .coach {{
                    padding: 10px 15px;
                    background: #f8f9fa;
                    font-size: 13px;
                    color: #7f8c8d;
                }}

                /* Predicted Lineups */
                .predicted-lineup-notice {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 12px 16px;
                    margin-bottom: 15px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 8px;
                    color: white;
                    font-size: 13px;
                }}
                .prediction-icon {{
                    font-size: 18px;
                }}
                .predicted-lineup {{
                    border-color: #764ba2 !important;
                    position: relative;
                }}
                .predicted-lineup .lineup-header {{
                    background: linear-gradient(135deg, #f5f3ff 0%, #faf5ff 100%);
                }}
                .prediction-badge {{
                    display: inline-block;
                    padding: 3px 8px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    font-size: 11px;
                    border-radius: 12px;
                    margin-left: 8px;
                }}
                .predicted-lineup .lineup-player {{
                    position: relative;
                }}
                .predicted-lineup .lineup-player::before {{
                    content: '';
                    position: absolute;
                    left: -15px;
                    top: 50%;
                    transform: translateY(-50%);
                    width: 3px;
                    height: 60%;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 2px;
                    opacity: 0.5;
                }}

                /* Statistics */
                .stat-row {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 5px;
                }}
                .stat-value {{
                    font-weight: 600;
                    font-size: 14px;
                    min-width: 45px;
                }}
                .stat-home {{ text-align: right; }}
                .stat-away {{ text-align: left; }}
                .stat-bar-container {{
                    flex: 1;
                    display: flex;
                    height: 8px;
                    background: #ecf0f1;
                    border-radius: 4px;
                    overflow: hidden;
                }}
                .stat-bar {{
                    height: 100%;
                    transition: width 0.3s ease;
                }}
                .stat-bar-home {{ background: #3498db; }}
                .stat-bar-away {{ background: #e74c3c; }}
                .stat-item {{
                    margin-bottom: 18px;
                }}
                .stat-label {{
                    text-align: center;
                    font-size: 12px;
                    color: #7f8c8d;
                    margin-bottom: 6px;
                    text-transform: uppercase;
                    font-weight: 500;
                }}

                .no-data {{
                    text-align: center;
                    color: #95a5a6;
                    padding: 40px 20px;
                }}
                .stats-warming {{
                    text-align: center;
                    padding: 40px 20px;
                    color: #7f8c8d;
                }}
                .stats-warming .warming-icon {{
                    font-size: 32px;
                    margin-bottom: 10px;
                    animation: pulse 2s infinite;
                }}
                .stats-warming p {{
                    margin: 5px 0;
                }}
                .stats-warming .warming-hint {{
                    font-size: 12px;
                    color: #bdc3c7;
                }}
                .refresh-info {{
                    text-align: center;
                    padding: 10px;
                    font-size: 12px;
                    color: #95a5a6;
                    border-top: 1px solid #eee;
                }}

                @media (max-width: 600px) {{
                    .scoreboard-main {{ gap: 15px; }}
                    .team-logo-large {{ width: 50px; height: 50px; }}
                    .score-main {{ font-size: 32px; }}
                    .lineups-container {{ grid-template-columns: 1fr; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="back-link">
                    <a href="/ui/matches?date={view.date[:10] if view.date else ''}">← Back to Matches</a>
                </div>

                {view.to_scoreboard_html()}

                <div class="tabs">
                    <div class="tab active" onclick="showTab('events')">Events</div>
                    <div class="tab" onclick="showTab('lineups')">Lineups</div>
                    <div class="tab" onclick="showTab('stats')">Stats</div>
                </div>

                <div id="events" class="tab-content active">
                    {events_html}
                </div>

                <div id="lineups" class="tab-content">
                    {lineups_html}
                </div>

                <div id="stats" class="tab-content">
                    {stats_html}
                </div>

                <div class="refresh-info">
                    Last updated: {view.last_updated[:19].replace('T', ' ')} UTC
                    {f'| Auto-refreshing every {refresh_interval}s' if refresh_interval else ''}
                    | <a href="?forceRefresh=true">Force Refresh</a>
                </div>
            </div>

            <script>
                function showTab(tabId) {{
                    // Hide all tabs
                    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));

                    // Show selected tab
                    document.getElementById(tabId).classList.add('active');
                    event.target.classList.add('active');
                }}

                // Live clock - updates seconds between API refreshes
                (function() {{
                    const clockEl = document.getElementById('live-clock');
                    if (!clockEl) return;

                    const elapsedMinute = parseInt(clockEl.dataset.elapsed || '0', 10);
                    const startTime = Date.now();

                    function updateClock() {{
                        const secondsSinceLoad = Math.floor((Date.now() - startTime) / 1000);
                        const displaySeconds = secondsSinceLoad % 60;
                        clockEl.textContent = elapsedMinute + ':' + displaySeconds.toString().padStart(2, '0');
                    }}

                    updateClock();
                    setInterval(updateClock, 1000);
                }})();
            </script>
        </body>
        </html>
        """
        return html_content

    except ValueError as e:
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Match Not Found - Football View</title></head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 40px; text-align: center; background: #f0f2f5;">
                <div style="background: white; max-width: 500px; margin: 40px auto; padding: 40px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                    <h1 style="color: #e74c3c; margin-bottom: 20px;">Match Not Found</h1>
                    <p style="color: #7f8c8d; margin-bottom: 30px;">{str(e)}</p>
                    <a href="/ui/matches" style="color: #3498db; text-decoration: none;">← Back to Matches</a>
                </div>
            </body>
            </html>
            """,
            status_code=404
        )
    except Exception as e:
        import logging
        logging.error(f"Match center error for match_id={match_id}: {e}", exc_info=True)
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Error - Football View</title></head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; padding: 40px; text-align: center; background: #f0f2f5;">
                <div style="background: white; max-width: 500px; margin: 40px auto; padding: 40px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                    <h1 style="color: #e74c3c; margin-bottom: 20px;">Something went wrong</h1>
                    <p style="color: #7f8c8d; margin-bottom: 10px;">We couldn't load this match right now.</p>
                    <p style="color: #bdc3c7; font-size: 12px; margin-bottom: 30px;">Error: {type(e).__name__}</p>
                    <div style="display: flex; gap: 20px; justify-content: center;">
                        <a href="?forceRefresh=true" style="color: #3498db; text-decoration: none;">Try Again</a>
                        <a href="/ui/matches" style="color: #3498db; text-decoration: none;">← Back to Matches</a>
                    </div>
                </div>
            </body>
            </html>
            """,
            status_code=500
        )

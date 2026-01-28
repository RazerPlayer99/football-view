"""
Football View (Pre-Alpha) - Main FastAPI Application
All data fetched LIVE from API-Football - no local database
"""
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

from app import api_client
from app.utils.search.pipeline import search as unified_search
from app.utils.search.models.responses import SearchResponse
from app.view_models import (
    TeamView, StandingRowView, MatchCardView, PlayerView,
    standings_to_view_models, matches_to_view_models, players_to_view_models
)
from config.settings import settings

# Version tracking
APP_VERSION = "v0.1.0"
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
    """Convert '2025-26' or '2025' to season year (2025)."""
    if "-" in season_str:
        return int(season_str.split("-")[0])
    return int(season_str)


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


@app.get("/", response_class=HTMLResponse)
def home():
    """Simple welcome page."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Football View</title>
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
                <li><strong><a href="/ui/search">/ui/search</a> - Search Teams & Players</strong></li>
                <li><a href="/ui/standings">/ui/standings</a> - League Standings Table</li>
                <li><a href="/ui/matches">/ui/matches</a> - Match Results</li>
                <li><a href="/ui/top-scorers">/ui/top-scorers</a> - Top Scorers</li>
            </ul>
            <h2>API Endpoints:</h2>
            <ul>
                <li><a href="/health">/health</a> - Health check</li>
                <li><a href="/docs">/docs</a> - Interactive API documentation</li>
                <li><a href="/teams?season=2025">/teams</a> - All Premier League teams (JSON)</li>
                <li><a href="/standings?season=2025">/standings</a> - League standings (JSON)</li>
                <li><a href="/matches?season=2025&limit=10">/matches</a> - Matches (JSON)</li>
                <li><a href="/players/top-scorers?season=2025&limit=20">/players/top-scorers</a> - Top scorers (JSON)</li>
            </ul>
            <p><em>All data fetched live from API-Football</em></p>
        </div>
    </body>
    </html>
    """
    return html_content


# ===== STANDINGS =====

@app.get("/standings")
def get_standings(
    season: str = Query(default="2025", description="Season year (e.g., '2025' for 2025-26)"),
    forceRefresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
):
    """
    Get live Premier League standings.
    Returns scope, season, league_id, standings list, and cache metadata.
    """
    try:
        season_year = parse_season(season)
        result = api_client.get_standings(season_year, force_refresh=forceRefresh)
        if not result or not result.get("standings"):
            raise HTTPException(status_code=404, detail=f"No standings found for season {season}")
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
    season: str = Query(default="2025", description="Season year")
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
    season: str = Query(default="2025", description="Season year")
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
    season: str = Query(default="2025", description="Season year"),
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
    season: str = Query(default="2025", description="Season year"),
    limit: int = Query(default=20, description="Number of top scorers"),
):
    """Get top scorers for a season."""
    try:
        season_year = parse_season(season)
        result = api_client.get_top_scorers(season_year, limit=limit)
        if not result or not result.get("players"):
            raise HTTPException(status_code=404, detail=f"No players found for season {season}")
        result["count"] = len(result.get("players", []))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/players/top-assists")
def get_top_assists(
    season: str = Query(default="2025", description="Season year"),
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
    season: str = Query(default="2025", description="Season year"),
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
    season: str = Query(default="2025", description="Season year"),
    league_id: Optional[int] = Query(None, description="Filter by league ID (39 for Premier League)"),
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
    season: str = Query(default="2025", description="Season year"),
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
def search_ui():
    """Search UI page."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Search - Football View</title>
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: Arial, sans-serif;
                max-width: 900px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 { color: #2c3e50; margin-bottom: 20px; }
            .live-badge {
                background: #e74c3c;
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
            }
            .search-box {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            #search-input {
                flex: 1;
                padding: 12px 16px;
                font-size: 16px;
                border: 2px solid #ddd;
                border-radius: 6px;
                outline: none;
            }
            #search-input:focus { border-color: #3498db; }
            #search-btn {
                padding: 12px 24px;
                background: #3498db;
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
            }
            #search-btn:hover { background: #2980b9; }
            .results-section { margin-top: 20px; }
            .results-section h2 {
                color: #2c3e50;
                border-bottom: 2px solid #eee;
                padding-bottom: 10px;
            }
            .result-item {
                padding: 12px;
                margin: 8px 0;
                background: #f9f9f9;
                border-radius: 4px;
                border-left: 3px solid #3498db;
                display: flex;
                align-items: center;
                gap: 12px;
            }
            .result-item:hover { background: #f0f0f0; }
            .result-item img {
                width: 40px;
                height: 40px;
                object-fit: contain;
            }
            .team-name, .player-name { font-weight: bold; color: #2c3e50; }
            .player-info { color: #666; font-size: 14px; margin-top: 4px; }
            .stats { color: #27ae60; font-weight: bold; }
            .no-results { color: #999; font-style: italic; padding: 20px; }
            .back-link { margin-bottom: 20px; }
            .back-link a { color: #3498db; text-decoration: none; }
            #loading { display: none; color: #666; padding: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="back-link"><a href="/">← Back to Home</a></div>
            <h1>Search Teams & Players <span class="live-badge">LIVE</span></h1>

            <div class="search-box">
                <input type="text" id="search-input" placeholder="Search for a team or player..." autofocus>
                <button id="search-btn">Search</button>
            </div>

            <div id="loading">Fetching live data...</div>
            <div id="results"></div>
        </div>

        <script>
            const searchInput = document.getElementById('search-input');
            const searchBtn = document.getElementById('search-btn');
            const resultsDiv = document.getElementById('results');
            const loadingDiv = document.getElementById('loading');

            async function doSearch() {
                const query = searchInput.value.trim();
                if (query.length < 2) {
                    resultsDiv.innerHTML = '<p class="no-results">Please enter at least 2 characters</p>';
                    return;
                }

                loadingDiv.style.display = 'block';
                resultsDiv.innerHTML = '';

                try {
                    const response = await fetch(`/search?q=${encodeURIComponent(query)}&season=2025`);
                    const data = await response.json();

                    loadingDiv.style.display = 'none';

                    let html = '';

                    // Teams section
                    html += '<div class="results-section">';
                    html += `<h2>Teams (${data.team_count})</h2>`;
                    if (data.teams.length === 0) {
                        html += '<p class="no-results">No teams found</p>';
                    } else {
                        data.teams.forEach(team => {
                            html += `<div class="result-item">
                                <img src="${team.logo || ''}" alt="">
                                <div>
                                    <a href="/ui/teams/${team.id}" class="team-name">${team.name}</a>
                                    <div class="player-info">${team.venue || ''}</div>
                                </div>
                            </div>`;
                        });
                    }
                    html += '</div>';

                    // Players section
                    html += '<div class="results-section">';
                    html += `<h2>Players (${data.player_count})</h2>`;
                    if (data.players.length === 0) {
                        html += '<p class="no-results">No players found</p>';
                    } else {
                        data.players.forEach(player => {
                            html += `<div class="result-item">
                                <img src="${player.photo || ''}" alt="">
                                <div>
                                    <a href="/ui/players/${player.id}" class="player-name">${player.name}</a>
                                    <div class="player-info">
                                        ${player.team?.name || ''} | ${player.position || ''}
                                        <span class="stats">${player.goals} goals, ${player.assists} assists</span>
                                    </div>
                                </div>
                            </div>`;
                        });
                    }
                    html += '</div>';

                    resultsDiv.innerHTML = html;

                } catch (error) {
                    loadingDiv.style.display = 'none';
                    resultsDiv.innerHTML = '<p class="no-results">Error fetching data. Please try again.</p>';
                }
            }

            searchBtn.addEventListener('click', doSearch);
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') doSearch();
            });
        </script>
    </body>
    </html>
    """
    return html_content


@app.get("/ui/teams/{team_id}", response_class=HTMLResponse)
def team_dashboard_ui(team_id: int, season: str = Query(default="2025")):
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
def standings_ui(season: str = Query(default="2025", description="Season year")):
    """Standings UI page with proper table rendering."""
    try:
        season_year = parse_season(season)
        result = api_client.get_standings(season_year)
        standings_data = result.get("standings", [])

        # Convert to view models
        standings = standings_to_view_models(standings_data)

        # Build table rows
        rows_html = ""
        for standing in standings:
            rows_html += standing.to_html_row()

        if not rows_html:
            rows_html = "<tr><td colspan='11' class='no-data'>No standings data available</td></tr>"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Standings - Football View</title>
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 1100px;
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
                    font-size: 14px;
                }}
                th, td {{
                    padding: 10px 8px;
                    text-align: center;
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
                .pos-cell {{
                    font-weight: bold;
                    width: 40px;
                }}
                .team-cell {{
                    text-align: left;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .team-mini-logo {{
                    width: 24px;
                    height: 24px;
                    object-fit: contain;
                }}
                .pts-cell {{
                    font-size: 16px;
                    color: #2c3e50;
                }}
                .gd-cell {{
                    color: #666;
                }}
                .form-cell {{
                    display: flex;
                    gap: 3px;
                    justify-content: center;
                }}
                .form-badge {{
                    width: 20px;
                    height: 20px;
                    border-radius: 3px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 11px;
                    font-weight: bold;
                    color: white;
                }}
                .form-win {{ background: #27ae60; }}
                .form-draw {{ background: #95a5a6; }}
                .form-loss {{ background: #e74c3c; }}
                .pos-ucl {{ background: #e8f5e9; }}
                .pos-uel {{ background: #fff3e0; }}
                .pos-rel {{ background: #ffebee; }}
                a {{ color: #3498db; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
                .legend {{
                    display: flex;
                    gap: 20px;
                    margin-top: 20px;
                    font-size: 12px;
                    color: #666;
                }}
                .legend-item {{
                    display: flex;
                    align-items: center;
                    gap: 5px;
                }}
                .legend-box {{
                    width: 12px;
                    height: 12px;
                    border-radius: 2px;
                }}
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
                <h1>Premier League Standings <span class="live-badge">LIVE</span></h1>
                <p class="subtitle">Season {season_year}-{str(season_year + 1)[-2:]}</p>

                <table>
                    <thead>
                        <tr>
                            <th>Pos</th>
                            <th style="text-align:left;">Team</th>
                            <th>P</th>
                            <th>W</th>
                            <th>D</th>
                            <th>L</th>
                            <th>GF</th>
                            <th>GA</th>
                            <th>GD</th>
                            <th>Pts</th>
                            <th>Form</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>

                <div class="legend">
                    <div class="legend-item">
                        <div class="legend-box" style="background:#e8f5e9;"></div>
                        <span>Champions League</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-box" style="background:#fff3e0;"></div>
                        <span>Europa League</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-box" style="background:#ffebee;"></div>
                        <span>Relegation</span>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        return html_content
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


@app.get("/ui/matches", response_class=HTMLResponse)
def matches_ui(
    season: str = Query(default="2025", description="Season year"),
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
    season: str = Query(default="2025", description="Season year"),
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
    FotMob-style layout with scoreboard header and tabbed content.
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

        # Build statistics HTML
        stats_html = ""
        if view.has_statistics:
            # Order statistics by importance
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
        else:
            stats_html = '<p class="no-data">Statistics not available</p>'

        # Auto-refresh for live matches
        auto_refresh_meta = ""
        if view.is_live:
            auto_refresh_meta = '<meta http-equiv="refresh" content="30">'

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
                .stat-label {{
                    text-align: center;
                    font-size: 12px;
                    color: #7f8c8d;
                    margin-bottom: 15px;
                }}

                .no-data {{
                    text-align: center;
                    color: #95a5a6;
                    padding: 40px 20px;
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
                    {'| Auto-refreshing every 30s' if view.is_live else ''}
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
            </script>
        </body>
        </html>
        """
        return html_content

    except ValueError as e:
        return HTMLResponse(
            content=f"""
            <html><body style="font-family: Arial; padding: 40px; text-align: center;">
                <h1>Match Not Found</h1>
                <p>{str(e)}</p>
                <a href="/ui/matches">← Back to Matches</a>
            </body></html>
            """,
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>Error loading match: {e}</h1>",
            status_code=500
        )

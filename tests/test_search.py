"""
Phase 4.5 Tests: Search endpoint and player data
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_search_endpoint_returns_200():
    """Test that /search returns HTTP 200 for valid query"""
    response = client.get("/search?q=test")
    assert response.status_code == 200


def test_search_endpoint_returns_structure():
    """Test that /search returns correct structure"""
    response = client.get("/search?q=test")
    data = response.json()
    assert "query" in data
    assert "teams" in data
    assert "players" in data
    assert "team_count" in data
    assert "player_count" in data


def test_search_requires_min_length():
    """Test that /search requires minimum 2 characters"""
    response = client.get("/search?q=a")
    assert response.status_code == 422  # Validation error


def test_search_finds_players_by_name():
    """Test that search finds players (requires data in DB)"""
    # Search for a common name pattern
    response = client.get("/search?q=Salah")
    data = response.json()
    # If Salah is in DB, should find at least one player
    if data["player_count"] > 0:
        player = data["players"][0]
        assert "name" in player
        assert "team" in player  # Eager loading works
        assert "id" in player["team"]  # Team has ID
        assert "name" in player["team"]  # Team has name


def test_search_finds_teams_by_name():
    """Test that search finds teams (requires data in DB)"""
    response = client.get("/search?q=Liverpool")
    data = response.json()
    if data["team_count"] > 0:
        team = data["teams"][0]
        assert "name" in team
        assert "id" in team


def test_player_list_endpoint():
    """Test that /players returns list with team info"""
    response = client.get("/players?limit=5")
    assert response.status_code == 200
    data = response.json()
    if len(data) > 0:
        player = data[0]
        assert "team" in player  # Eager loading works
        assert player["team"] is not None


def test_team_detail_ui_returns_html():
    """Test that /ui/teams/{id} returns HTML"""
    # First get a team ID
    response = client.get("/teams?limit=1")
    if response.status_code == 200 and len(response.json()) > 0:
        team_id = response.json()[0]["id"]
        response = client.get(f"/ui/teams/{team_id}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


def test_player_detail_ui_returns_html():
    """Test that /ui/players/{id} returns HTML"""
    # First get a player ID
    response = client.get("/players?limit=1")
    if response.status_code == 200 and len(response.json()) > 0:
        player_id = response.json()[0]["id"]
        response = client.get(f"/ui/players/{player_id}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


def test_team_detail_ui_404_for_invalid_id():
    """Test that /ui/teams/{id} returns 404 for non-existent team"""
    response = client.get("/ui/teams/99999")
    assert response.status_code == 404


def test_player_detail_ui_404_for_invalid_id():
    """Test that /ui/players/{id} returns 404 for non-existent player"""
    response = client.get("/ui/players/99999")
    assert response.status_code == 404

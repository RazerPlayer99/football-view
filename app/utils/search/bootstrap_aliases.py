"""
Bootstrap script to generate aliases.json from API data and curated seed file.

Usage:
    python -m app.utils.search.bootstrap_aliases
    python -m app.utils.search.bootstrap_aliases --with-players
    python -m app.utils.search.bootstrap_aliases --with-players --player-limit 50

This script:
1. Loads the curated seed file (data/aliases_seed.json)
2. Fetches standings from all supported leagues to get team names/IDs
3. Optionally fetches player data for each team (use --with-players)
4. AUTO-GENERATES aliases for all players/teams using AI matching logic
5. Merges API data with curated aliases
6. Writes the final aliases.json

Run periodically (e.g., start of season) to update the alias database.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Set

from config.settings import settings

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


# =============================================================================
# AUTO-ALIAS GENERATION (duplicated from entities.py to avoid circular imports)
# =============================================================================

def normalize_unicode(text: str) -> str:
    """Remove diacritics: Šeško → sesko, Müller → muller"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def generate_person_aliases(full_name: str) -> Set[str]:
    """
    Auto-generate common aliases for a person's name.

    "Nick Woltemade" generates:
        - nick woltemade (full)
        - woltemade (last name)
        - n woltemade (initial + last)
        - n. woltemade (initial with dot)

    "Bruno Fernandes" generates:
        - bruno fernandes
        - fernandes
        - b fernandes / b. fernandes
    """
    name = normalize_unicode(full_name)
    name = re.sub(r"[^a-z\s\-']", "", name)  # Keep letters, spaces, hyphens, apostrophes
    parts = [p for p in name.split() if p]

    if not parts:
        return set()

    aliases = set()
    aliases.add(name)  # Full normalized name

    if len(parts) >= 2:
        first = parts[0]
        last = parts[-1]

        # Last name only (most common search pattern)
        aliases.add(last)

        # Initial + last name (API format: "B. Fernandes")
        aliases.add(f"{first[0]} {last}")
        aliases.add(f"{first[0]}. {last}")

        # First + last (skip middle names)
        if len(parts) > 2:
            aliases.add(f"{first} {last}")

    # Single name (e.g., just "Neymar", "Ronaldinho")
    if len(parts) == 1:
        aliases.add(parts[0])

    return aliases


def generate_team_aliases(team_name: str) -> Set[str]:
    """
    Auto-generate common aliases for a team name.

    "Manchester United" generates:
        - manchester united

    "FC Barcelona" generates:
        - fc barcelona
        - barcelona (without fc/cf/sc prefixes)
    """
    name = normalize_unicode(team_name)
    name = re.sub(r"[^a-z0-9\s\-]", "", name)
    parts = [p for p in name.split() if p]

    if not parts:
        return set()

    aliases = set()
    aliases.add(name)  # Full normalized name

    # Remove common club markers
    club_markers = {"fc", "cf", "sc", "ac", "cd", "afc", "fk", "sk"}
    core = [p for p in parts if p not in club_markers]

    if core and core != parts:
        aliases.add(" ".join(core))

    return aliases


def expand_api_name(api_name: str) -> Set[str]:
    """
    Expand API-style names (initial + last) to searchable forms.

    "N. Woltemade" -> {"n woltemade", "n. woltemade", "woltemade"}
    """
    name = normalize_unicode(api_name)
    parts = name.split()

    if not parts:
        return set()

    aliases = set()
    aliases.add(name.replace(".", "").strip())
    aliases.add(name)

    if len(parts) >= 2:
        first = parts[0].replace(".", "")
        if len(first) <= 2:
            last = parts[-1]
            aliases.add(last)
            aliases.add(f"{first} {last}")
            aliases.add(f"{first}. {last}")

    return aliases


def load_seed_file(seed_path: Path) -> Dict[str, Any]:
    """Load the curated seed file."""
    if not seed_path.exists():
        print(f"Warning: Seed file not found at {seed_path}")
        return {
            "version": "1.0.0",
            "teams": {},
            "players": {},
            "competitions": {},
            "metrics": {},
        }

    with open(seed_path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_teams_from_standings(league_ids: List[int], season: int) -> Dict[str, Dict[str, Any]]:
    """
    Fetch all teams from standings for given leagues and AUTO-GENERATE aliases.

    Returns dict keyed by team_id with name, league_id, and auto-generated aliases.
    """
    from app.api_client import get_standings

    teams = {}

    for league_id in league_ids:
        print(f"  Fetching standings for league {league_id}...")
        try:
            data = get_standings(season, league_id)
            standings = data.get("standings", [])

            for team_row in standings:
                # Handle both flat format (team_id, team_name) and nested format (team.id, team.name)
                team_data = team_row.get("team", {})
                team_id = str(team_data.get("id") or team_row.get("team_id", ""))
                team_name = team_data.get("name") or team_row.get("team_name", "")

                if team_id and team_name:
                    if team_id not in teams:
                        # AUTO-GENERATE aliases using AI matching logic
                        auto_aliases = generate_team_aliases(team_name)

                        teams[team_id] = {
                            "canonical": team_name,
                            "aliases": sorted(list(auto_aliases)),
                            "league_id": league_id,
                        }
                    else:
                        # Team in multiple leagues (e.g., in both PL and UCL)
                        pass  # Keep first league as primary

            print(f"    Found {len(standings)} teams in league {league_id}")

        except Exception as e:
            print(f"    Error fetching league {league_id}: {e}")

    return teams


def fetch_players_for_teams(team_ids: List[str], season: int, limit: int = 50) -> Dict[str, Dict[str, Any]]:
    """
    Fetch players for given teams and AUTO-GENERATE aliases.

    Args:
        team_ids: List of team IDs to fetch players for
        season: Season year
        limit: Max teams to process (to limit API calls)

    Returns:
        Dict keyed by player_id with name, team_id, and auto-generated aliases.
    """
    from app.api_client import get_team_players

    players = {}
    processed = 0

    for team_id in team_ids[:limit]:
        print(f"  Fetching players for team {team_id}...")
        try:
            data = get_team_players(int(team_id), season)
            player_list = data.get("players", [])

            for player in player_list:
                # Handle both formats: (id, name) and (player_id, player_name)
                player_id = str(player.get("id") or player.get("player_id", ""))
                player_name = player.get("name") or player.get("player_name", "")

                if player_id and player_name:
                    # AUTO-GENERATE aliases using AI matching logic
                    auto_aliases = generate_person_aliases(player_name)
                    # Also expand if name looks like API format (N. Name)
                    auto_aliases.update(expand_api_name(player_name))

                    players[player_id] = {
                        "canonical": player_name,
                        "aliases": sorted(list(auto_aliases)),  # Sort for readability
                        "team_id": int(team_id),
                    }

            processed += 1
            print(f"    Found {len(player_list)} players for team {team_id}")

        except Exception as e:
            print(f"    Error fetching players for team {team_id}: {e}")

    print(f"  Processed {processed} teams, found {len(players)} total players")
    return players


def fetch_top_players(league_ids: List[int], season: int) -> Dict[str, Dict[str, Any]]:
    """
    Fetch top scorers and assists to capture star players who may not be
    in the top 20 per-team API response.

    Returns dict keyed by player_id.
    """
    from app.api_client import get_top_scorers, get_top_assists

    players = {}

    for league_id in league_ids:
        # Top scorers
        print(f"  Fetching top scorers for league {league_id}...")
        try:
            data = get_top_scorers(season, league_id, limit=50)
            # API returns 'players' key, not 'top_scorers'
            for player in data.get("players", data.get("top_scorers", [])):
                player_id = str(player.get("id") or player.get("player_id", ""))
                player_name = player.get("name") or player.get("player_name", "")
                # Team can be nested or flat
                team_data = player.get("team", {})
                team_id = team_data.get("id") if isinstance(team_data, dict) else player.get("team_id")

                if player_id and player_name:
                    auto_aliases = generate_person_aliases(player_name)
                    auto_aliases.update(expand_api_name(player_name))

                    players[player_id] = {
                        "canonical": player_name,
                        "aliases": sorted(list(auto_aliases)),
                        "team_id": team_id,
                    }

            print(f"    Found {len(data.get('players', data.get('top_scorers', [])))} top scorers")
        except Exception as e:
            print(f"    Error fetching top scorers: {e}")

        # Top assists
        print(f"  Fetching top assists for league {league_id}...")
        try:
            data = get_top_assists(season, league_id, limit=50)
            # API returns 'players' key, not 'top_assists'
            for player in data.get("players", data.get("top_assists", [])):
                player_id = str(player.get("id") or player.get("player_id", ""))
                player_name = player.get("name") or player.get("player_name", "")
                team_data = player.get("team", {})
                team_id = team_data.get("id") if isinstance(team_data, dict) else player.get("team_id")

                if player_id and player_name and player_id not in players:
                    auto_aliases = generate_person_aliases(player_name)
                    auto_aliases.update(expand_api_name(player_name))

                    players[player_id] = {
                        "canonical": player_name,
                        "aliases": sorted(list(auto_aliases)),
                        "team_id": team_id,
                    }

            print(f"    Found {len(data.get('players', data.get('top_assists', [])))} top assists")
        except Exception as e:
            print(f"    Error fetching top assists: {e}")

    print(f"  Total unique players from top stats: {len(players)}")
    return players


def merge_aliases(
    seed_data: Dict[str, Any],
    api_teams: Dict[str, Dict[str, Any]],
    api_players: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Merge curated seed data with API-fetched data.

    Seed data takes precedence for aliases (curated nicknames).
    API data fills in missing teams/players.
    """
    result = {
        "version": seed_data.get("version", "1.0.0"),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "teams": {},
        "players": {},
        "competitions": seed_data.get("competitions", {}),
        "metrics": seed_data.get("metrics", {}),
    }

    # Merge teams: API data first, then overlay seed data
    for team_id, team_data in api_teams.items():
        result["teams"][team_id] = team_data.copy()

    for team_id, team_data in seed_data.get("teams", {}).items():
        if team_id in result["teams"]:
            # Merge aliases, keeping seed aliases
            existing = result["teams"][team_id]
            existing_aliases = set(existing.get("aliases", []))
            seed_aliases = set(team_data.get("aliases", []))
            existing["aliases"] = list(seed_aliases | existing_aliases)
            existing["canonical"] = team_data.get("canonical", existing["canonical"])
        else:
            result["teams"][team_id] = team_data.copy()

    # Merge players: API data first, then overlay seed data
    for player_id, player_data in api_players.items():
        result["players"][player_id] = player_data.copy()

    for player_id, player_data in seed_data.get("players", {}).items():
        if player_id in result["players"]:
            existing = result["players"][player_id]
            existing_aliases = set(existing.get("aliases", []))
            seed_aliases = set(player_data.get("aliases", []))
            existing["aliases"] = list(seed_aliases | existing_aliases)
            existing["canonical"] = player_data.get("canonical", existing["canonical"])
        else:
            result["players"][player_id] = player_data.copy()

    return result


def main():
    parser = argparse.ArgumentParser(description="Generate aliases.json from API data and seed file")
    parser.add_argument(
        "--season",
        type=int,
        default=settings.current_season,
        help="Season year (default: current season)",
    )
    parser.add_argument(
        "--with-players",
        action="store_true",
        help="Also fetch player data (expensive, many API calls)",
    )
    parser.add_argument(
        "--player-limit",
        type=int,
        default=20,
        help="Max teams to fetch players for (default: 20)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path (default: data/aliases.json)",
    )
    parser.add_argument(
        "--seed",
        type=str,
        default=None,
        help="Seed file path (default: data/aliases_seed.json)",
    )

    args = parser.parse_args()

    # Determine paths
    data_dir = project_root / "data"
    seed_path = Path(args.seed) if args.seed else data_dir / "aliases_seed.json"
    output_path = Path(args.output) if args.output else data_dir / "aliases.json"

    print("=== Alias Database Bootstrap ===")
    print(f"Season: {args.season}")
    print(f"Seed file: {seed_path}")
    print(f"Output file: {output_path}")
    print()

    # Load seed data
    print("1. Loading seed file...")
    seed_data = load_seed_file(seed_path)
    print(f"   Loaded {len(seed_data.get('teams', {}))} teams, {len(seed_data.get('players', {}))} players from seed")
    print()

    # Fetch teams from API
    print("2. Fetching teams from standings...")
    from app.api_client import SUPPORTED_LEAGUES
    league_ids = list(SUPPORTED_LEAGUES.keys())
    api_teams = fetch_teams_from_standings(league_ids, args.season)
    print(f"   Fetched {len(api_teams)} teams from API")
    print()

    # Optionally fetch players
    api_players = {}
    if args.with_players:
        print("3. Fetching team rosters...")
        team_ids = list(api_teams.keys())
        api_players = fetch_players_for_teams(team_ids, args.season, args.player_limit)
        print()

        print("4. Fetching top scorers/assists...")
        top_players = fetch_top_players(league_ids, args.season)
        # Merge - existing team roster data takes precedence
        for pid, pdata in top_players.items():
            if pid not in api_players:
                api_players[pid] = pdata
        print(f"   Total players after merge: {len(api_players)}")
        print()

    # Merge data
    print("5. Merging with seed data...")
    result = merge_aliases(seed_data, api_teams, api_players)
    print(f"   Final: {len(result['teams'])} teams, {len(result['players'])} players")
    print()

    # Write output
    print(f"6. Writing to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("   Done!")
    print()

    # Summary
    print("=== Summary ===")
    print(f"Teams: {len(result['teams'])}")
    print(f"Players: {len(result['players'])}")
    print(f"Competitions: {len(result['competitions'])}")
    print(f"Metrics: {len(result['metrics'])}")


if __name__ == "__main__":
    main()

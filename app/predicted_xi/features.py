"""
Feature extraction for Predicted XI engine.

Extracts normalized features from player and team data for use in prediction scoring.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import Counter

from .models import PlayerFeatures

logger = logging.getLogger("predicted_xi.features")

# How many recent matches to consider
HISTORY_WINDOW = 10


def extract_player_features(
    player_id: int,
    player_name: str,
    player_position: str,
    squad_number: Optional[int],
    historical_lineups: List[Dict[str, Any]],
    match_log: List[Dict[str, Any]],
    target_position: Optional[str] = None,
    days_until_match: Optional[int] = None,
) -> PlayerFeatures:
    """
    Extract features for a single player based on historical data.

    Args:
        player_id: The player's ID
        player_name: The player's name
        player_position: The player's primary/registered position
        squad_number: The player's squad number
        historical_lineups: List of past lineups containing this player's appearances
        match_log: The player's match log with per-game stats
        target_position: The position we're evaluating for (e.g., "D", "M")
        days_until_match: Days until the target match (for rotation calculation)

    Returns:
        PlayerFeatures with all normalized feature values
    """
    features = PlayerFeatures(
        player_id=player_id,
        player_name=player_name,
        primary_position=player_position,
        squad_number=squad_number,
    )

    # Filter to recent window
    recent_lineups = historical_lineups[:HISTORY_WINDOW]
    recent_matches = match_log[:HISTORY_WINDOW]

    if not recent_lineups and not recent_matches:
        logger.debug(f"No historical data for player {player_id}")
        return features

    # Calculate starts
    starts = 0
    total_matches = len(recent_lineups)
    positions_played: Dict[str, int] = Counter()
    consecutive_starts = 0
    last_start_found = False

    for lineup in recent_lineups:
        started = _player_started_in_lineup(player_id, lineup)
        if started:
            starts += 1
            position = _get_player_position_in_lineup(player_id, lineup)
            if position:
                positions_played[position] += 1

            # Track consecutive starts from most recent
            if not last_start_found:
                consecutive_starts += 1
        else:
            last_start_found = True

    # Recent starts feature (0-1)
    features.starts_last_n = starts
    features.total_matches_last_n = total_matches
    features.recent_starts = starts / max(total_matches, 1)
    features.consecutive_starts = consecutive_starts
    features.positions_played = dict(positions_played)

    # Minutes trend from match log
    if recent_matches:
        features.minutes_last_n = sum(m.get("minutes", 0) for m in recent_matches)
        features.minutes_trend = _calculate_minutes_trend(recent_matches)
    else:
        features.minutes_trend = 0.5  # Neutral if no data

    # Position fit
    target_pos = target_position or player_position
    features.position_fit = _calculate_position_fit(
        player_position, positions_played, target_pos
    )

    # Rotation signal (based on recent workload)
    features.rotation_signal = _calculate_rotation_signal(
        recent_matches, consecutive_starts, days_until_match
    )

    # Availability (based on cards, recent appearances)
    features.availability, features.yellow_cards_season = _calculate_availability(
        recent_matches, recent_lineups
    )

    # Days since last match
    if recent_matches:
        last_match_date = recent_matches[0].get("date")
        if last_match_date:
            try:
                last_dt = datetime.fromisoformat(last_match_date.replace("Z", "+00:00"))
                features.days_since_last_match = (datetime.now(last_dt.tzinfo) - last_dt).days
            except (ValueError, TypeError):
                pass

    return features


def _player_started_in_lineup(player_id: int, lineup: Dict[str, Any]) -> bool:
    """Check if player was in the starting XI."""
    starting_xi = lineup.get("starting_xi", [])
    for player in starting_xi:
        if isinstance(player, dict):
            if player.get("id") == player_id:
                return True
        elif isinstance(player, int):
            if player == player_id:
                return True
    return False


def _get_player_position_in_lineup(player_id: int, lineup: Dict[str, Any]) -> Optional[str]:
    """Get the position a player played in a lineup."""
    starting_xi = lineup.get("starting_xi", [])
    for player in starting_xi:
        if isinstance(player, dict) and player.get("id") == player_id:
            return player.get("position", player.get("pos"))
    return None


def _calculate_minutes_trend(match_log: List[Dict[str, Any]]) -> float:
    """
    Calculate minutes trend (0-1).

    1.0 = minutes increasing (good form, playing more)
    0.5 = stable
    0.0 = minutes decreasing (being phased out)
    """
    if len(match_log) < 2:
        return 0.5

    # Split into recent and older
    recent = match_log[:len(match_log) // 2]
    older = match_log[len(match_log) // 2:]

    recent_avg = sum(m.get("minutes", 0) for m in recent) / max(len(recent), 1)
    older_avg = sum(m.get("minutes", 0) for m in older) / max(len(older), 1)

    if older_avg == 0:
        return 1.0 if recent_avg > 0 else 0.5

    ratio = recent_avg / older_avg

    # Normalize to 0-1 (ratio of 2.0 = 1.0, ratio of 0.5 = 0.0)
    normalized = min(1.0, max(0.0, (ratio - 0.5) / 1.5))
    return normalized


def _calculate_position_fit(
    primary_position: str,
    positions_played: Dict[str, int],
    target_position: str,
) -> float:
    """
    Calculate how well player fits target position (0-1).

    1.0 = Primary position matches target
    0.8 = Has played target position frequently
    0.5 = Compatible but not natural fit
    0.2 = Poor fit
    """
    # Normalize positions
    primary = _normalize_position(primary_position)
    target = _normalize_position(target_position)

    if primary == target:
        return 1.0

    # Check if they've played this position
    total_appearances = sum(positions_played.values())
    if total_appearances > 0:
        target_appearances = sum(
            count for pos, count in positions_played.items()
            if _normalize_position(pos) == target
        )
        if target_appearances > 0:
            return 0.6 + (target_appearances / total_appearances) * 0.3

    # Check positional compatibility
    compatibility = _get_position_compatibility(primary, target)
    return compatibility


def _normalize_position(position: str) -> str:
    """Normalize position to G/D/M/F categories."""
    if not position:
        return "M"  # Default

    pos = position.upper().strip()

    # Direct matches
    if pos in ("G", "GK", "GOALKEEPER"):
        return "G"
    if pos in ("D", "DEF", "DEFENDER", "CB", "LB", "RB", "LWB", "RWB"):
        return "D"
    if pos in ("M", "MID", "MIDFIELDER", "CM", "CDM", "CAM", "LM", "RM", "DM", "AM"):
        return "M"
    if pos in ("F", "FWD", "FORWARD", "ST", "CF", "LW", "RW", "SS"):
        return "F"

    # Fallback
    return "M"


def _get_position_compatibility(primary: str, target: str) -> float:
    """Get compatibility score between positions."""
    # Same position
    if primary == target:
        return 1.0

    # Compatible pairs
    compatible_pairs = {
        ("D", "M"): 0.4,  # Defenders can play defensive mid
        ("M", "D"): 0.4,
        ("M", "F"): 0.5,  # Midfielders can play forward
        ("F", "M"): 0.5,
    }

    return compatible_pairs.get((primary, target), 0.2)


def _calculate_rotation_signal(
    match_log: List[Dict[str, Any]],
    consecutive_starts: int,
    days_until_match: Optional[int] = None,
) -> float:
    """
    Calculate rotation likelihood signal (0-1).

    1.0 = Well rested, should start
    0.5 = Normal workload
    0.0 = Needs rest, rotation candidate
    """
    if not match_log:
        return 0.7  # Default to slightly favoring inclusion

    # Calculate total minutes in last 5 matches
    recent_5 = match_log[:5]
    total_minutes = sum(m.get("minutes", 0) for m in recent_5)
    max_possible = 90 * len(recent_5)

    workload = total_minutes / max(max_possible, 1)

    # Heavy workload (>85% of possible minutes) = rotation risk
    if workload > 0.85 and consecutive_starts >= 4:
        score = 0.4  # Rotation likely

    elif workload > 0.7 and consecutive_starts >= 3:
        score = 0.6  # Possible rotation

    elif workload < 0.3:
        score = 0.5  # Not playing much, unclear status

    else:
        score = 0.8  # Normal workload, should start

    # Adjust for days until match (if fixture congestion)
    if days_until_match is not None and days_until_match <= 3:
        # Quick turnaround, rotation more likely for heavy workload players
        if workload > 0.7:
            score *= 0.8

    return score


def _calculate_availability(
    match_log: List[Dict[str, Any]],
    lineups: List[Dict[str, Any]],
) -> Tuple[float, int]:
    """
    Calculate availability score (0-1) and yellow card count.

    1.0 = Fully available
    0.7 = Some risk (accumulating yellows)
    0.3 = High risk (close to suspension)
    0.0 = Likely unavailable
    """
    # Count yellow cards
    yellow_cards = sum(
        m.get("yellow_cards", 0) or m.get("cards", {}).get("yellow", 0)
        for m in match_log
    )

    # Check if player has been in recent squads
    recent_appearances = 0
    for lineup in lineups[:5]:
        if _player_in_squad(match_log[0].get("player_id") if match_log else 0, lineup):
            recent_appearances += 1

    # Base availability
    if recent_appearances == 0 and len(lineups) >= 3:
        # Not in squad recently - possible injury
        availability = 0.3
    else:
        availability = 1.0

    # Yellow card suspension risk (typically 5 yellows = 1 match ban)
    if yellow_cards >= 4:
        availability *= 0.5  # High risk
    elif yellow_cards >= 3:
        availability *= 0.8  # Some risk

    return availability, yellow_cards


def _player_in_squad(player_id: int, lineup: Dict[str, Any]) -> bool:
    """Check if player was in the matchday squad."""
    starting_xi = lineup.get("starting_xi", [])
    substitutes = lineup.get("substitutes", [])

    all_players = starting_xi + substitutes
    for player in all_players:
        if isinstance(player, dict) and player.get("id") == player_id:
            return True
        elif isinstance(player, int) and player == player_id:
            return True
    return False


def extract_formation_patterns(
    historical_lineups: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Extract formation patterns from historical lineups.

    Returns:
        Dictionary with formation counts, primary formation, etc.
    """
    formation_counts: Dict[str, int] = Counter()

    for lineup in historical_lineups:
        formation = lineup.get("formation")
        if formation:
            # Normalize formation string
            formation = formation.strip()
            formation_counts[formation] += 1

    total = sum(formation_counts.values())

    if total == 0:
        return {
            "primary_formation": "4-3-3",  # Default
            "formation_counts": {},
            "total_matches": 0,
            "confidence": 0.0,
        }

    # Find primary formation
    primary = max(formation_counts.items(), key=lambda x: x[1])

    return {
        "primary_formation": primary[0],
        "formation_counts": dict(formation_counts),
        "total_matches": total,
        "confidence": primary[1] / total,
    }


def get_formation_positions(formation: str) -> Dict[str, int]:
    """
    Get the number of positions needed for a formation.

    Args:
        formation: Formation string like "4-3-3", "4-2-3-1"

    Returns:
        Dictionary with position counts: {"G": 1, "D": 4, "M": 3, "F": 3}
    """
    positions = {"G": 1, "D": 0, "M": 0, "F": 0}

    # Parse formation string
    parts = formation.replace("-", " ").split()
    try:
        nums = [int(p) for p in parts if p.isdigit()]
    except ValueError:
        nums = [4, 3, 3]  # Default

    # Standard formations: D-M-F or D-M-M-F
    if len(nums) >= 3:
        positions["D"] = nums[0]
        if len(nums) == 3:
            positions["M"] = nums[1]
            positions["F"] = nums[2]
        elif len(nums) == 4:
            positions["M"] = nums[1] + nums[2]
            positions["F"] = nums[3]
        else:
            # Sum middle sections as midfielders, last as forwards
            positions["M"] = sum(nums[1:-1])
            positions["F"] = nums[-1]

    return positions

"""nflreadpy adapter: the only module that touches nflreadpy/Polars.

Selects just the columns the pipeline uses, so a 48k-row season becomes plain dicts quickly.
Runs on the build host (a CI runner or the owner's Mac), never on the YMP-A1.
"""
from __future__ import annotations

import json
import urllib.request

PBP_COLUMNS = (
    "game_id", "play_id", "home_team", "away_team", "season", "season_type", "week", "posteam", "defteam",
    "qtr", "time", "quarter_seconds_remaining", "game_seconds_remaining", "down", "ydstogo", "yardline_100",
    "desc", "play_type", "yards_gained", "ydsnet", "sp", "touchdown", "td_team", "pass_touchdown",
    "rush_touchdown", "return_touchdown", "field_goal_result", "extra_point_result", "extra_point_attempt",
    "two_point_conv_result", "two_point_attempt", "defensive_two_point_conv", "safety", "total_home_score",
    "total_away_score", "epa", "qb_epa", "wp", "home_wp", "home_wp_post", "wpa", "success", "pass", "rush",
    "special", "sack", "interception", "fumble_lost", "fumbled_1_team", "penalty", "penalty_team",
    "penalty_yards", "first_down", "third_down_converted", "third_down_failed", "fourth_down_converted",
    "fourth_down_failed", "passing_yards", "rushing_yards", "receiving_yards", "passer_player_id",
    "passer_player_name", "rusher_player_id", "rusher_player_name", "receiver_player_id",
    "receiver_player_name", "lateral_receiver_player_id", "lateral_receiver_player_name",
    "lateral_receiving_yards", "lateral_rusher_player_id", "lateral_rusher_player_name", "lateral_rushing_yards",
    "complete_pass", "fixed_drive", "fixed_drive_result", "drive_play_count",
    "drive_time_of_possession", "drive_first_downs", "drive_start_yard_line", "drive_quarter_start",
    "drive_game_clock_start",
)

TIMESTAMP_URL = "https://github.com/nflverse/nflverse-data/releases/download/{tag}/timestamp.json"


def load_schedules() -> list[dict]:
    import nflreadpy as nfl
    return nfl.load_schedules().to_dicts()


def load_teams() -> list[dict]:
    import nflreadpy as nfl
    return nfl.load_teams().to_dicts()


def load_pbp(seasons: list[int]) -> dict[str, list[dict]]:
    """Play-by-play rows grouped by game_id."""
    import nflreadpy as nfl
    frame = nfl.load_pbp(seasons)
    cols = [c for c in PBP_COLUMNS if c in frame.columns]
    missing = sorted(set(PBP_COLUMNS) - set(cols))
    if missing:
        raise RuntimeError(f"nflverse play-by-play lacks columns: {missing}")
    out: dict[str, list[dict]] = {}
    for row in frame.select(cols).iter_rows(named=True):
        out.setdefault(row["game_id"], []).append(row)
    return out


def _by_game(frame) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if "game_id" not in frame.columns:
        raise RuntimeError("nflverse stats release lacks game_id")
    for row in frame.iter_rows(named=True):
        if row.get("game_id"):
            out.setdefault(row["game_id"], []).append(row)
    return out


def load_team_stats(seasons: list[int]) -> dict[str, list[dict]]:
    """nflverse ``stats_team`` (week level), grouped by game_id."""
    import nflreadpy as nfl
    return _by_game(nfl.load_team_stats(seasons))


def load_player_stats(seasons: list[int]) -> dict[str, list[dict]]:
    """nflverse ``stats_player`` (week level), grouped by game_id."""
    import nflreadpy as nfl
    return _by_game(nfl.load_player_stats(seasons))


def release_timestamp(tag: str, timeout: float = 10.0) -> str | None:
    """nflverse publishes ``timestamp.json`` beside each release. None when unreachable."""
    try:
        with urllib.request.urlopen(TIMESTAMP_URL.format(tag=tag), timeout=timeout) as r:
            return json.loads(r.read(4096)).get("last_updated")
    except (OSError, ValueError):
        return None

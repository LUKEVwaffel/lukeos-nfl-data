"""Team hub data for one season: record, splits, game log, trends, season analytics, leaders."""
from __future__ import annotations

from . import metrics
from .game_detail import _player_tables
from .games import for_team, side
from .records import outcome_for, team_record
from .values import mean, text

LEADERS = 3


def game_log(games: list[dict], team: str) -> list[dict]:
    out = []
    for g in sorted(for_team(games, team), key=lambda g: (g["start"] or 0, g["id"])):
        mine, theirs = side(g, team)
        where = "neutral" if g["neutral"] else ("home" if g["home"]["team"] == team else "away")
        o = outcome_for(g, team)
        out.append({"id": g["id"], "week": g["week"], "type": g["type"], "date": g["date"], "start": g["start"],
                    "state": g["state"], "opp": theirs["team"], "where": where, "for": mine["score"],
                    "against": theirs["score"], "result": o.upper() if o else None, "ot": g["overtime"]})
    return out


def _season_leaders(plays: list[dict], team: str) -> dict:
    tables = _player_tables(plays, team)
    return {k: v[:LEADERS] for k, v in tables.items()}


def trends(games: list[dict], plays_by_game: dict, team: str) -> list[dict]:
    out = []
    for g in sorted(for_team(games, team), key=lambda g: (g["start"] or 0, g["id"])):
        plays = plays_by_game.get(g["id"])
        if g["state"] != "final" or not plays:
            continue
        off, de = metrics.offense(plays, team), metrics.defense(plays, team)
        mine, theirs = side(g, team)
        out.append({"id": g["id"], "week": g["week"], "for": mine["score"], "against": theirs["score"],
                    "epa": off["epaPerPlay"], "epaAllowed": de["epaPerPlayAllowed"], "success": off["successRate"]})
    return out


def build(season: int, games: list[dict], plays_by_game: dict, team: str, teams_by_id: dict,
          standings_doc: dict | None) -> dict:
    season_games = [g for g in games if g["season"] == season]
    reg_finals = [g for g in for_team(season_games, team) if g["state"] == "final" and not g["postseason"]]
    reg_plays = [p for g in reg_finals for p in plays_by_game.get(g["id"], [])]
    covered = sum(1 for g in reg_finals if plays_by_game.get(g["id"]))
    rank = None
    for div in (standings_doc or {}).get("divisions") or []:
        for row in div["teams"]:
            if row["team"] == team:
                rank = {"division": div["name"], "rank": row["rank"]}
    upcoming = [g for g in game_log(season_games, team) if g["state"] in ("scheduled", "started")]
    recent = [g for g in game_log(season_games, team) if g["state"] == "final"]
    home_pts = [g["for"] for g in recent if g["where"] == "home" and g["type"] == "REG"]
    away_pts = [g["for"] for g in recent if g["where"] == "away" and g["type"] == "REG"]
    return {
        "team": teams_by_id.get(team),
        "season": season,
        "record": team_record(season_games, team, teams_by_id),
        "standing": rank,
        "next": upcoming[0] if upcoming else None,
        "last": recent[-1] if recent else None,
        "games": game_log(season_games, team),
        "homeAway": {"homePointsPerGame": mean(home_pts, 1), "awayPointsPerGame": mean(away_pts, 1)},
        "analytics": {
            "status": "available" if covered else "pending",
            "gamesCovered": covered, "gamesFinal": len(reg_finals),
            "offense": metrics.offense(reg_plays, team) if reg_plays else None,
            "defense": metrics.defense(reg_plays, team) if reg_plays else None,
            "penalties": metrics.penalties(reg_plays, team) if reg_plays else None,
        },
        "leaders": _season_leaders(reg_plays, team) if reg_plays else None,
        "trends": trends(season_games, plays_by_game, team),
    }


def team_ids_in(games: list[dict]) -> list[str]:
    return sorted({text(g["home"]["team"]) for g in games} | {text(g["away"]["team"]) for g in games})

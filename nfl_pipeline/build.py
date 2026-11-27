"""Assemble every published document from already-loaded rows (pure; no network)."""
from __future__ import annotations

from . import game_detail, history, records, team_season
from .games import normalize_schedule
from .metrics import DEFINITIONS
from .publish import Writer, envelope
from .teams import normalize_teams, team_index


def build_all(writer: Writer, schedule_rows: list[dict], team_rows: list[dict], pbp_by_game: dict,
              seasons: list[int], detail_seasons: set[int], now_ms: int, sources: dict,
              team_stats: dict | None = None, player_stats: dict | None = None) -> dict:
    teams = normalize_teams(team_rows)
    by_id = team_index(teams)
    games = normalize_schedule(schedule_rows, None)  # deterministic: final | scheduled
    writer.write("teams.json", envelope("teams", teams))
    writer.write("definitions.json", envelope("definitions", DEFINITIONS))
    for (a, b), doc in history.all_pairs(games).items():
        writer.write(f"history/h2h/{a}_{b}.json", envelope("head-to-head", doc))
    summary = {}
    for season in seasons:
        season_games = [g for g in games if g["season"] == season]
        if not season_games:
            continue
        detail = season in detail_seasons
        for g in season_games:
            g["analytics"] = "unavailable"
        counts: dict[str, int] = {}
        if detail:
            covered_starts = [g["start"] or 0 for g in season_games if pbp_by_game.get(g["id"])]
            last_covered = max(covered_starts) if covered_starts else None
            for g in season_games:
                if g["state"] != "final":
                    continue
                doc = game_detail.build(g, pbp_by_game.get(g["id"], []), (team_stats or {}).get(g["id"]),
                                        (player_stats or {}).get(g["id"]))
                if doc["analytics"]["status"] == "pending" and last_covered is not None \
                        and (g["start"] or 0) < last_covered:
                    # A later game already has play-by-play, so this gap is not publishing lag.
                    doc["analytics"] = {"status": "unavailable",
                                        "reason": "nflverse has no play-by-play for this game"}
                g["analytics"] = doc["analytics"]["status"]
                if doc["quality"].get("scoreMismatch"):
                    g["analytics"] = "mismatch"
                counts[g["analytics"]] = counts.get(g["analytics"], 0) + 1
                if g["analytics"] != "unavailable":
                    writer.write(f"games/{season}/{g['id']}.json", envelope("game", doc))
        writer.write(f"seasons/{season}/games.json", envelope("season-games", season_games))
        table = records.standings(games, season, teams)
        writer.write(f"seasons/{season}/standings.json", envelope("standings", table))
        plays = {g["id"]: pbp_by_game.get(g["id"], []) for g in season_games} if detail else {}
        for t in teams:
            hub = team_season.build(season, games, plays, t["team"], by_id, table)
            writer.write(f"seasons/{season}/teams/{t['team']}.json", envelope("team-season", hub))
        writer.prune([f"games/{season}/", f"seasons/{season}/"])
        summary[str(season)] = {"games": len(season_games),
                                "final": sum(1 for g in season_games if g["state"] == "final"),
                                "analytics": counts.get("available", 0) + counts.get("mismatch", 0),
                                "mismatch": counts.get("mismatch", 0), "pending": counts.get("pending", 0),
                                "noPlayByPlay": counts.get("unavailable", 0), "detail": detail}
    return summary

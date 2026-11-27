"""Cross-check LukeOS's play-by-play derivations against nflverse's own team and player stats.

nflverse's ``stats_team`` / ``stats_player`` releases are an independent computation of the same
box-score numbers. Any disagreement is reported per game and field; nothing is auto-corrected.
"""
from __future__ import annotations

from . import game_detail
from .teams import franchise

TEAM_FIELDS = {
    # ours (offense dict key) : theirs (stats_team column), with transform
    "passYardsGross": ("passing_yards", None),
    "rushYards": ("rushing_yards", None),
    "sacksTaken": ("sacks_suffered", None),
    "interceptions": ("passing_interceptions", None),
}


def compare_team(doc: dict, team_rows: list[dict]) -> list[str]:
    problems = []
    gid = doc["game"]["id"]
    for row in team_rows:
        team = franchise(row["team"])
        if team not in doc["teams"]:
            problems.append(f"{gid}: {team} not in our document")
            continue
        off, pen = doc["teams"][team]["offense"], doc["teams"][team]["penalties"]
        for ours, (theirs, _) in TEAM_FIELDS.items():
            if row.get(theirs) is not None and off[ours] != int(row[theirs]):
                problems.append(f"{gid} {team} {ours}: ours {off[ours]} nflverse {row[theirs]}")
        if row.get("penalties") is not None and pen["count"] != int(row["penalties"]):
            problems.append(f"{gid} {team} penalties: ours {pen['count']} nflverse {row['penalties']}")
        if row.get("penalty_yards") is not None and pen["yards"] != int(row["penalty_yards"]):
            problems.append(f"{gid} {team} penalty yards: ours {pen['yards']} nflverse {row['penalty_yards']}")
    return problems


def compare_players(doc: dict, player_rows: list[dict]) -> list[str]:
    problems = []
    gid = doc["game"]["id"]
    ours = {}
    for team, tables in doc["players"].items():
        for r in tables["passing"]:
            ours.setdefault(r["id"], {}).update({"completions": r["cmp"], "attempts": r["att"],
                                                 "passing_yards": r["yds"], "passing_tds": r["td"]})
        for r in tables["rushing"]:
            ours.setdefault(r["id"], {}).update({"carries": r["att"], "rushing_yards": r["yds"],
                                                 "rushing_tds": r["td"]})
        for r in tables["receiving"]:
            ours.setdefault(r["id"], {}).update({"receptions": r["rec"], "targets": r["tgt"],
                                                 "receiving_yards": r["yds"], "receiving_tds": r["td"]})
    for row in player_rows:
        mine = ours.get(row["player_id"], {})
        for field, value in mine.items():
            theirs = row.get(field)
            if theirs is not None and int(theirs) != value:
                problems.append(f"{gid} {row.get('player_display_name')} {field}: ours {value} nflverse {theirs}")
    return problems


def season(games: list[dict], pbp_by_game: dict, team_stats: list[dict], player_stats: list[dict]) -> dict:
    by_game_team, by_game_player = {}, {}
    for r in team_stats:
        by_game_team.setdefault(r["game_id"], []).append(r)
    for r in player_stats:
        if r.get("game_id"):
            by_game_player.setdefault(r["game_id"], []).append(r)
    checked, problems, scores = 0, [], []
    for g in games:
        if g["state"] != "final" or not pbp_by_game.get(g["id"]):
            continue
        doc = game_detail.build(g, pbp_by_game[g["id"]])
        checked += 1
        if doc["quality"].get("scoreMismatch"):
            scores.append(f"{g['id']}: pbp {doc['quality']['pbpFinal']} schedule "
                          f"{[g['home']['score'], g['away']['score']]}")
            continue
        total = sum(s["points"] for s in doc["scoring"])
        if total != g["home"]["score"] + g["away"]["score"]:
            scores.append(f"{g['id']}: scoring plays sum {total}")
        problems += compare_team(doc, by_game_team.get(g["id"], []))
        problems += compare_players(doc, by_game_player.get(g["id"], []))
    return {"checked": checked, "scoreProblems": scores, "statProblems": problems}

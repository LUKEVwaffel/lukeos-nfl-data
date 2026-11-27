"""One completed game's postgame breakdown from nflverse play-by-play.

Scores come from the schedule (``games.normalize_game``), which is the source of truth for the
final. Play-by-play supplies everything else and is checked against it: when the score implied
by play-by-play disagrees with the schedule, the line score and scoring summary are withheld and
``quality.scoreMismatch`` is set, rather than showing two different finals.
"""
from __future__ import annotations

from . import metrics
from .values import fmt_clock, flag, integer, num, text

WP_POINTS = 160
KEY_PLAYS = 6


def _order(plays: list[dict]) -> list[dict]:
    return sorted(plays, key=lambda p: (num(p.get("play_id")) or 0))


def _ot_length(game: dict) -> int:
    return 900 if game["postseason"] or (game["season"] or 0) < 2017 else 600


def elapsed(p: dict, game: dict) -> int | None:
    q, left = integer(p.get("qtr")), integer(p.get("quarter_seconds_remaining"))
    if q is None or left is None:
        return None
    if q <= 4:
        return (q - 1) * 900 + (900 - left)
    ot = _ot_length(game)
    return 3600 + (q - 5) * ot + (ot - left)


def _scores(p: dict) -> tuple[int | None, int | None]:
    return integer(p.get("total_home_score")), integer(p.get("total_away_score"))


def line_score(plays: list[dict]) -> tuple[list[int], list[int]]:
    """Points per period (Q1..Q4, then each OT) from the running score."""
    ends: dict[int, tuple[int, int]] = {}
    for p in plays:
        q = integer(p.get("qtr"))
        h, a = _scores(p)
        if q is None or h is None or a is None:
            continue
        prev = ends.get(q, (0, 0))
        ends[q] = (max(prev[0], h), max(prev[1], a))
    periods = max(4, max(ends) if ends else 4)
    home, away, last = [], [], (0, 0)
    for q in range(1, periods + 1):
        cur = ends.get(q, last)
        cur = (max(cur[0], last[0]), max(cur[1], last[1]))
        home.append(cur[0] - last[0])
        away.append(cur[1] - last[1])
        last = cur
    return home, away


def _kind(p: dict) -> str:
    if flag(p.get("touchdown")):
        if flag(p.get("return_touchdown")):
            return "return_td"
        if flag(p.get("pass_touchdown")):
            return "pass_td"
        if flag(p.get("rush_touchdown")):
            return "rush_td"
        return "td"
    if text(p.get("field_goal_result")) == "made":
        return "fg"
    if flag(p.get("safety")):
        return "safety"
    if text(p.get("extra_point_result")) == "good":
        return "pat"
    if text(p.get("two_point_conv_result")) == "success":
        return "two_point"
    if flag(p.get("defensive_two_point_conv")):
        return "defensive_two_point"
    return "other"


def _try_after(plays: list[dict], start: int) -> tuple[str | None, int]:
    """Result of the try after a touchdown at index ``start``: ('good'|'missed'|'2pt good'|...)."""
    for p in plays[start + 1:start + 6]:
        if flag(p.get("extra_point_attempt")):
            r = text(p.get("extra_point_result"))
            return ("PAT good" if r == "good" else "PAT missed"), plays.index(p, start)
        if flag(p.get("two_point_attempt")):
            r = text(p.get("two_point_conv_result"))
            return ("2-pt good" if r == "success" else "2-pt failed"), plays.index(p, start)
        if text(p.get("play_type")) == "kickoff":
            break
    return None, start


def scoring_plays(plays: list[dict], game: dict) -> list[dict]:
    """Every change in the score, with a touchdown and its try merged into one entry."""
    home, away = game["home"]["team"], game["away"]["team"]
    out, last = [], (0, 0)
    merged_until = -1
    for i, p in enumerate(plays):
        h, a = _scores(p)
        # Scores never go down. Timeout and kickoff rows sometimes carry a stale running score,
        # so only a rise above the highest score seen so far is a scoring event.
        if h is None or a is None:
            continue
        h, a = max(h, last[0]), max(a, last[1])
        if (h, a) == last:
            continue
        dh, da = h - last[0], a - last[1]
        team = home if dh > da else away
        if i <= merged_until and out and out[-1]["team"] == team:
            # The try after this touchdown: same scorer, fold it into the touchdown entry.
            last = (h, a)
            out[-1]["score"] = [h, a]
            out[-1]["points"] = (h - out[-1]["_base"][0]) + (a - out[-1]["_base"][1])
            continue
        entry = {"_base": list(last), "qtr": integer(p.get("qtr")), "clock": text(p.get("time")),
                 "elapsed": elapsed(p, game), "team": team, "kind": _kind(p), "points": dh + da,
                 "text": (text(p.get("desc")) or "")[:240], "score": [h, a], "try": None}
        if entry["kind"].endswith("td") or entry["kind"] == "td":
            result, idx = _try_after(plays, i)
            entry["try"] = result
            merged_until = idx
        out.append(entry)
        last = (h, a)
    for e in out:
        e.pop("_base", None)
    return out


def drives(plays: list[dict], game: dict) -> list[dict]:
    rows: dict[float, list[dict]] = {}
    for p in plays:
        d = num(p.get("fixed_drive"))
        if d is not None and text(p.get("posteam")):
            rows.setdefault(d, []).append(p)
    out = []
    for d in sorted(rows):
        first, last = rows[d][0], rows[d][-1]
        out.append({
            "n": int(d), "team": text(first.get("posteam")), "qtr": integer(first.get("drive_quarter_start")),
            "start": text(first.get("drive_start_yard_line")), "clock": text(first.get("drive_game_clock_start")),
            "plays": integer(first.get("drive_play_count")),
            "yards": integer(last.get("ydsnet")),
            "time": text(first.get("drive_time_of_possession")),
            "firstDowns": integer(first.get("drive_first_downs")),
            "result": text(first.get("fixed_drive_result")),
        })
    return out


def _player_tables(plays: list[dict], team: str) -> dict:
    passing, rushing, receiving = {}, {}, {}
    for p in plays:
        if text(p.get("posteam")) != team or flag(p.get("two_point_attempt")):
            continue
        kind = text(p.get("play_type"))
        # Spikes are official incomplete attempts; kneels are official rushes.
        if kind in ("pass", "qb_spike") and not flag(p.get("sack")) and text(p.get("passer_player_id")):
            r = passing.setdefault(text(p.get("passer_player_id")),
                                   {"name": text(p.get("passer_player_name")), "cmp": 0, "att": 0, "yds": 0,
                                    "td": 0, "int": 0, "epa": 0.0})
            r["att"] += 1
            r["cmp"] += 1 if flag(p.get("complete_pass")) else 0
            r["yds"] += integer(p.get("passing_yards")) or 0
            r["td"] += 1 if flag(p.get("pass_touchdown")) else 0
            r["int"] += 1 if flag(p.get("interception")) else 0
            r["epa"] += num(p.get("qb_epa")) or 0.0
            if text(p.get("receiver_player_id")):
                c = receiving.setdefault(text(p.get("receiver_player_id")),
                                         {"name": text(p.get("receiver_player_name")), "rec": 0, "tgt": 0,
                                          "yds": 0, "td": 0})
                c["tgt"] += 1
                if flag(p.get("complete_pass")):
                    c["rec"] += 1
                    c["yds"] += integer(p.get("receiving_yards")) or 0
                    c["td"] += 1 if flag(p.get("pass_touchdown")) else 0
        # Yards after a lateral belong to the player who carried the lateral (nflverse convention:
        # yards only, no extra reception or carry).
        if kind == "pass" and text(p.get("lateral_receiver_player_id")):
            c = receiving.setdefault(text(p.get("lateral_receiver_player_id")),
                                     {"name": text(p.get("lateral_receiver_player_name")), "rec": 0, "tgt": 0,
                                      "yds": 0, "td": 0})
            c["yds"] += integer(p.get("lateral_receiving_yards")) or 0
        if kind in ("run", "qb_kneel") and text(p.get("lateral_rusher_player_id")):
            r = rushing.setdefault(text(p.get("lateral_rusher_player_id")),
                                   {"name": text(p.get("lateral_rusher_player_name")), "att": 0, "yds": 0, "td": 0})
            r["yds"] += integer(p.get("lateral_rushing_yards")) or 0
        if kind in ("run", "qb_kneel") and text(p.get("rusher_player_id")):
            r = rushing.setdefault(text(p.get("rusher_player_id")),
                                   {"name": text(p.get("rusher_player_name")), "att": 0, "yds": 0, "td": 0})
            r["att"] += 1
            r["yds"] += integer(p.get("rushing_yards")) or 0
            r["td"] += 1 if flag(p.get("rush_touchdown")) else 0
    for r in passing.values():
        r["epa"] = round(r["epa"], 1)

    def ranked(table: dict) -> list[dict]:
        return sorted(({"id": k, **v} for k, v in table.items()), key=lambda r: (-r["yds"], r["id"]))
    return {"passing": ranked(passing), "rushing": ranked(rushing), "receiving": ranked(receiving)}


def win_probability(plays: list[dict], game: dict) -> list[list] | None:
    pts = []
    for p in plays:
        wp, t = num(p.get("home_wp")), elapsed(p, game)
        if wp is not None and t is not None:
            pts.append([t, round(wp, 3)])
    if not pts:
        return None
    if len(pts) > WP_POINTS:
        step = len(pts) / (WP_POINTS - 1)
        pts = [pts[int(i * step)] for i in range(WP_POINTS - 1)] + [pts[-1]]
    if game["result"]:
        end = max(pts[-1][0], elapsed(plays[-1], game) or pts[-1][0])
        pts.append([end, {"home": 1.0, "away": 0.0, "tie": 0.5}[game["result"]]])
    return pts


def key_plays(plays: list[dict], game: dict) -> list[dict]:
    scored = []
    for p in plays:
        before, after = num(p.get("home_wp")), num(p.get("home_wp_post"))
        if before is None or after is None:
            continue
        scored.append((abs(after - before), p, after - before))
    scored.sort(key=lambda x: (-x[0], num(x[1].get("play_id")) or 0))
    return [{"qtr": integer(p.get("qtr")), "clock": text(p.get("time")), "team": text(p.get("posteam")),
             "homeWpDelta": round(delta, 3), "text": (text(p.get("desc")) or "")[:240]}
            for _, p, delta in scored[:KEY_PLAYS]]


def factors(plays: list[dict], game: dict) -> list[dict]:
    """Net EPA by phase from the winner's (or home team's, for a tie) point of view."""
    lead = game["home"]["team"] if game["result"] in ("home", "tie", None) else game["away"]["team"]
    phases = metrics.epa_by_phase(plays, lead)
    names = {"passing": "Passing", "rushing": "Rushing", "turnovers": "Turnovers",
             "specialTeams": "Special teams", "other": "Penalties and other"}
    ranked = sorted(phases.items(), key=lambda kv: -abs(kv[1]))
    return [{"phase": k, "label": names[k], "team": lead, "netEpa": v} for k, v in ranked]


BOX_FROM_STATS = {  # our offense key -> nflverse stats_team column
    "passYardsGross": "passing_yards", "rushYards": "rushing_yards", "sacksTaken": "sacks_suffered",
    "interceptions": "passing_interceptions",
}


def apply_team_stats(doc: dict, rows: list[dict]) -> None:
    """Prefer nflverse's published team box score (source priority 1) over LukeOS's derivation.

    Overridden fields are listed in ``doc['boxSource']``; derived values stay for every field
    the release does not carry.
    """
    from .teams import franchise
    used = False
    for row in rows:
        team = franchise(text(row.get("team")))
        if team not in doc["teams"]:
            continue
        off, pen = doc["teams"][team]["offense"], doc["teams"][team]["penalties"]
        for ours, col in BOX_FROM_STATS.items():
            v = integer(row.get(col))
            if v is not None:
                off[ours] = v
                used = True
        sack_lost = integer(row.get("sack_yards_lost"))
        if sack_lost is not None:
            off["sackYards"] = abs(sack_lost)
            off["passYards"] = off["passYardsGross"] - abs(sack_lost)
        off["yards"] = off["passYards"] + off["rushYards"]
        # fumbles_lost_total covers every lost fumble (laterals and returns included); the
        # rushing/receiving/sack columns do not, so their sum would undercount.
        lost = integer(row.get("fumbles_lost_total"))
        if lost is not None:
            off["fumblesLost"] = lost
        off["turnovers"] = off["interceptions"] + off["fumblesLost"]
        for ours, col in (("count", "penalties"), ("yards", "penalty_yards")):
            v = integer(row.get(col))
            if v is not None:
                pen[ours] = v
    if used:
        doc["boxSource"] = "nflverse stats_team"


def apply_player_stats(doc: dict, rows: list[dict]) -> None:
    """Replace derived player tables with nflverse's published per-game player stats."""
    from .teams import franchise
    tables = {t: {"passing": [], "rushing": [], "receiving": []} for t in doc["teams"]}
    for r in rows:
        team = franchise(text(r.get("team")))
        if team not in tables:
            continue
        pid, name = text(r.get("player_id")), text(r.get("player_display_name"))
        if (integer(r.get("attempts")) or 0) > 0:
            tables[team]["passing"].append({"id": pid, "name": name, "cmp": integer(r.get("completions")) or 0,
                                            "att": integer(r.get("attempts")), "yds": integer(r.get("passing_yards")) or 0,
                                            "td": integer(r.get("passing_tds")) or 0,
                                            "int": integer(r.get("passing_interceptions")) or 0,
                                            "epa": round(num(r.get("passing_epa")) or 0.0, 1)})
        if (integer(r.get("carries")) or 0) > 0:
            tables[team]["rushing"].append({"id": pid, "name": name, "att": integer(r.get("carries")),
                                            "yds": integer(r.get("rushing_yards")) or 0,
                                            "td": integer(r.get("rushing_tds")) or 0})
        if (integer(r.get("targets")) or 0) > 0 or (integer(r.get("receptions")) or 0) > 0:
            tables[team]["receiving"].append({"id": pid, "name": name, "rec": integer(r.get("receptions")) or 0,
                                              "tgt": integer(r.get("targets")) or 0,
                                              "yds": integer(r.get("receiving_yards")) or 0,
                                              "td": integer(r.get("receiving_tds")) or 0})
    if any(v for t in tables.values() for v in t.values()):
        for t in tables.values():
            for k in t:
                t[k].sort(key=lambda r: (-r["yds"], r["id"] or ""))
        doc["players"] = tables
        doc["playersSource"] = "nflverse stats_player"


def build(game: dict, plays: list[dict], team_stats: list[dict] | None = None,
          player_stats: list[dict] | None = None) -> dict:
    """The full postgame document for one final game. ``plays`` = that game's pbp rows.

    Source priority: schedule for the final score; nflverse stats_team/stats_player for box
    scores when published; LukeOS derivation from play-by-play otherwise.
    """
    if game["state"] != "final":
        raise ValueError(f"{game['id']} is not final")
    plays = _order([p for p in plays if text(p.get("game_id")) == game["id"]])
    home, away = game["home"]["team"], game["away"]["team"]
    doc = {"game": game, "analytics": {"status": "unavailable"}, "quality": {}}
    if not plays:
        doc["analytics"] = {"status": "pending", "reason": "play-by-play not published yet"}
        return doc
    pbp_home, pbp_away = line_score(plays)
    if (sum(pbp_home), sum(pbp_away)) != (game["home"]["score"], game["away"]["score"]):
        doc["quality"] = {"scoreMismatch": True, "pbpFinal": [sum(pbp_home), sum(pbp_away)]}
        lines, scoring = None, None
    else:
        lines, scoring = {"home": pbp_home, "away": pbp_away}, scoring_plays(plays, game)
    doc["lineScore"] = lines
    doc["scoring"] = scoring
    doc["drives"] = drives(plays, game)
    doc["teams"] = {t: {"offense": metrics.offense(plays, t), "defense": metrics.defense(plays, t),
                        "penalties": metrics.penalties(plays, t)} for t in (home, away)}
    doc["players"] = {t: _player_tables(plays, t) for t in (home, away)}
    doc["boxSource"] = doc["playersSource"] = "LukeOS from play-by-play"
    if team_stats:
        apply_team_stats(doc, team_stats)
    if player_stats:
        apply_player_stats(doc, player_stats)
    doc["winProbability"] = win_probability(plays, game)
    doc["keyPlays"] = key_plays(plays, game)
    doc["factors"] = factors(plays, game)
    doc["analytics"] = {"status": "available", "plays": len(plays)}
    return doc


def leaders(doc: dict) -> dict:
    """Top passer, rusher and receiver per team from a built document."""
    out = {}
    for team, tables in (doc.get("players") or {}).items():
        out[team] = {k: (v[0] if v else None) for k, v in tables.items()}
    return out


def clock_text(seconds: int | None) -> str | None:
    return fmt_clock(seconds)

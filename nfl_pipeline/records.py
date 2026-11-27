"""Team records and standings, derived by LukeOS from final games only.

Rules (tested in tests/test_nfl_pipeline.py):
- Only ``final`` games count. Scheduled, started, unresolved and canceled games never do.
- Regular season and postseason are separate records; ``record`` means regular season.
- Win percentage counts a tie as half a win: (W + T/2) / (W + L + T), the NFL convention.
- Splits: home, away, neutral site (a neutral game is neither home nor away), division (the
  schedule's own div_game flag), conference (from today's teams table, so only for 2002+).
- Before the 2002 realignment no division/conference tables are produced (marked unavailable).
- Streak runs over every final in date order, postseason included; a tie ends a streak.
- Standings order is LukeOS's simplified tiebreak: win pct, head-to-head pct (when both played),
  division pct, conference pct, point differential, then team id. It is labelled approximate;
  official NFL tiebreakers (strength of victory, common games, ...) are not implemented.
"""
from __future__ import annotations

from .games import side
from .teams import conference_of
from .values import ratio

FIRST_SEASON_WITH_CURRENT_DIVISIONS = 2002


def _blank() -> dict:
    return {"w": 0, "l": 0, "t": 0}


def _add(rec: dict, outcome: str) -> None:
    rec[outcome] += 1


def pct(rec: dict) -> float | None:
    games = rec["w"] + rec["l"] + rec["t"]
    return ratio(rec["w"] + rec["t"] / 2, games)


def fmt(rec: dict) -> str:
    return f"{rec['w']}-{rec['l']}" + (f"-{rec['t']}" if rec["t"] else "")


def outcome_for(game: dict, team: str) -> str | None:
    """'w'/'l'/'t' for a final game, else None."""
    if game["state"] != "final":
        return None
    mine, theirs = side(game, team)
    if mine["score"] > theirs["score"]:
        return "w"
    if mine["score"] < theirs["score"]:
        return "l"
    return "t"


def team_record(games: list[dict], team: str, teams_by_id: dict) -> dict:
    """Records for one team over ``games`` (one season)."""
    finals = sorted((g for g in games if g["state"] == "final" and team in (g["home"]["team"], g["away"]["team"])),
                    key=lambda g: (g["start"] or 0, g["id"]))
    reg = {"overall": _blank(), "home": _blank(), "away": _blank(), "neutral": _blank(),
           "division": _blank(), "conference": _blank()}
    post = _blank()
    pf = pa = 0
    pf_post = pa_post = 0
    sequence = []
    my_conf = conference_of(teams_by_id, team)
    for g in finals:
        o = outcome_for(g, team)
        mine, theirs = side(g, team)
        sequence.append(o)
        if g["postseason"]:
            _add(post, o)
            pf_post += mine["score"]
            pa_post += theirs["score"]
            continue
        _add(reg["overall"], o)
        pf += mine["score"]
        pa += theirs["score"]
        where = "neutral" if g["neutral"] else ("home" if g["home"]["team"] == team else "away")
        _add(reg[where], o)
        if g["div"]:
            _add(reg["division"], o)
        # Conference membership comes from today's teams table, valid only since 2002 realignment.
        if my_conf and g["season"] >= FIRST_SEASON_WITH_CURRENT_DIVISIONS \
                and conference_of(teams_by_id, theirs["team"]) == my_conf:
            _add(reg["conference"], o)
    return {
        "team": team,
        "record": fmt(reg["overall"]),
        "pct": pct(reg["overall"]),
        "splits": {k: fmt(v) for k, v in reg.items()},
        "raw": reg,
        "pointsFor": pf, "pointsAgainst": pa, "diff": pf - pa,
        "postseason": {"record": fmt(post), "raw": post, "pointsFor": pf_post, "pointsAgainst": pa_post}
        if sum(post.values()) else None,
        "streak": streak(sequence),
        "last5": "".join(x.upper() for x in sequence[-5:]),
        "gamesPlayed": sum(reg["overall"].values()),
    }


def streak(sequence: list[str]) -> str | None:
    if not sequence:
        return None
    last = sequence[-1]
    n = 0
    for o in reversed(sequence):
        if o != last:
            break
        n += 1
    return f"{last.upper()}{n}"


def _head_to_head(games: list[dict], a: str, b: str) -> float | None:
    rec = _blank()
    for g in games:
        if g["postseason"] or g["state"] != "final":
            continue
        if {g["home"]["team"], g["away"]["team"]} == {a, b}:
            _add(rec, outcome_for(g, a))
    return pct(rec)


def standings(games: list[dict], season: int, teams: list[dict]) -> dict:
    """Division and conference tables for one season's regular season."""
    teams_by_id = {t["team"]: t for t in teams}
    regular = [g for g in games if g["season"] == season and not g["postseason"]]
    records = {t["team"]: team_record(regular, t["team"], teams_by_id) for t in teams}

    def key(team_id: str) -> tuple:
        r = records[team_id]
        return (-(r["pct"] or 0), -(pct(r["raw"]["division"]) or 0), -(pct(r["raw"]["conference"]) or 0),
                -r["diff"], team_id)

    def ordered(ids: list[str]) -> list[str]:
        ids = sorted(ids, key=key)
        # Two-team head-to-head on an exact win-pct tie, applied pairwise for adjacent pairs.
        for i in range(len(ids) - 1):
            a, b = ids[i], ids[i + 1]
            if records[a]["pct"] == records[b]["pct"]:
                h = _head_to_head(regular, a, b)
                if h is not None and h < 0.5:
                    ids[i], ids[i + 1] = b, a
        return ids

    def row(team_id: str, rank: int) -> dict:
        r = records[team_id]
        return {"team": team_id, "rank": rank, "record": r["record"], "pct": r["pct"],
                "division": r["splits"]["division"], "conference": r["splits"]["conference"],
                "pointsFor": r["pointsFor"], "pointsAgainst": r["pointsAgainst"], "diff": r["diff"],
                "streak": r["streak"]}

    divisions = {}
    if season >= FIRST_SEASON_WITH_CURRENT_DIVISIONS:
        for t in teams:
            divisions.setdefault(t["division"], []).append(t["team"])
    conferences = {}
    if season >= FIRST_SEASON_WITH_CURRENT_DIVISIONS:
        for t in teams:
            conferences.setdefault(t["conf"], []).append(t["team"])
    return {
        "season": season,
        "tiebreak": "approximate",
        "divisions": [{"name": name, "teams": [row(x, i + 1) for i, x in enumerate(ordered(ids))]}
                      for name, ids in sorted(divisions.items())] or None,
        "conferences": [{"name": name, "teams": [row(x, i + 1) for i, x in enumerate(ordered(ids))]}
                        for name, ids in sorted(conferences.items())] or None,
        "complete": all(g["state"] == "final" for g in regular) and bool(regular),
    }

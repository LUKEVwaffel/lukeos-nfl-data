"""All-time head-to-head between every pair of current franchises (finals only)."""
from __future__ import annotations

from itertools import combinations

from .records import fmt, outcome_for
from .teams import CURRENT

RECENT = 10


def head_to_head(games: list[dict], a: str, b: str) -> dict:
    """Records from ``a``'s point of view (a < b alphabetically in published files)."""
    meetings = sorted((g for g in games if g["state"] == "final" and {g["home"]["team"], g["away"]["team"]} == {a, b}),
                      key=lambda g: (g["start"] or 0, g["id"]))
    reg, post = {"w": 0, "l": 0, "t": 0}, {"w": 0, "l": 0, "t": 0}
    for g in meetings:
        (post if g["postseason"] else reg)[outcome_for(g, a)] += 1
    recent = [{"id": g["id"], "season": g["season"], "type": g["type"], "date": g["date"],
               "home": g["home"]["team"], "homeScore": g["home"]["score"],
               "away": g["away"]["team"], "awayScore": g["away"]["score"], "ot": g["overtime"]}
              for g in reversed(meetings[-RECENT:])]
    return {"teams": [a, b], "since": meetings[0]["season"] if meetings else None,
            "regular": fmt(reg), "postseason": fmt(post), "meetings": len(meetings), "recent": recent}


def all_pairs(games: list[dict]) -> dict[tuple[str, str], dict]:
    return {(a, b): head_to_head(games, a, b) for a, b in combinations(sorted(CURRENT), 2)}

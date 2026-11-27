"""Schedule rows -> canonical game records with explicit, honest states.

nflverse is not a live source. Its schedule only ever tells us one of:

- ``final``      both scores present (the game is over; corrections may still arrive)
- ``scheduled``  kickoff is in the future
- ``started``    kickoff has passed but no result yet: the UI must defer to the live provider and
                 must not show it as upcoming or as final
- ``unresolved`` kickoff is long past and still no result (postponed/suspended/data gap)

Canceled games are removed from nflverse schedules (e.g. 2022 BUF at CIN), so they never reach
records. A live provider may still report them; see the proxy's reconciliation rules.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .teams import franchise
from .values import integer, text

EASTERN = ZoneInfo("America/New_York")
POSTSEASON = ("WC", "DIV", "CON", "SB")
GAME_TYPES = ("REG",) + POSTSEASON
UNRESOLVED_AFTER_MS = 12 * 3600 * 1000


def kickoff_ms(gameday: str | None, gametime: str | None) -> int | None:
    """nflverse gameday/gametime are US Eastern local time."""
    if not gameday:
        return None
    try:
        day = dt.date.fromisoformat(gameday)
    except ValueError:
        return None
    hh, mm = 13, 0
    if gametime:
        try:
            hh, mm = (int(x) for x in gametime.split(":")[:2])
        except ValueError:
            return None
    local = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=EASTERN)
    return int(local.timestamp() * 1000)


def state_of(home_score, away_score, start_ms, now_ms) -> str:
    """``now_ms=None`` (the published build): only final or scheduled, so a rebuild with the same
    inputs is byte-identical; the proxy applies the clock rules when it serves the game."""
    if home_score is not None and away_score is not None:
        return "final"
    if now_ms is None or start_ms is None or now_ms < start_ms:
        return "scheduled"
    if now_ms - start_ms < UNRESOLVED_AFTER_MS:
        return "started"
    return "unresolved"


def result_of(game: dict) -> str | None:
    if game["state"] != "final":
        return None
    h, a = game["home"]["score"], game["away"]["score"]
    return "home" if h > a else "away" if a > h else "tie"


def normalize_game(row: dict, now_ms: int | None) -> dict:
    gid = text(row.get("game_id"))
    gtype = text(row.get("game_type"))
    if not gid or gtype not in GAME_TYPES:
        raise ValueError(f"bad schedule row {gid!r}")
    home_abbr, away_abbr = text(row.get("home_team")), text(row.get("away_team"))
    if not home_abbr or not away_abbr or franchise(home_abbr) == franchise(away_abbr):
        raise ValueError(f"bad teams in {gid}")
    hs, as_ = integer(row.get("home_score")), integer(row.get("away_score"))
    if (hs is None) != (as_ is None):
        hs = as_ = None  # half a score is not a result
    start = kickoff_ms(text(row.get("gameday")), text(row.get("gametime")))
    state = state_of(hs, as_, start, now_ms)
    game = {
        "id": gid,
        "season": integer(row.get("season")),
        "week": integer(row.get("week")),
        "type": gtype,
        "postseason": gtype in POSTSEASON,
        "date": text(row.get("gameday")),
        "time": text(row.get("gametime")),
        "start": start,
        "state": state,
        "home": {"team": franchise(home_abbr), "abbr": home_abbr, "score": hs if state == "final" else None},
        "away": {"team": franchise(away_abbr), "abbr": away_abbr, "score": as_ if state == "final" else None},
        "neutral": text(row.get("location")) == "Neutral",
        "div": integer(row.get("div_game")) == 1,
        "overtime": state == "final" and integer(row.get("overtime")) == 1,
        "venue": text(row.get("stadium")),
        "roof": text(row.get("roof")),
        "surface": text(row.get("surface")),
        "ids": {k: v for k, v in (("espn", text(row.get("espn"))), ("gsis", text(row.get("gsis"))),
                                  ("pfr", text(row.get("pfr")))) if v},
    }
    game["result"] = result_of(game)
    return game


def normalize_schedule(rows: list[dict], now_ms: int | None) -> list[dict]:
    games, seen = [], set()
    for row in rows:
        g = normalize_game(row, now_ms)
        if g["id"] in seen:
            raise ValueError(f"duplicate game id {g['id']}")
        seen.add(g["id"])
        games.append(g)
    games.sort(key=lambda g: (g["season"], g["start"] or 0, g["id"]))
    return games


def for_team(games: list[dict], team: str) -> list[dict]:
    return [g for g in games if team in (g["home"]["team"], g["away"]["team"])]


def side(game: dict, team: str) -> tuple[dict, dict]:
    """(team's side, opponent's side). Raises when the team did not play."""
    if game["home"]["team"] == team:
        return game["home"], game["away"]
    if game["away"]["team"] == team:
        return game["away"], game["home"]
    raise ValueError(f"{team} not in {game['id']}")

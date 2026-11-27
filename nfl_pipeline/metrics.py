"""Team statistics from nflverse play-by-play, with documented, reproducible definitions.

Every metric carries a ``kind`` so the UI can label it honestly:

- ``derived``  counted or calculated by LukeOS from play-by-play rows (may differ slightly from
               the official gamebook, e.g. on plays nullified by penalty)
- ``model``    aggregates of nflfastR model outputs (EPA, win probability): analytical estimates

``DEFINITIONS`` is published with the data so the app can explain each number.
"""
from __future__ import annotations

from .values import clock_seconds, flag, integer, mean, num, ratio, text

DEFINITIONS = {
    "epaPerPlay": {
        "label": "EPA per play", "kind": "model",
        "formula": "mean(epa) over plays with pass == 1 or rush == 1 and epa present",
        "explain": "Expected Points Added: how much each play changed the points a team could expect "
                   "to score on that drive, from nflfastR's model. Above 0 is good for the offense; "
                   "+0.1 per play is strong, -0.1 is poor.",
    },
    "successRate": {
        "label": "Success rate", "kind": "model",
        "formula": "share of the same plays with epa > 0",
        "explain": "How often a play left the offense better off than before it. Around 45% is "
                   "typical; 50%+ is very good.",
    },
    "explosiveRate": {
        "label": "Explosive play rate", "kind": "derived",
        "formula": "(dropbacks gaining >= 20 yards + designed runs gaining >= 10 yards) / plays",
        "explain": "Share of plays that broke big: passes of 20+ yards or runs of 10+ yards.",
    },
    "yardsPerPlay": {
        "label": "Yards per play", "kind": "derived",
        "formula": "total yards / (rushes + dropbacks), excluding two-point tries",
        "explain": "Average yards on each offensive snap, sacks included.",
    },
    "thirdDown": {
        "label": "Third-down conversions", "kind": "derived",
        "formula": "third_down_converted / (third_down_converted + third_down_failed)",
        "explain": "How often the offense kept the drive alive on third down.",
    },
    "fourthDown": {
        "label": "Fourth-down conversions", "kind": "derived",
        "formula": "fourth_down_converted / (fourth_down_converted + fourth_down_failed)",
        "explain": "Successful fourth-down attempts out of all tries (punts and kicks are not tries).",
    },
    "redZone": {
        "label": "Red-zone touchdowns", "kind": "derived",
        "formula": "drives ending in a touchdown / drives with a snap at or inside the opponent 20",
        "explain": "When a drive reached the opponent's 20, how often it ended in a touchdown.",
    },
    "turnovers": {
        "label": "Turnovers", "kind": "derived",
        "formula": "interceptions thrown + fumbles lost (fumbled_1_team == team and fumble_lost == 1)",
        "explain": "Possessions given away. Each one typically costs about four expected points.",
    },
    "timeOfPossession": {
        "label": "Time of possession", "kind": "derived",
        "formula": "sum of drive_time_of_possession over the team's drives",
        "explain": "How long the team had the ball.",
    },
    "pointsPerDrive": {
        "label": "Points per drive", "kind": "derived",
        "formula": "offensive points (TD 6 + PAT/2pt, FG 3) / drives, excluding end-of-half kneels",
        "explain": "Scoring efficiency per possession.",
    },
    "winProbability": {
        "label": "Win probability", "kind": "model",
        "formula": "nflfastR home_wp before each play; final point is the actual result",
        "explain": "The model's estimate of each team's chance to win at that moment, based on "
                   "score, time, field position, down and distance. It is an estimate, not a fact.",
    },
    "epaFactors": {
        "label": "What decided it", "kind": "model",
        "formula": "net EPA by phase: passing, rushing, turnovers, special teams, other (penalties)",
        "explain": "Splits the game's expected-points margin into phases so you can see which part "
                   "of the game produced the result. Values are in expected points.",
    },
}


def is_scrimmage(p: dict) -> bool:
    """nflfastR convention for EPA/success: a dropback or a designed run with an EPA value."""
    return (flag(p.get("pass")) or flag(p.get("rush"))) and num(p.get("epa")) is not None


def _real_play(p: dict) -> bool:
    return not flag(p.get("two_point_attempt")) and text(p.get("play_type")) in ("pass", "run", "qb_kneel", "qb_spike")


def is_turnover(p: dict) -> bool:
    if flag(p.get("interception")):
        return True
    return flag(p.get("fumble_lost")) and text(p.get("fumbled_1_team")) == text(p.get("posteam"))


def _drive_key(p: dict):
    d = num(p.get("fixed_drive"))
    return None if d is None else (text(p.get("game_id")), d)


def _drives(plays: list[dict], team: str) -> list[dict]:
    """One entry per (game, fixed_drive) the team had, first row wins. Works across a season."""
    seen, out = set(), []
    for p in plays:
        k = _drive_key(p)
        if k is None or text(p.get("posteam")) != team or k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _red_zone(plays: list[dict], team: str) -> tuple[int, int]:
    trips, tds = set(), set()
    for p in plays:
        if text(p.get("posteam")) != team or not is_scrimmage(p):
            continue
        y = num(p.get("yardline_100"))
        d = _drive_key(p)
        if y is not None and y <= 20 and d is not None:
            trips.add(d)
            if text(p.get("fixed_drive_result")) == "Touchdown":
                tds.add(d)
    return len(trips), len(tds)


def offense(plays: list[dict], team: str) -> dict:
    """Offensive box score and efficiency for ``team`` (rows where it had the ball)."""
    own = [p for p in plays if text(p.get("posteam")) == team]
    scrim = [p for p in own if is_scrimmage(p)]
    real = [p for p in own if _real_play(p)]
    rushes = [p for p in real if text(p.get("play_type")) in ("run", "qb_kneel")]
    dropbacks = [p for p in real if text(p.get("play_type")) in ("pass", "qb_spike")]
    sacks = [p for p in dropbacks if flag(p.get("sack"))]
    rush_yds = sum(integer(p.get("rushing_yards")) or 0 for p in rushes)
    gross_pass = sum(integer(p.get("passing_yards")) or 0 for p in dropbacks)
    sack_yds = sum(integer(p.get("yards_gained")) or 0 for p in sacks)
    net_pass = gross_pass + sack_yds
    explosive = sum(1 for p in scrim if (flag(p.get("pass")) and (num(p.get("yards_gained")) or 0) >= 20)
                    or (flag(p.get("rush")) and (num(p.get("yards_gained")) or 0) >= 10))
    t3c = sum(1 for p in own if flag(p.get("third_down_converted")))
    t3f = sum(1 for p in own if flag(p.get("third_down_failed")))
    t4c = sum(1 for p in own if flag(p.get("fourth_down_converted")))
    t4f = sum(1 for p in own if flag(p.get("fourth_down_failed")))
    rz_trips, rz_tds = _red_zone(plays, team)
    drives = _drives(plays, team)
    top = sum(clock_seconds(d.get("drive_time_of_possession")) or 0 for d in drives)
    n_plays = len(rushes) + len(dropbacks)
    epas = [num(p.get("epa")) for p in scrim]
    return {
        "plays": n_plays,
        "yards": rush_yds + net_pass,
        "rushYards": rush_yds, "rushes": len(rushes),
        "passYards": net_pass, "passYardsGross": gross_pass,
        "dropbacks": len(dropbacks), "sacksTaken": len(sacks), "sackYards": -sack_yds,
        "firstDowns": sum(1 for p in own if flag(p.get("first_down"))),
        "thirdDown": [t3c, t3c + t3f], "fourthDown": [t4c, t4c + t4f],
        "redZone": [rz_tds, rz_trips],
        "turnovers": sum(1 for p in own if is_turnover(p)),
        "interceptions": sum(1 for p in own if flag(p.get("interception"))),
        "fumblesLost": sum(1 for p in own if flag(p.get("fumble_lost")) and text(p.get("fumbled_1_team")) == team),
        "explosive": explosive,
        "explosiveRate": ratio(explosive, len(scrim)),
        "yardsPerPlay": ratio(rush_yds + net_pass, n_plays, 2),
        "epaPerPlay": mean(epas),
        "passEpaPerPlay": mean(num(p.get("epa")) for p in scrim if flag(p.get("pass"))),
        "rushEpaPerPlay": mean(num(p.get("epa")) for p in scrim if flag(p.get("rush"))),
        "successRate": ratio(sum(1 for e in epas if e > 0), len(epas)),
        "drives": len(drives),
        "timeOfPossession": top,
    }


def penalties(plays: list[dict], team: str) -> dict:
    flagged = [p for p in plays if flag(p.get("penalty")) and text(p.get("penalty_team")) == team]
    return {"count": len(flagged), "yards": sum(integer(p.get("penalty_yards")) or 0 for p in flagged)}


def defense(plays: list[dict], team: str) -> dict:
    """What the defense allowed and took away (rows where ``team`` was defteam)."""
    opp = [p for p in plays if text(p.get("defteam")) == team]
    scrim = [p for p in opp if is_scrimmage(p)]
    epas = [num(p.get("epa")) for p in scrim]
    return {
        "epaPerPlayAllowed": mean(epas),
        "successRateAllowed": ratio(sum(1 for e in epas if e > 0), len(epas)),
        "sacks": sum(1 for p in opp if flag(p.get("sack")) and _real_play(p)),
        "takeaways": sum(1 for p in opp if is_turnover(p)),
    }


PHASES = ("passing", "rushing", "turnovers", "specialTeams", "other")


def phase_of(p: dict) -> str:
    if is_turnover(p):
        return "turnovers"
    if flag(p.get("special")):
        return "specialTeams"
    if flag(p.get("pass")):
        return "passing"
    if flag(p.get("rush")):
        return "rushing"
    return "other"


def epa_by_phase(plays: list[dict], team: str) -> dict:
    """Net EPA for ``team`` per phase: its own EPA as posteam minus the opponent's."""
    out = {k: 0.0 for k in PHASES}
    for p in plays:
        e = num(p.get("epa"))
        pos = text(p.get("posteam"))
        if e is None or pos is None:
            continue
        out[phase_of(p)] += e if pos == team else -e
    return {k: round(v, 2) for k, v in out.items()}

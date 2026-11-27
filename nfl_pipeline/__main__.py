"""CLI: ``python -m nfl_pipeline build|poc``. Needs nflreadpy (see nfl-pipeline/requirements.txt)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import game_detail, loader, logos
from .publish import envelope
from .build import build_all
from .games import normalize_schedule
from .publish import Writer


def _seasons(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def _sources() -> dict:
    return {"nflverse": {"schedules": loader.release_timestamp("schedules"),
                         "pbp": loader.release_timestamp("pbp"), "teams": loader.release_timestamp("teams")}}


def cmd_build(args) -> int:
    now = int(time.time() * 1000)
    seasons = _seasons(args.seasons)
    detail = set(_seasons(args.detail_seasons)) if args.detail_seasons else set(seasons)
    pbp = loader.load_pbp(sorted(detail)) if detail else {}
    writer = Writer(Path(args.out), adopt=args.adopt)
    sources = _sources()
    stats_seasons = sorted(detail)
    team_stats = loader.load_team_stats(stats_seasons) if detail else {}
    player_stats = loader.load_player_stats(stats_seasons) if detail else {}
    summary = build_all(writer, loader.load_schedules(), loader.load_teams(), pbp, seasons, detail, now, sources,
                        team_stats, player_stats)
    token = os.environ.get("LOGO_DEV_TOKEN", "")
    if token:
        coverage = logos.build(writer, token)
        writer.write("logos/coverage.json", envelope("logo-coverage", coverage))
        summary["logos"] = {"complete": coverage["complete"], "total": coverage["total"]}
    manifest = writer.finish(now, sources, summary)
    total = sum(f["bytes"] for f in manifest["files"].values())
    print(json.dumps({"files": len(manifest["files"]), "bytes": total, "seasons": summary}, indent=1))
    return 0


def cmd_changed(args) -> int:
    from .publish import same_content

    def manifest(root):
        try:
            return json.loads((Path(root) / "nfl" / "v1" / "manifest.json").read_text())
        except (OSError, ValueError):
            return {}
    return 1 if same_content(manifest(args.new), manifest(args.old)) else 0


def _fmt_line(doc: dict) -> str:
    g, ls = doc["game"], doc.get("lineScore")
    rows = [f"{'':5}" + "".join(f"{q:>4}" for q in (["1", "2", "3", "4"] + ["OT"] * (len(ls['home']) - 4)
                                                   if ls else [])) + "    T"]
    for s in ("away", "home"):
        cells = "".join(f"{x:>4}" for x in ls[s]) if ls else "  (line score withheld)"
        rows.append(f"{g[s]['team']:5}{cells}{g[s]['score']:>5}")
    return "\n".join(rows)


def cmd_poc(args) -> int:
    season = int(args.game[:4])
    now = int(time.time() * 1000)
    game = next((g for g in normalize_schedule(loader.load_schedules(), now) if g["id"] == args.game), None)
    if game is None:
        print(f"{args.game} is not in the nflverse schedule", file=sys.stderr)
        return 2
    plays = loader.load_pbp([season]).get(args.game, [])
    doc = game_detail.build(game, plays, loader.load_team_stats([season]).get(args.game),
                            loader.load_player_stats([season]).get(args.game))
    if args.out:
        Path(args.out).write_text(json.dumps(doc, indent=1))
    g = doc["game"]
    print(f"{g['id']}  {g['type']} week {g['week']}  {g['date']} {g['time']} ET  {g['venue']}")
    print(f"FINAL{'/OT' if g['overtime'] else ''}: {g['away']['team']} {g['away']['score']} at "
          f"{g['home']['team']} {g['home']['score']}   analytics: {doc['analytics']}")
    print(_fmt_line(doc))
    print("\nScoring plays")
    for s in doc.get("scoring") or []:
        print(f"  Q{s['qtr']} {s['clock']:>5}  {s['team']:3} {s['kind']:10} +{s['points']}  "
              f"{s['score'][1]}-{s['score'][0]}  {s['try'] or ''}  {s['text'][:90]}")
    print(f"\nTeam stats (box: {doc['boxSource']}; efficiency: LukeOS from play-by-play)")
    keys = ("plays", "yards", "passYards", "rushYards", "yardsPerPlay", "firstDowns", "thirdDown", "fourthDown",
            "redZone", "turnovers", "sacksTaken", "explosive", "timeOfPossession", "epaPerPlay", "passEpaPerPlay",
            "rushEpaPerPlay", "successRate", "explosiveRate")
    away, home = g["away"]["team"], g["home"]["team"]
    for k in keys:
        a, h = doc["teams"][away]["offense"][k], doc["teams"][home]["offense"][k]
        if k == "timeOfPossession":
            a, h = game_detail.clock_text(a), game_detail.clock_text(h)
        print(f"  {k:18} {str(a):>12} {str(h):>12}")
    for t in (away, home):
        p = doc["teams"][t]["penalties"]
        print(f"  penalties {t:8} {p['count']}-{p['yards']}")
    print(f"\nLeaders ({doc['playersSource']})")
    for t, ls in game_detail.leaders(doc).items():
        for k, v in ls.items():
            print(f"  {t} {k:10} {v}")
    print("\nWhat decided it (net EPA, winner's view)")
    for f in doc["factors"]:
        print(f"  {f['label']:22} {f['netEpa']:+.2f}")
    print("\nKey plays (win-probability swing, home view)")
    for k in doc["keyPlays"]:
        print(f"  Q{k['qtr']} {k['clock']} {k['team']} {k['homeWpDelta']:+.3f} {k['text'][:100]}")
    wp = doc.get("winProbability") or []
    print(f"\nWin-probability series: {len(wp)} points (nflfastR model estimate)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nfl_pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--seasons", required=True, help="e.g. 2025 or 2023-2026")
    b.add_argument("--detail-seasons", help="seasons that get per-game breakdowns (default: all)")
    b.add_argument("--out", required=True)
    b.add_argument("--adopt", action="store_true", help="keep files a previous build left in --out")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("changed", help="exit 0 if two builds differ in content, 1 if identical")
    c.add_argument("new")
    c.add_argument("old")
    c.set_defaults(func=cmd_changed)
    p = sub.add_parser("poc")
    p.add_argument("--game", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_poc)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""LukeOS NFL pipeline tests: records, game identity, scoring, analytics, publishing.

Real-data fixtures come from nflverse (CC BY 4.0; tests/fixtures/nfl/README.md). Synthetic rows
are built inline for edge cases nflverse cannot show (half-reported scores, stale rows, ...).
Pure standard library: no nflreadpy, Polars or network needed. Runs in this repository and in
the generated lukeos-nfl-data repository.
"""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
for candidate in (HERE.parent / "nfl-pipeline", HERE.parent):
    if (candidate / "nfl_pipeline").is_dir():
        sys.path.insert(0, str(candidate))
        break

from nfl_pipeline import ATTRIBUTION, game_detail, history, logos, metrics, records, team_season  # noqa: E402
from nfl_pipeline.build import build_all  # noqa: E402
from nfl_pipeline.games import kickoff_ms, normalize_game, normalize_schedule, state_of  # noqa: E402
from nfl_pipeline.publish import Writer, envelope, same_content  # noqa: E402
from nfl_pipeline.teams import franchise, normalize_teams, provider_team, team_index  # noqa: E402

FIX = HERE / "fixtures" / "nfl"
POC = "2025_01_MIN_CHI"
TIE = "2025_04_GB_DAL"


def load(name):
    return json.loads((FIX / name).read_text())


SCHEDULE = load("schedule-2025.json")
TEAMS = normalize_teams(load("teams.json"))
BY_ID = team_index(TEAMS)
GAMES = normalize_schedule(SCHEDULE, None)
GAME = {g["id"]: g for g in GAMES}
PBP = {POC: load(f"pbp-{POC}.json"), TIE: load(f"pbp-{TIE}.json")}
STATS = load(f"stats-{POC}.json")


def row(gid="2030_01_AAA_BBB", home="MIN", away="CHI", hs=None, as_=None, gtype="REG", week=1,
        day="2030-09-15", time="13:00", location="Home", div=1, season=None, ot=0):
    return {"game_id": gid, "season": season or int(day[:4]), "game_type": gtype, "week": week, "gameday": day,
            "gametime": time, "home_team": home, "away_team": away, "home_score": hs, "away_score": as_,
            "location": location, "div_game": div, "overtime": ot}


class GameStateTests(unittest.TestCase):
    def test_states_follow_the_clock_and_never_invent_results(self):
        start = kickoff_ms("2030-09-15", "13:00")
        self.assertEqual(state_of(10, 7, start, start - 1), "final")
        self.assertEqual(state_of(None, None, start, start - 1), "scheduled")
        self.assertEqual(state_of(None, None, start, start + 1), "started")
        self.assertEqual(state_of(None, None, start, start + 13 * 3600 * 1000), "unresolved")

    def test_published_build_has_only_final_or_scheduled(self):
        self.assertEqual({g["state"] for g in GAMES}, {"final"})
        future = normalize_schedule([row()], None)[0]
        self.assertEqual(future["state"], "scheduled")
        self.assertIsNone(future["home"]["score"])

    def test_half_a_score_is_not_a_result(self):
        g = normalize_game(row(hs=7), kickoff_ms("2030-09-15", "13:00") + 1)
        self.assertEqual(g["state"], "started")
        self.assertIsNone(g["home"]["score"])
        self.assertIsNone(g["result"])

    def test_bad_rows_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_game(row(home="MIN", away="MIN"), 0)
        with self.assertRaises(ValueError):
            normalize_game(row(gtype="PRE"), 0)
        with self.assertRaises(ValueError):
            normalize_schedule([row(), row()], 0)

    def test_kickoff_is_eastern_time_with_daylight_saving(self):
        # 2025-09-08 20:15 EDT = 00:15 UTC next day; 2025-12-25 = EST.
        self.assertEqual(kickoff_ms("2025-09-08", "20:15"), 1757376900000)
        self.assertEqual(kickoff_ms("2025-12-25", "13:00") % 86400000, 18 * 3600 * 1000)

    def test_relocated_franchises_share_one_identity(self):
        self.assertEqual(franchise("OAK"), "LV")
        self.assertEqual(franchise("SD"), "LAC")
        self.assertEqual(franchise("STL"), "LA")
        self.assertEqual(provider_team("LAR"), "LA")
        self.assertEqual(provider_team("WSH"), "WAS")
        self.assertIsNone(provider_team("XYZ"))

    def test_overtime_and_tie_come_from_the_schedule(self):
        tie = GAME[TIE]
        self.assertEqual((tie["home"]["score"], tie["away"]["score"], tie["result"], tie["overtime"]),
                         (40, 40, "tie", True))
        self.assertFalse(GAME[POC]["overtime"])


class RecordTests(unittest.TestCase):
    def test_every_team_played_seventeen_and_the_league_balances(self):
        recs = {t["team"]: records.team_record(GAMES, t["team"], BY_ID) for t in TEAMS}
        self.assertTrue(all(r["gamesPlayed"] == 17 for r in recs.values()))
        w = sum(r["raw"]["overall"]["w"] for r in recs.values())
        l_ = sum(r["raw"]["overall"]["l"] for r in recs.values())
        t = sum(r["raw"]["overall"]["t"] for r in recs.values())
        self.assertEqual(w, l_)
        self.assertEqual(t % 2, 0)
        self.assertEqual(w + l_ + t, 2 * sum(1 for g in GAMES if g["type"] == "REG"))

    def test_tie_counts_as_half_a_win(self):
        gb = records.team_record(GAMES, "GB", BY_ID)
        self.assertEqual(gb["raw"]["overall"]["t"], 1)
        r = gb["raw"]["overall"]
        self.assertEqual(gb["pct"], round((r["w"] + 0.5) / 17, 3))
        self.assertTrue(gb["record"].endswith("-1"))

    def test_postseason_is_separate_from_the_regular_season(self):
        rows = [row(gid="2030_01_CHI_MIN", hs=20, as_=10),
                row(gid="2030_19_CHI_MIN", gtype="WC", week=19, day="2031-01-10", season=2030, hs=10, as_=20)]
        games = normalize_schedule(rows, None)
        r = records.team_record(games, "MIN", BY_ID)
        self.assertEqual(r["record"], "1-0")
        self.assertEqual(r["postseason"]["record"], "0-1")
        self.assertEqual(r["streak"], "L1")  # streak runs through the postseason

    def test_unplayed_and_half_reported_games_never_count(self):
        rows = [row(gid="2030_01_CHI_MIN", hs=20, as_=10), row(gid="2030_02_GB_MIN", away="GB", week=2,
                                                                 day="2030-09-22"),
                row(gid="2030_03_DET_MIN", away="DET", week=3, day="2030-09-29", hs=3)]
        r = records.team_record(normalize_schedule(rows, 10**13), "MIN", BY_ID)
        self.assertEqual((r["record"], r["gamesPlayed"], r["pointsFor"]), ("1-0", 1, 20))

    def test_neutral_site_is_neither_home_nor_away(self):
        games = normalize_schedule([row(gid="2030_05_CHI_MIN", hs=24, as_=21, location="Neutral")], None)
        s = records.team_record(games, "MIN", BY_ID)["splits"]
        self.assertEqual((s["home"], s["away"], s["neutral"]), ("0-0", "0-0", "1-0"))

    def test_a_tie_ends_a_streak(self):
        self.assertEqual(records.streak(["w", "w", "t"]), "T1")
        self.assertEqual(records.streak(["l", "w", "w"]), "W2")
        self.assertIsNone(records.streak([]))

    def test_vikings_2025_splits_add_up(self):
        r = records.team_record(GAMES, "MIN", BY_ID)
        raw = r["raw"]
        total = sum(raw["overall"].values())
        self.assertEqual(sum(sum(raw[k].values()) for k in ("home", "away", "neutral")), total)
        self.assertEqual(sum(raw["division"].values()), 6)
        mine = [g for g in GAMES if "MIN" in (g["home"]["team"], g["away"]["team"])]
        pf = sum(g["home"]["score"] if g["home"]["team"] == "MIN" else g["away"]["score"] for g in mine)
        self.assertEqual(r["pointsFor"], pf)

    def test_standings_cover_eight_divisions_and_rank_by_pct(self):
        table = records.standings(GAMES, 2025, TEAMS)
        self.assertEqual(len(table["divisions"]), 8)
        self.assertTrue(all(len(d["teams"]) == 4 for d in table["divisions"]))
        self.assertEqual(table["tiebreak"], "approximate")
        self.assertTrue(table["complete"])
        for d in table["divisions"]:
            pcts = [r["pct"] for r in d["teams"]]
            self.assertEqual(pcts, sorted(pcts, reverse=True))

    def test_before_2002_there_are_no_division_or_conference_tables(self):
        old = normalize_schedule([row(gid="1999_01_CHI_MIN", day="1999-09-12", hs=10, as_=7)], None)
        table = records.standings(old, 1999, TEAMS)
        self.assertIsNone(table["divisions"])
        self.assertIsNone(table["conferences"])
        self.assertEqual(records.team_record(old, "MIN", BY_ID)["splits"]["conference"], "0-0")

    def test_head_to_head_follows_the_franchise_through_relocation(self):
        hist = normalize_schedule(load("schedule-min-lv-history.json"), None)
        h = history.head_to_head(hist, "LV", "MIN")
        self.assertEqual(h["meetings"], 7)
        self.assertEqual(h["regular"], "3-4")  # LV's view: OAK won 1999, 2003, 2011
        self.assertEqual(h["recent"][0]["id"], "2023_14_MIN_LV")
        self.assertEqual(h["since"], 1999)


class GameDetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = game_detail.build(GAME[POC], PBP[POC])
        cls.tie = game_detail.build(GAME[TIE], PBP[TIE])

    def test_final_score_and_line_score_agree_with_the_schedule(self):
        self.assertEqual(self.doc["lineScore"], {"home": [7, 3, 7, 7], "away": [0, 6, 0, 21]})
        self.assertEqual(self.doc["quality"], {})
        self.assertEqual(sum(self.doc["lineScore"]["away"]), GAME[POC]["away"]["score"])

    def test_scoring_summary_merges_tries_and_sums_to_the_final(self):
        s = self.doc["scoring"]
        self.assertEqual(len(s), 9)
        self.assertEqual(sum(x["points"] for x in s), 51)
        self.assertEqual([x["try"] for x in s if x["kind"].endswith("td")],
                         ["PAT good", "PAT good", "2-pt failed", "2-pt good", "PAT good", "PAT good"])
        self.assertEqual(s[-1]["score"], [24, 27])
        self.assertEqual(s[4]["kind"], "return_td")  # the pick-six
        scores = [tuple(x["score"]) for x in s]
        self.assertEqual(scores, sorted(scores, key=sum))  # never goes backwards

    def test_stale_running_scores_do_not_create_phantom_scores(self):
        g = normalize_schedule([row(gid="2030_01_CHI_MIN", hs=3, as_=0)], None)[0]
        plays = [{"game_id": g["id"], "play_id": i, "qtr": 1, "time": "10:00", "quarter_seconds_remaining": 600,
                  "total_home_score": h, "total_away_score": 0, "field_goal_result": fg, "desc": d}
                 for i, (h, fg, d) in enumerate([(0, None, "kick"), (3, "made", "FG good"), (0, None, "Timeout"),
                                                 (3, None, "kickoff")], 1)]
        s = game_detail.scoring_plays(plays, g)
        self.assertEqual([(x["kind"], x["points"]) for x in s], [("fg", 3)])

    def test_defensive_two_point_is_not_folded_into_the_touchdown(self):
        g = normalize_schedule([row(gid="2030_01_CHI_MIN", hs=6, as_=2)], None)[0]
        base = {"game_id": g["id"], "qtr": 2, "time": "5:00", "quarter_seconds_remaining": 300}
        plays = [{**base, "play_id": 1, "touchdown": 1, "rush_touchdown": 1, "total_home_score": 6,
                  "total_away_score": 0, "desc": "TD"},
                 {**base, "play_id": 2, "two_point_attempt": 1, "two_point_conv_result": "failure",
                  "defensive_two_point_conv": 1, "total_home_score": 6, "total_away_score": 2, "desc": "def 2pt"}]
        s = game_detail.scoring_plays(plays, g)
        self.assertEqual([(x["team"], x["points"]) for x in s], [("MIN", 6), ("CHI", 2)])

    def test_play_by_play_disagreeing_with_the_final_is_withheld(self):
        wrong = {**GAME[POC], "home": {**GAME[POC]["home"], "score": 99}}
        doc = game_detail.build(wrong, PBP[POC])
        self.assertTrue(doc["quality"]["scoreMismatch"])
        self.assertIsNone(doc["lineScore"])
        self.assertIsNone(doc["scoring"])

    def test_no_play_by_play_means_pending_not_empty_stats(self):
        doc = game_detail.build(GAME[POC], [])
        self.assertEqual(doc["analytics"]["status"], "pending")
        self.assertNotIn("teams", doc)
        with self.assertRaises(ValueError):
            game_detail.build(normalize_schedule([row()], None)[0], [])

    def test_derived_box_score_matches_nflverse_stats(self):
        mn, ch = self.doc["teams"]["MIN"]["offense"], self.doc["teams"]["CHI"]["offense"]
        self.assertEqual((mn["passYardsGross"], mn["rushYards"], mn["sacksTaken"]), (143, 120, 3))
        self.assertEqual((ch["passYardsGross"], ch["rushYards"], ch["sacksTaken"]), (210, 119, 2))
        self.assertEqual(self.doc["teams"]["CHI"]["penalties"], {"count": 12, "yards": 127})
        self.assertEqual(mn["timeOfPossession"] + ch["timeOfPossession"], 3600)
        qb = self.doc["players"]["MIN"]["passing"][0]
        self.assertEqual((qb["cmp"], qb["att"], qb["yds"], qb["td"], qb["int"]), (13, 20, 143, 2, 1))
        moore = next(r for r in self.doc["players"]["CHI"]["receiving"] if r["id"] == "00-0034827")
        self.assertEqual(moore["yds"], 68)  # includes the 11 lateral yards nflverse credits

    def test_published_stats_take_priority_and_are_labelled(self):
        doc = game_detail.build(GAME[POC], PBP[POC], STATS["team"], STATS["player"])
        self.assertEqual(doc["boxSource"], "nflverse stats_team")
        self.assertEqual(doc["playersSource"], "nflverse stats_player")
        self.assertEqual(doc["teams"]["MIN"]["offense"]["passYards"], 143 - 9)
        self.assertEqual(doc["players"]["CHI"]["passing"][0]["name"], "Caleb Williams")
        # CHI lost the final-play lateral fumble; nflverse's total counts it, its component columns don't.
        self.assertEqual((doc["teams"]["CHI"]["offense"]["fumblesLost"], doc["teams"]["CHI"]["offense"]["turnovers"]), (1, 1))
        self.assertEqual(doc["teams"]["MIN"]["offense"]["turnovers"], 1)
        self.assertEqual(self.doc["boxSource"], "LukeOS from play-by-play")

    def test_efficiency_metrics_use_documented_filters(self):
        plays = PBP[POC]
        scrim = [p for p in plays if p["posteam"] == "MIN" and metrics.is_scrimmage(p)]
        epa = round(sum(p["epa"] for p in scrim) / len(scrim), 3)
        self.assertEqual(self.doc["teams"]["MIN"]["offense"]["epaPerPlay"], epa)
        succ = round(sum(1 for p in scrim if p["epa"] > 0) / len(scrim), 3)
        self.assertEqual(self.doc["teams"]["MIN"]["offense"]["successRate"], succ)
        self.assertEqual(self.doc["teams"]["MIN"]["offense"]["redZone"], [3, 4])
        self.assertIsNone(metrics.offense([], "MIN")["successRate"])  # no plays: unknown, not 0%

    def test_epa_phases_sum_to_the_total_margin(self):
        phases = sum(f["netEpa"] for f in self.doc["factors"])
        total = sum((p["epa"] if p["posteam"] == "MIN" else -p["epa"]) for p in PBP[POC]
                    if p.get("epa") is not None and p.get("posteam"))
        self.assertAlmostEqual(phases, total, delta=0.05)
        self.assertEqual(self.doc["factors"][0]["phase"], "turnovers")  # the pick-six dominated
        self.assertEqual(self.doc["factors"][0]["team"], "MIN")  # winner's point of view

    def test_win_probability_is_bounded_and_ends_at_the_result(self):
        wp = self.doc["winProbability"]
        self.assertLessEqual(len(wp), game_detail.WP_POINTS + 1)
        self.assertTrue(all(0 <= p[1] <= 1 for p in wp))
        self.assertEqual(wp[-1][1], 0.0)  # home (CHI) lost
        self.assertEqual([p[0] for p in wp], sorted(p[0] for p in wp))
        self.assertEqual(self.tie["winProbability"][-1][1], 0.5)

    def test_overtime_tie_has_a_fifth_period(self):
        ls = self.tie["lineScore"]
        self.assertEqual(len(ls["home"]), 5)
        self.assertEqual((sum(ls["home"]), sum(ls["away"])), (40, 40))
        ot_row = next(p for p in PBP[TIE] if p.get("qtr") == 5)
        self.assertGreaterEqual(game_detail.elapsed(ot_row, GAME[TIE]), 3600)
        self.assertEqual(game_detail._ot_length(GAME[TIE]), 600)
        self.assertEqual(game_detail._ot_length({**GAME[TIE], "postseason": True}), 900)

    def test_key_plays_are_the_largest_swings(self):
        swings = [abs(k["homeWpDelta"]) for k in self.doc["keyPlays"]]
        self.assertEqual(swings, sorted(swings, reverse=True))
        self.assertIn("INTERCEPTED", self.doc["keyPlays"][0]["text"])


class TeamSeasonTests(unittest.TestCase):
    def test_hub_record_matches_records_and_game_log_is_complete(self):
        hub = team_season.build(2025, GAMES, PBP, "MIN", BY_ID, records.standings(GAMES, 2025, TEAMS))
        self.assertEqual(len(hub["games"]), 17)
        self.assertEqual(hub["record"]["record"], records.team_record(GAMES, "MIN", BY_ID)["record"])
        self.assertEqual(hub["standing"]["division"], "NFC North")
        self.assertEqual(hub["analytics"]["gamesCovered"], 1)  # only one game's pbp in fixtures
        self.assertIsNone(hub["next"])  # 2025 is over
        self.assertEqual(hub["games"][0]["result"], "W")
        self.assertEqual(hub["games"][0]["opp"], "CHI")


class PublishTests(unittest.TestCase):
    def _build(self, root, adopt=False, schedule=None):
        w = Writer(root, adopt=adopt)
        summary = build_all(w, schedule or SCHEDULE, load("teams.json"), PBP, [2025], {2025}, 0, {"nflverse": {}},
                            {POC: STATS["team"]}, {POC: STATS["player"]})
        return w, w.finish(123, {"nflverse": {"pbp": "x"}}, summary)

    def test_build_is_deterministic_and_never_claims_live(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            _, ma = self._build(Path(a))
            _, mb = self._build(Path(b))
            self.assertTrue(same_content(ma, mb))
            doc = json.loads((Path(a) / "nfl/v1/games/2025" / f"{POC}.json").read_text())
            self.assertFalse(doc["live"])
            self.assertEqual(doc["contract"], "nfl.v1")
            self.assertNotIn("generatedAt", doc)
            self.assertEqual(ma["seasons"]["2025"]["analytics"], 2)
            s25 = ma["seasons"]["2025"]
            self.assertEqual((s25["analytics"], s25["mismatch"]), (2, 0))
            self.assertEqual(s25["analytics"] + s25["pending"] + s25["noPlayByPlay"], 285)
            self.assertEqual(ma["attribution"]["license"], "CC-BY-4.0")
            games = json.loads((Path(a) / "nfl/v1/seasons/2025/games.json").read_text())["data"]
            self.assertEqual({g["state"] for g in games}, {"final"})

    def test_missing_play_by_play_is_pending_only_at_the_end_of_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            self._build(Path(d))
            games = {g["id"]: g for g in json.loads((Path(d) / "nfl/v1/seasons/2025/games.json").read_text())["data"]}
            early = next(g for g in games.values() if g["week"] == 1 and g["id"] != POC)
            late = max(games.values(), key=lambda g: g["start"])
            self.assertEqual(games[POC]["analytics"], "available")
            self.assertEqual(early["analytics"], "unavailable")  # GB_DAL (week 4) has pbp, so week 1 is a gap
            self.assertEqual(late["analytics"], "pending")  # after the newest covered game: may still arrive

    def test_rebuild_prunes_games_that_left_the_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            self._build(Path(d))
            self.assertTrue((Path(d) / f"nfl/v1/games/2025/{TIE}.json").exists())
            fewer = [r for r in SCHEDULE if r["game_id"] != TIE]
            w, m = self._build(Path(d), adopt=True, schedule=fewer)
            self.assertFalse((Path(d) / f"nfl/v1/games/2025/{TIE}.json").exists())
            self.assertNotIn(f"games/2025/{TIE}.json", m["files"])
            self.assertIn("history/h2h/ARI_ATL.json", m["files"])  # adopted, still listed

    def test_unsafe_paths_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            w = Writer(Path(d))
            for bad in ("../x.json", "/etc/x", "a/../../b", "a b.json"):
                with self.assertRaises(ValueError):
                    w.write(bad, {})

    def test_envelope_carries_attribution(self):
        self.assertEqual(envelope("x", 1)["attribution"], ATTRIBUTION["text"])


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeOpener:
    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def open(self, req, timeout=None):
        self.urls.append(req.full_url)
        answer = self.answers(req.full_url)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(req.full_url, answer, "x", {}, None)
        return FakeResponse(answer)


def png(w, h):
    import struct
    return logos.PNG_MAGIC + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"


class LogoTests(unittest.TestCase):
    def test_lookup_asks_for_404_instead_of_a_generated_monogram(self):
        u = logos.url("vikings.com", 128, "pk_test")
        self.assertIn("fallback=404", u)
        self.assertIn("format=png", u)

    def test_coverage_is_verified_per_team_and_size(self):
        def answers(u):
            if "vikings.com" in u:
                return png(256, 256) if "size=256" in u else png(128, 128)
            if "chicagobears.com" in u:
                return 404
            if "packers.com" in u:
                return b"<html>not an image</html>"
            return png(8, 8)
        with tempfile.TemporaryDirectory() as d:
            w = Writer(Path(d))
            report = logos.build(w, "pk_test", FakeOpener(answers))
            self.assertEqual(report["teams"]["MIN"]["sizes"]["128"]["status"], "ok")
            self.assertEqual(report["teams"]["CHI"]["sizes"]["128"]["status"], "missing")
            self.assertEqual(report["teams"]["GB"]["sizes"]["128"]["status"], "error:not-png")
            self.assertEqual(report["teams"]["DAL"]["sizes"]["128"]["status"], "error:too-small")
            self.assertEqual(report["complete"], 1)
            self.assertTrue((Path(d) / "nfl/v1/logos/MIN-128.png").exists())
            self.assertFalse((Path(d) / "nfl/v1/logos/CHI-128.png").exists())
            self.assertEqual(report["credit"], "Logos provided by Logo.dev")


if __name__ == "__main__":
    unittest.main()

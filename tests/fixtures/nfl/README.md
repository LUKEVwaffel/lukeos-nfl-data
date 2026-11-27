# NFL test fixtures (real data)

Extracted 2026-11-27 with nflreadpy 0.1.5 from nflverse releases (`pbp`, `schedules`, `teams`,
`stats_team`, `stats_player`). nflverse data is licensed CC BY 4.0:
https://github.com/nflverse/nflverse-data. EPA and win probability are nflfastR model outputs.

- `pbp-2025_01_MIN_CHI.json` - every play of 2025 week 1, Vikings 27 at Bears 24 (pipeline columns only)
- `pbp-2025_04_GB_DAL.json` - 2025 week 4, Packers at Cowboys, a tie after overtime
- `schedule-2025.json` - all 285 games of 2025 (pipeline columns only)
- `schedule-min-lv-history.json` - every Vikings/Raiders meeting since 1999 (OAK and LV abbreviations)
- `teams.json` - nflverse teams table (36 rows incl. historical abbreviations; logo URLs dropped)
- `stats-2025_01_MIN_CHI.json` - nflverse team and player box score rows for that game

Synthetic edge cases (canceled, postponed, live, conflicting providers) are built in the tests
themselves and are clearly not real results.

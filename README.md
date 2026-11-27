# lukeos-nfl-data

Scheduled NFL data build for LukeOS Sports. GitHub Actions runs `nfl_pipeline` on nflverse data
every 6 hours (current season) and every Tuesday (full history since 1999), and publishes the JSON
documents as a single-commit `data` branch. No personal computer needs to be on. The LukeOS Sports
proxy reads `https://raw.githubusercontent.com/<owner>/lukeos-nfl-data/data/nfl/v1/...`.

## What is published

Schedules, results, records, approximate standings, team-season summaries, per-game postgame
breakdowns (scoring, drives, box scores, EPA, success rate, win probability) and head-to-head history,
all derived from nflverse. No logos, credentials or personal data.

## Attribution and licences

- Data: nflverse (https://github.com/nflverse/nflverse-data), CC BY 4.0, including nflfastR
  play-by-play and nfldata schedules. EPA and win probability are nflfastR model estimates.
- FTN charting data (CC BY-SA 4.0) is not used.
- Code: part of LukeOS.

## Limits

- nflverse is not live: play-by-play is published nightly in season. Live scores come from a separate
  provider in the Sports proxy and are labelled as live there.
- GitHub-hosted scheduled runs can start late; the manifest records when each build ran and when
  nflverse last updated its releases.

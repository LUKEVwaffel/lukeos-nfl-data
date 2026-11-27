"""LukeOS NFL data pipeline.

Turns nflverse datasets (schedules, teams, play-by-play) into small, versioned JSON documents
the Sports proxy can serve to the YMP-A1. Everything except ``loader`` is pure standard-library
Python working on plain row dicts, so the logic is testable without nflreadpy or Polars.

Data: nflverse (https://github.com/nflverse/nflverse-data), CC BY 4.0. Win probability and EPA
are nflfastR model outputs carried in that data; LukeOS only aggregates them.
"""

CONTRACT = "nfl.v1"
SCHEMA = 1

ATTRIBUTION = {
    "text": "NFL data: nflverse (nflfastR play-by-play, nfldata schedules), CC BY 4.0",
    "url": "https://github.com/nflverse/nflverse-data",
    "license": "CC-BY-4.0",
    "models": "EPA and win probability are nflfastR model estimates",
}

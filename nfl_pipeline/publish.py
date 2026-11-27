"""Write versioned, compact JSON documents plus a manifest that lists each file's hash.

Layout (all under ``<out>/nfl/v1/``):

    manifest.json                      written last; readers trust only files it lists
    teams.json                         32 franchises: names, conference, division, colours
    definitions.json                   metric labels, kinds, formulas, explanations
    seasons/<season>/games.json        every game of the season with its state and final score
    seasons/<season>/standings.json    derived standings (approximate tiebreaks, labelled)
    seasons/<season>/teams/<TEAM>.json team hub for that season
    games/<season>/<game_id>.json      postgame breakdown (final games with play-by-play)
    history/h2h/<A>_<B>.json           all-time head-to-head for each franchise pair
    logos/<TEAM>-<size>.png            Logo.dev PNGs (only when LOGO_DEV_TOKEN is set at build)
    logos/coverage.json                which teams/sizes were found and verified

Every document is wrapped in an envelope that says it is postgame/historical data, never live.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import ATTRIBUTION, CONTRACT, SCHEMA

SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]{1,160}$")


def envelope(kind: str, data) -> dict:
    """Documents carry no build time or source timestamps, so unchanged inputs give byte-identical
    files and the scheduled job publishes only real changes. Both live in manifest.json."""
    return {"contract": CONTRACT, "schema": SCHEMA, "kind": kind, "live": False,
            "attribution": ATTRIBUTION["text"], "data": data}


def dumps(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class Writer:
    """Writes documents under ``<root>/nfl/v1``.

    ``adopt=True`` keeps what a previous build published there (the scheduled job checks out
    the data branch first), so a run that rebuilds only the current season still publishes a
    complete tree. Rebuilt seasons are pruned of files this run did not write, so a game that
    left the schedule cannot linger.
    """

    def __init__(self, root: Path, adopt: bool = False):
        self.root = Path(root) / "nfl" / "v1"
        self.files: dict[str, dict] = {}
        self.written: set[str] = set()
        self.previous_seasons: dict = {}
        if adopt and self.root.is_dir():
            for path in sorted(self.root.rglob("*")):
                rel = path.relative_to(self.root).as_posix()
                if path.is_file() and rel != "manifest.json" and not rel.endswith(".tmp"):
                    body = path.read_bytes()
                    self.files[rel] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            try:
                self.previous_seasons = json.loads((self.root / "manifest.json").read_text()).get("seasons", {})
            except (OSError, ValueError):
                self.previous_seasons = {}

    def prune(self, prefixes: list[str]) -> list[str]:
        """Delete adopted files under ``prefixes`` that this run did not rewrite."""
        removed = []
        for rel in sorted(self.files):
            if rel not in self.written and any(rel.startswith(p) for p in prefixes):
                (self.root / rel).unlink(missing_ok=True)
                del self.files[rel]
                removed.append(rel)
        return removed

    def write(self, rel: str, obj) -> None:
        self.write_bytes(rel, dumps(obj))

    def write_bytes(self, rel: str, body: bytes) -> None:
        if not SAFE_PATH.match(rel) or ".." in rel or rel.startswith("/"):
            raise ValueError(f"unsafe path {rel!r}")
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)
        self.files[rel] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        self.written.add(rel)

    def finish(self, generated_ms: int, sources: dict, seasons: dict) -> dict:
        merged = {**self.previous_seasons, **seasons}
        manifest = {"contract": CONTRACT, "schema": SCHEMA, "generatedAt": generated_ms, "live": False,
                    "sources": sources, "attribution": ATTRIBUTION, "seasons": dict(sorted(merged.items())),
                    "files": dict(sorted(self.files.items()))}
        self.write("manifest.json", manifest)
        return manifest


def same_content(a: dict, b: dict) -> bool:
    """True when two manifests list identical files (build time and source stamps ignored)."""
    strip = lambda m: {k: v for k, v in (m.get("files") or {}).items() if k != "manifest.json"}  # noqa: E731
    return strip(a) == strip(b)

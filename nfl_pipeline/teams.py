"""NFL team identity: canonical franchise ids, historical abbreviations, branding inputs.

Canonical team id is the current nflverse abbreviation ("MIN", "LV", "LA"). Historical rows keep
the abbreviation that season used ("OAK" in 2019) as ``abbr`` while ``team`` is the franchise.
"""
from __future__ import annotations

from .values import text

# Relocations: historical nflverse abbreviation -> current franchise abbreviation.
FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}

CURRENT = (
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND",
    "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF",
    "TB", "TEN", "WAS",
)

# Official club web domains, used only as Logo.dev lookup keys. Coverage is verified by
# scripts/nfl_logo_check.py; a domain here is not proof that Logo.dev has the right asset.
DOMAINS = {
    "ARI": "azcardinals.com", "ATL": "atlantafalcons.com", "BAL": "baltimoreravens.com",
    "BUF": "buffalobills.com", "CAR": "panthers.com", "CHI": "chicagobears.com", "CIN": "bengals.com",
    "CLE": "clevelandbrowns.com", "DAL": "dallascowboys.com", "DEN": "denverbroncos.com",
    "DET": "detroitlions.com", "GB": "packers.com", "HOU": "houstontexans.com", "IND": "colts.com",
    "JAX": "jaguars.com", "KC": "chiefs.com", "LA": "therams.com", "LAC": "chargers.com",
    "LV": "raiders.com", "MIA": "miamidolphins.com", "MIN": "vikings.com", "NE": "patriots.com",
    "NO": "neworleanssaints.com", "NYG": "giants.com", "NYJ": "newyorkjets.com",
    "PHI": "philadelphiaeagles.com", "PIT": "steelers.com", "SEA": "seahawks.com", "SF": "49ers.com",
    "TB": "buccaneers.com", "TEN": "tennesseetitans.com", "WAS": "commanders.com",
}

# Abbreviations other providers use for the same franchise (live-score matching).
PROVIDER_ALIASES = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "LVR": "LV", "OAK": "LV", "SD": "LAC",
                    "STL": "LA", "KAN": "KC", "GNB": "GB", "NWE": "NE", "NOR": "NO", "SFO": "SF",
                    "TAM": "TB"}


def franchise(abbr: str | None) -> str | None:
    a = text(abbr)
    if a is None:
        return None
    a = a.upper()
    return FRANCHISE.get(a, a)


def provider_team(abbr: str | None) -> str | None:
    """Map another provider's abbreviation onto the canonical franchise id, or None."""
    a = text(abbr)
    if a is None:
        return None
    a = a.upper()
    a = PROVIDER_ALIASES.get(a, a)
    return a if a in CURRENT else None


def _color(value) -> str | None:
    s = text(value)
    if s and len(s) == 7 and s.startswith("#"):
        try:
            int(s[1:], 16)
        except ValueError:
            return None
        return s.upper()
    return None


def normalize_teams(rows: list[dict]) -> list[dict]:
    """The 32 current franchises from nflverse ``load_teams()`` rows.

    Logo URLs in that dataset (ESPN, Wikipedia) are deliberately dropped: their reuse terms are
    not established. Colours are factual identity data and are kept.
    """
    by_abbr = {text(r.get("team_abbr")): r for r in rows}
    out = []
    for abbr in CURRENT:
        r = by_abbr.get(abbr)
        if r is None:
            raise ValueError(f"teams dataset is missing {abbr}")
        division = text(r.get("team_division")) or ""
        out.append({
            "team": abbr,
            "name": text(r.get("team_name")) or abbr,
            "nick": text(r.get("team_nick")) or abbr,
            "conf": text(r.get("team_conf")) or "",
            "division": division,
            "colors": [c for c in (_color(r.get("team_color")), _color(r.get("team_color2"))) if c],
            "logoKey": DOMAINS[abbr],
        })
    return out


def team_index(teams: list[dict]) -> dict:
    return {t["team"]: t for t in teams}


def conference_of(teams_by_id: dict, team: str) -> str | None:
    t = teams_by_id.get(franchise(team))
    return t["conf"] if t else None

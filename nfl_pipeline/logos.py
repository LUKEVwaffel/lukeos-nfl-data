"""Team logos from Logo.dev, fetched at build time and published as static PNGs.

Why build time: the Logo.dev key then lives only in the CI secret store. It is never in the APK
and never in the proxy's runtime environment. Logo.dev's pricing FAQ allows storing what the API
returns and serving it from your own servers on every plan; the free (Community) plan needs a
"Logos provided by Logo.dev" link for commercial use and none for personal projects. LukeOS
shows the credit anyway. Logos are club trademarks: Logo.dev grants no licence to them, so they
are used only to identify teams, never altered or combined into new marks.

Coverage is verified, not assumed: each lookup uses ``fallback=404`` so a missing logo is a 404
instead of a generated monogram, and every file is checked for PNG structure and size. The
report still flags every team for one-time visual review, because a domain lookup can return a
club's site icon rather than its primary mark.
"""
from __future__ import annotations

import hashlib
import struct
import urllib.error
import urllib.parse
import urllib.request

from .teams import CURRENT, DOMAINS

SIZES = (64, 128, 256)
CDN = "https://img.logo.dev/{domain}?{query}"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_BYTES = 512 * 1024


def png_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(PNG_MAGIC) or len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def url(domain: str, size: int, token: str) -> str:
    q = urllib.parse.urlencode({"token": token, "size": size, "format": "png", "retina": "false",
                                "fallback": "404"})
    return CDN.format(domain=domain, query=q)


def fetch(domain: str, size: int, token: str, opener=None, timeout: float = 10.0) -> tuple[str, bytes | None]:
    """('ok', png) | ('missing', None) | ('error:<reason>', None). Never raises on HTTP errors."""
    open_ = (opener or urllib.request.build_opener()).open
    req = urllib.request.Request(url(domain, size, token), headers={"User-Agent": "LukeOS-NFL-Pipeline/1"})
    try:
        with open_(req, timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        e.close()
        return ("missing", None) if e.code == 404 else (f"error:http{e.code}", None)
    except (urllib.error.URLError, TimeoutError, OSError):
        return "error:network", None
    if len(data) > MAX_BYTES:
        return "error:oversized", None
    dims = png_size(data)
    if dims is None:
        return "error:not-png", None
    if min(dims) < size // 2:
        return "error:too-small", None
    return "ok", data


def build(writer, token: str, opener=None) -> dict:
    """Fetch every team at every size; write logos/<TEAM>-<size>.png and logos/coverage.json."""
    report = {}
    for team in CURRENT:
        entry = {"domain": DOMAINS[team], "sizes": {}, "review": "visual check required"}
        for size in SIZES:
            status, data = fetch(DOMAINS[team], size, token, opener)
            if data is not None:
                writer.write_bytes(f"logos/{team}-{size}.png", data)
                w, h = png_size(data)
                entry["sizes"][str(size)] = {"status": status, "width": w, "height": h,
                                             "sha256": hashlib.sha256(data).hexdigest()}
            else:
                entry["sizes"][str(size)] = {"status": status}
        report[team] = entry
    ok = sum(1 for e in report.values() if all(s["status"] == "ok" for s in e["sizes"].values()))
    return {"teams": report, "complete": ok, "total": len(CURRENT),
            "credit": "Logos provided by Logo.dev", "creditUrl": "https://logo.dev"}

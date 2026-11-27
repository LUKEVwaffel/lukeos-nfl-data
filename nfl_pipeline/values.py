"""Small, strict value readers for nflverse rows (which mix None, NaN, floats and strings)."""
import math
import re

_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")


def num(value):
    """A finite float, or None for None/NaN/inf/non-numbers."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def integer(value):
    f = num(value)
    return None if f is None else int(round(f))


def flag(value):
    """nflverse binary indicators arrive as 1.0/0.0/None."""
    f = num(value)
    return f is not None and f >= 0.5


def text(value):
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    s = str(value).strip()
    return s or None


def clock_seconds(value):
    """'M:SS' or 'MM:SS' to seconds; None when not a clock."""
    s = text(value)
    if not s:
        return None
    m = _CLOCK.match(s)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def fmt_clock(seconds):
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def ratio(numerator, denominator, digits=3):
    """Rounded ratio, or None when the denominator is zero (never a fake 0%)."""
    if not denominator:
        return None
    return round(numerator / denominator, digits) + 0.0


def mean(values, digits=3):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), digits) + 0.0  # + 0.0 turns -0.0 into 0.0

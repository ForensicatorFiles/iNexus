"""
General-purpose helpers: HTML escaping, hashing, timestamp conversion,
geo math, and phone-number normalization. No forensic-source-specific
logic lives here — see loaders/ and analysis.py for that.
"""
import hashlib, math, os, re
from datetime import datetime, timezone, timedelta

from .constants import APPLE_EPOCH

def esc_html(s):
    """HTML-escape a string for safe inline injection into the report template."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace('"', "&quot;"))

def sha256_file(path, chunk_size=1024 * 1024):
    """
    Compute the SHA-256 hash of a file in fixed-size chunks (default 1 MB),
    so multi-GB extraction files don't need to be loaded into memory at once.
    Used for chain-of-custody / integrity verification in the report.
    Returns the lowercase hex digest, or None if the file can't be read.
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ── HEIC → JPEG batch conversion (optional, for in-report previews) ──────────
def _unique_dir(base):
    """Return a directory path that doesn't yet exist. If `base` is taken,
    append _1, _2, … until a free name is found (never overwrites)."""
    if not os.path.exists(base):
        return base
    i = 1
    while True:
        cand = f"{base}_{i}"
        if not os.path.exists(cand):
            return cand
        i += 1


def apple_ts(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts + APPLE_EPOCH, tz=timezone.utc)

def unix_ts(ts):
    """Apple CoreData timestamp → Unix timestamp (float)."""
    if ts is None:
        return None
    return ts + APPLE_EPOCH

def unix_ts_ns(ts):
    """
    Apple CoreData timestamp in NANOSECONDS → Unix timestamp (float).

    sms.db's message.date/date_read/date_delivered columns switched from
    seconds to nanoseconds since the Apple epoch on iOS 11+ — unlike
    Photos.sqlite/Cache.sqlite/knowledgeC.db, which all still use whole
    seconds. Mixing these up silently produces a timestamp ~22 billion years
    in the future, so this is kept as a distinct helper rather than letting
    callers accidentally pass message.date through unix_ts().
    """
    if ts is None or ts == 0:
        return None
    return (ts / 1_000_000_000) + APPLE_EPOCH

def fmt_dt(dt, local_offset_hours=0):
    """Format a datetime object. If a float is passed, treat as Unix timestamp."""
    if dt is None:
        return "—"
    if isinstance(dt, (int, float)):
        dt = datetime.fromtimestamp(dt, tz=timezone.utc)
    local = dt + timedelta(hours=local_offset_hours)
    return local.strftime("%Y-%m-%d %H:%M:%S")

def fmt_dur(seconds):
    if seconds is None or seconds < 0:
        return "—"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"

def haversine(lat1, lon1, lat2, lon2):
    """Distance in metres between two lat/lon points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def centroid(points):
    """Mean lat/lon of a list of (lat, lon) tuples."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return sum(lats)/len(lats), sum(lons)/len(lons)

# ── Phone-number normalization ─────────────────────────────────────────────────
def normalize_phone(raw):
    """
    Canonicalizes a phone number for matching across sources that format
    the same number differently — sms.db/CallHistory.storedata vs.
    AddressBook.sqlitedb routinely disagree on punctuation/spacing/country
    code for the literal same number, e.g. '+15828887553',
    '(919) 888-7386', '+1 919-888-7386', and '1 (919) 923-3798' all need to
    collapse to the same key.

    Strategy: strip everything but digits, then drop a leading '1' on an
    11-digit result (US/Canada country code) so a 10-digit number is the
    canonical form. Numbers that aren't 10 or 11 digits after stripping
    (international numbers, vanity numbers with letters, short codes) are
    returned as their stripped-digit form as-is — not US-normalized, but
    still comparable to another occurrence of the same raw value.

    Returns None for empty/non-phone input, never raises.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits



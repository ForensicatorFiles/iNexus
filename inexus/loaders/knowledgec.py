"""Load app foreground/background usage sessions from knowledgeC.db and
correlate them to detected stays / the GPS ping stream."""

import sqlite3

from ..db import _open_sqlite_or_die
from ..utils import apple_ts, fmt_dt, unix_ts
from ..classification import classify_app_session

def load_knowledgec(path, photos_db_path=None):
    """
    Loads app foreground/background usage sessions from a knowledgeC.db.

    knowledgeC.db uses Apple's generic Core Duet object model: every kind of
    behavioral event (app usage, notifications, now-playing, bluetooth state,
    etc.) lives in one ZOBJECT table, discriminated by ZSTREAMNAME. This
    loader only reads the '/app/usage' stream — each row is one foreground
    session for a single app, with ZVALUESTRING holding the bundle ID
    directly and ZSTARTDATE/ZENDDATE marking the session in the same Apple
    CoreData epoch used throughout Photos.sqlite and Cache.sqlite, so the
    existing apple_ts()/unix_ts() helpers apply unchanged.

    These sessions carry no location of their own — that's the whole reason
    they go through the same interpolate_location() pipeline as photos
    (see correlate_app_sessions() below) rather than being self-contained.

    Returns a list of session dicts, each with: bundle_id, category,
    subcategory, start (unix), end (unix), start_str/end_str, duration,
    tz_offset_secs. Returns an empty list if this file has no /app/usage rows
    (e.g. wrong file, or a knowledgeC.db from an iOS version that uses a
    different stream name for this data — see module note below).
    """
    conn, cur = _open_sqlite_or_die(path)

    try:
        cur.execute("SELECT 1 FROM ZOBJECT WHERE ZSTREAMNAME='/app/usage' LIMIT 1")
        has_usage = cur.fetchone() is not None
    except sqlite3.OperationalError:
        has_usage = False

    sessions = []
    if has_usage:
        cur.execute("""
            SELECT Z_PK, ZVALUESTRING, ZSTARTDATE, ZENDDATE, ZSECONDSFROMGMT
            FROM ZOBJECT
            WHERE ZSTREAMNAME = '/app/usage'
              AND ZSTARTDATE IS NOT NULL AND ZENDDATE IS NOT NULL
              AND ZVALUESTRING IS NOT NULL
            ORDER BY ZSTARTDATE
        """)
        for r in cur.fetchall():
            d = dict(r)
            bundle = d["ZVALUESTRING"]
            start  = unix_ts(d["ZSTARTDATE"])
            end    = unix_ts(d["ZENDDATE"])
            if start is None or end is None or end < start:
                continue   # skip malformed rows rather than silently mis-displaying them
            cls = classify_app_session(bundle)
            sessions.append({
                "zpk":            d["Z_PK"],
                "bundle_id":      bundle,
                "category":       cls["category"],
                "subcategory":    cls["subcategory"],
                "confidence":     cls["confidence"],
                "start":          start,
                "end":            end,
                "start_str":      fmt_dt(apple_ts(d["ZSTARTDATE"])),
                "end_str":        fmt_dt(apple_ts(d["ZENDDATE"])),
                "duration":       end - start,
                "tz_offset_secs": d["ZSECONDSFROMGMT"],
                # Filled in by correlate_app_sessions()
                "lat": None, "lng": None, "location_method": None,
                "location_accuracy": None, "place_id": None,
            })

    conn.close()
    return sessions



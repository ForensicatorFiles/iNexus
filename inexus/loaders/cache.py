"""Load GPS location history and stay/visit clustering from Cache.sqlite
(the required anchor source for every run)."""

from ..constants import DEFAULT_MIN_STAY_MINUTES
import sqlite3

from ..db import _open_sqlite_or_die
from ..utils import unix_ts

def load_cache(path, min_stay_minutes=DEFAULT_MIN_STAY_MINUTES):
    """
    Loads GPS pings, visits, and trip segments from a "Cache.sqlite" style
    location-history database: ZRTCLLOCATIONMO (raw pings), ZRTVISITMO
    (stationary stops, type=3 confidence=1.0), ZRTTRIPSEGMENTMO (movement
    segments). Returns (pings, visits, trips) — empty lists for any table
    that doesn't exist or has no qualifying rows in this file.
    """
    conn, cur = _open_sqlite_or_die(path)

    def _has_rows(table, where=""):
        try:
            cur.execute(f"SELECT 1 FROM {table} {where} LIMIT 1")
            return cur.fetchone() is not None
        except sqlite3.OperationalError:
            return False

    all_pings = []
    if _has_rows("ZRTCLLOCATIONMO", "WHERE ZLATITUDE IS NOT NULL"):
        cur.execute("""
            SELECT Z_PK, ZTIMESTAMP, ZLATITUDE, ZLONGITUDE, ZHORIZONTALACCURACY, ZSPEED, ZTYPE
            FROM ZRTCLLOCATIONMO
            WHERE ZLATITUDE IS NOT NULL AND ZLONGITUDE IS NOT NULL
              AND ZHORIZONTALACCURACY < 200
            ORDER BY ZTIMESTAMP
        """)
        for r in cur.fetchall():
            d = dict(r)
            all_pings.append({
                "zpk":      d["Z_PK"],
                "ts":       unix_ts(d["ZTIMESTAMP"]),
                "ts_apple": d["ZTIMESTAMP"],
                "lat":      d["ZLATITUDE"],
                "lng":      d["ZLONGITUDE"],
                "hacc":     d["ZHORIZONTALACCURACY"],
                "speed":    d["ZSPEED"],
                "type":     d["ZTYPE"],
                "source_db": "cache",
            })

    visits = []
    if _has_rows("ZRTVISITMO", "WHERE ZTYPE=3 AND ZCONFIDENCE=1.0 AND ZENTRYDATE IS NOT NULL"):
        cur.execute("""
            SELECT ZENTRYDATE, ZEXITDATE, ZLOCATIONLATITUDE, ZLOCATIONLONGITUDE,
                   ZLOCATIONUNCERTAINTY, ZCONFIDENCE, ZTYPE
            FROM ZRTVISITMO
            WHERE ZTYPE=3 AND ZCONFIDENCE=1.0 AND ZENTRYDATE IS NOT NULL
            ORDER BY ZENTRYDATE
        """)
        for r in cur.fetchall():
            d = dict(r)
            entry = unix_ts(d["ZENTRYDATE"])
            exit_ = unix_ts(d["ZEXITDATE"])
            dur   = (exit_ - entry) if (entry and exit_) else None
            if dur and dur < min_stay_minutes * 60:
                continue
            visits.append({
                "entry":         entry,
                "exit":          exit_,
                "duration":      dur,
                "lat":           d["ZLOCATIONLATITUDE"],
                "lng":           d["ZLOCATIONLONGITUDE"],
                "hacc":          d["ZLOCATIONUNCERTAINTY"],
                "conf":          d["ZCONFIDENCE"],
                "source_schema": "cache",
                "source_db":     "cache",
            })

    trips = []
    if _has_rows("ZRTTRIPSEGMENTMO", "WHERE ZSTARTDATE IS NOT NULL"):
        cur.execute("""
            SELECT ZSTARTDATE, ZENDDATE, ZMODEOFTRANSPORTATION, ZTRIPDISTANCE_M
            FROM ZRTTRIPSEGMENTMO
            WHERE ZSTARTDATE IS NOT NULL
            ORDER BY ZSTARTDATE
        """)
        for r in cur.fetchall():
            d = dict(r)
            d["source_schema"] = "cache"
            d["source_db"] = "cache"
            trips.append(d)

    conn.close()
    return all_pings, visits, trips



"""Load supplemental "learned place" location data from Cloud-V2.sqlite,
used to corroborate/enrich Cache.sqlite stays when supplied."""

from ..constants import DEFAULT_MIN_STAY_MINUTES
import sqlite3

from ..db import _open_sqlite_or_die
from ..utils import unix_ts

def load_cloud_v2(path, min_stay_minutes=DEFAULT_MIN_STAY_MINUTES):
    """
    Loads visits and trip segments from a "Cloud-V2.sqlite" style database:
    ZRTLEARNEDVISITMO (learned stationary stops) joined through
    ZRTLEARNEDPLACEMO → ZRTMAPITEMMO → ZRTADDRESSMO for human-readable place
    names and addresses, and ZRTDEVICEMO for which physical device recorded
    the visit. ZRTLEARNEDTRANSITIONMO supplies movement segments, linked
    directly to their origin/destination visit rows.

    This file format does not carry an equivalent raw-ping stream in the
    cases observed so far, so this loader returns an empty pings list —
    pings still come from load_cache() when available. Returns
    (pings, visits, trips); all empty if this file has no learned-* rows.
    """
    conn, cur = _open_sqlite_or_die(path)

    def _has_rows(table, where=""):
        try:
            cur.execute(f"SELECT 1 FROM {table} {where} LIMIT 1")
            return cur.fetchone() is not None
        except sqlite3.OperationalError:
            return False

    visits = []
    if _has_rows("ZRTLEARNEDVISITMO", "WHERE ZCONFIDENCE >= 0.5 AND ZENTRYDATE IS NOT NULL"):
        cur.execute("""
            SELECT lv.Z_PK, lv.ZENTRYDATE, lv.ZEXITDATE,
                   lv.ZLOCATIONLATITUDE, lv.ZLOCATIONLONGITUDE,
                   lv.ZLOCATIONUNCERTAINTY, lv.ZCONFIDENCE,
                   lv.ZPLACE, lv.ZDEVICE, lv.ZDATAPOINTCOUNT,
                   mi.ZNAME as place_name, mi.ZCATEGORY as place_category,
                   ad.ZTHOROUGHFARE, ad.ZSUBLOCALITY, ad.ZLOCALITY,
                   ad.ZADMINISTRATIVEAREA, ad.ZCOUNTRY,
                   dv.ZDEVICENAME, dv.ZDEVICEMODEL, dv.ZDEVICECLASS
            FROM ZRTLEARNEDVISITMO lv
            LEFT JOIN ZRTLEARNEDPLACEMO lp ON lp.Z_PK = lv.ZPLACE
            LEFT JOIN ZRTMAPITEMMO mi      ON mi.Z_PK = lp.ZMAPITEM
            LEFT JOIN ZRTADDRESSMO ad      ON ad.Z_PK = mi.ZADDRESS
            LEFT JOIN ZRTDEVICEMO dv       ON dv.Z_PK = lv.ZDEVICE
            WHERE lv.ZCONFIDENCE >= 0.5 AND lv.ZENTRYDATE IS NOT NULL
            ORDER BY lv.ZENTRYDATE
        """)
        for r in cur.fetchall():
            d = dict(r)
            entry = unix_ts(d["ZENTRYDATE"])
            exit_ = unix_ts(d["ZEXITDATE"])
            dur   = (exit_ - entry) if (entry and exit_) else None
            if dur and dur < min_stay_minutes * 60:
                continue
            address_parts = [d.get("ZTHOROUGHFARE"), d.get("ZSUBLOCALITY"),
                              d.get("ZLOCALITY"), d.get("ZADMINISTRATIVEAREA"),
                              d.get("ZCOUNTRY")]
            address = ", ".join(p for p in address_parts if p)
            device_label = d.get("ZDEVICENAME") or d.get("ZDEVICEMODEL") or d.get("ZDEVICECLASS")
            visits.append({
                "entry":            entry,
                "exit":             exit_,
                "duration":         dur,
                "lat":              d["ZLOCATIONLATITUDE"],
                "lng":              d["ZLOCATIONLONGITUDE"],
                "hacc":             d["ZLOCATIONUNCERTAINTY"],
                "conf":             d["ZCONFIDENCE"],
                "source_schema":    "cloud_v2_learned",
                "source_db":        "cloud_v2",
                "learned_zpk":      d["Z_PK"],
                "place_name":       d.get("place_name"),
                "place_category":   d.get("place_category"),
                "address":          address or None,
                "device_name":      device_label,
                "data_point_count": d.get("ZDATAPOINTCOUNT"),
            })

    trips = []
    if _has_rows("ZRTLEARNEDTRANSITIONMO", "WHERE ZSTARTDATE IS NOT NULL"):
        # ZPREDOMINANTMOTIONACTIVITYTYPE is Apple's CMMotionActivity-style
        # enum (stationary/walking/running/automotive/cycling) — decoded via
        # TRANSPORT_LABELS at render time.
        cur.execute("""
            SELECT Z_PK, ZSTARTDATE, ZSTOPDATE, ZPREDOMINANTMOTIONACTIVITYTYPE,
                   ZORIGIN, ZDESTINATION, ZDEVICE
            FROM ZRTLEARNEDTRANSITIONMO
            WHERE ZSTARTDATE IS NOT NULL
            ORDER BY ZSTARTDATE
        """)
        for r in cur.fetchall():
            d = dict(r)
            trips.append({
                "ZSTARTDATE":            d["ZSTARTDATE"],
                "ZENDDATE":              d["ZSTOPDATE"],
                "ZMODEOFTRANSPORTATION": d["ZPREDOMINANTMOTIONACTIVITYTYPE"],
                "ZTRIPDISTANCE_M":       None,   # not directly available in this schema
                "source_schema":         "cloud_v2_learned",
                "source_db":             "cloud_v2",
                "learned_zpk":           d["Z_PK"],
                "origin_visit_zpk":      d["ZORIGIN"],
                "destination_visit_zpk": d["ZDESTINATION"],
            })

    conn.close()
    return [], visits, trips



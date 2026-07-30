"""
Attempts to recover deleted location-history rows from Cache.sqlite's
freelist pages — see sqlite_forensics/ for how. Only used when the person
running the tool passes -recover-deleted; results are never merged into
the confirmed pings/places/track used elsewhere in this tool. A recovered
row means "a page that used to hold a ZRTCLLOCATIONMO row, and hasn't
been overwritten since it was deleted" — it is NOT the same evidentiary
weight as a row read straight out of the live table, and this tool never
treats it that way.
"""
from ..utils import apple_ts, unix_ts
from ._common import carve_table, is_num

_TABLE = "ZRTCLLOCATIONMO"
_REQUIRED_COLS = ("Z_PK", "ZTIMESTAMP", "ZLATITUDE", "ZLONGITUDE")


def _validate_factory(col_index):
    ts_i, lat_i, lng_i = col_index["ZTIMESTAMP"], col_index["ZLATITUDE"], col_index["ZLONGITUDE"]

    def fn(values):
        if len(values) <= max(ts_i, lat_i, lng_i):
            return False
        ts, lat, lng = values[ts_i], values[lat_i], values[lng_i]
        if not (is_num(ts) and is_num(lat) and is_num(lng)):
            return False
        # Apple-epoch seconds since 2001-01-01 — plausible range covers any
        # real device data (roughly year 2001 through 2050).
        if not (0 <= ts <= 1.6e9):
            return False
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return False
        if lat == 0 and lng == 0:
            return False  # the classic "null island" false-positive coordinate
        return True

    return fn


def recover_cache(path):
    """
    Returns a list of recovered-candidate dicts:
      rowid, page, ts (datetime), unix_ts, lat, lng, hacc, speed,
      truncated, recovered=True, confidence="carved"
    Returns [] if the file has no freelist pages, or its live schema
    doesn't look like a Cache.sqlite (missing the columns this needs).
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    hacc_i  = col_index.get("ZHORIZONTALACCURACY")
    speed_i = col_index.get("ZSPEED")

    recovered = []
    for cell in carved:
        ts_raw = cell.values[col_index["ZTIMESTAMP"]]
        recovered.append({
            "rowid":      cell.rowid,   # Z_PK is an INTEGER PRIMARY KEY = the rowid itself
            "page":       cell.page,
            "ts":         apple_ts(ts_raw),
            "unix_ts":    unix_ts(ts_raw),
            "lat":        cell.values[col_index["ZLATITUDE"]],
            "lng":        cell.values[col_index["ZLONGITUDE"]],
            "hacc":       cell.values[hacc_i] if hacc_i is not None else None,
            "speed":      cell.values[speed_i] if speed_i is not None else None,
            "truncated":  cell.truncated,
            "recovered":  True,
            "confidence": "carved",
        })
    return recovered

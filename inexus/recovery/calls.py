"""Recovers deleted call records from CallHistory.storedata's ZCALLRECORD
table via freelist carving. See recovery/cache.py's docstring for the
general caveats — the same apply here."""
from ..utils import apple_ts, unix_ts
from ._common import carve_table, is_num

_TABLE = "ZCALLRECORD"
_REQUIRED_COLS = ("Z_PK", "ZDATE", "ZDURATION", "ZADDRESS")


def _validate_factory(col_index):
    date_i, dur_i = col_index["ZDATE"], col_index["ZDURATION"]

    def fn(values):
        if len(values) <= max(date_i, dur_i):
            return False
        date, dur = values[date_i], values[dur_i]
        if not is_num(date) or not (0 <= date <= 1.6e9):
            return False
        if dur is not None and (not is_num(dur) or dur < 0):
            return False
        return True

    return fn


def recover_calls(path):
    """
    Returns a list of recovered-candidate dicts: rowid, page, ts, unix_ts,
    duration, address, name, service_provider, truncated, recovered=True,
    confidence="carved".
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    date_i = col_index["ZDATE"]
    dur_i  = col_index["ZDURATION"]
    addr_i = col_index["ZADDRESS"]
    name_i = col_index.get("ZNAME")
    svc_i  = col_index.get("ZSERVICE_PROVIDER")

    recovered = []
    for cell in carved:
        date_raw = cell.values[date_i]
        recovered.append({
            "rowid":            cell.rowid,
            "page":             cell.page,
            "ts":               apple_ts(date_raw),
            "unix_ts":          unix_ts(date_raw),
            "duration":         cell.values[dur_i],
            "address":          cell.values[addr_i],
            "name":             cell.values[name_i] if name_i is not None else None,
            "service_provider": cell.values[svc_i] if svc_i is not None else None,
            "truncated":        cell.truncated,
            "recovered":        True,
            "confidence":       "carved",
        })
    return recovered

"""Recovers deleted "learned visit" records from Cloud-V2.sqlite's
ZRTLEARNEDVISITMO table via freelist carving. See recovery/cache.py's
docstring for the general caveats — the same apply here."""
from ..utils import apple_ts, unix_ts
from ._common import carve_table, is_num

_TABLE = "ZRTLEARNEDVISITMO"
_REQUIRED_COLS = ("Z_PK", "ZENTRYDATE", "ZEXITDATE", "ZLATITUDE", "ZLONGITUDE")


def _validate_factory(col_index):
    entry_i, exit_i = col_index["ZENTRYDATE"], col_index["ZEXITDATE"]
    lat_i, lng_i = col_index["ZLATITUDE"], col_index["ZLONGITUDE"]

    def fn(values):
        if len(values) <= max(entry_i, exit_i, lat_i, lng_i):
            return False
        entry, exit_, lat, lng = values[entry_i], values[exit_i], values[lat_i], values[lng_i]
        if not (is_num(entry) and is_num(lat) and is_num(lng)):
            return False
        if not (0 <= entry <= 1.6e9):
            return False
        if exit_ is not None and (not is_num(exit_) or exit_ < entry):
            return False
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return False
        if lat == 0 and lng == 0:
            return False
        return True

    return fn


def recover_cloud_v2(path):
    """
    Returns a list of recovered-candidate dicts: rowid, page, entry, exit,
    unix_entry, unix_exit, lat, lng, truncated, recovered=True,
    confidence="carved".
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    entry_i, exit_i = col_index["ZENTRYDATE"], col_index["ZEXITDATE"]
    lat_i, lng_i = col_index["ZLATITUDE"], col_index["ZLONGITUDE"]

    recovered = []
    for cell in carved:
        entry_raw, exit_raw = cell.values[entry_i], cell.values[exit_i]
        recovered.append({
            "rowid":      cell.rowid,
            "page":       cell.page,
            "entry":      apple_ts(entry_raw),
            "exit":       apple_ts(exit_raw) if exit_raw is not None else None,
            "unix_entry": unix_ts(entry_raw),
            "unix_exit":  unix_ts(exit_raw) if exit_raw is not None else None,
            "lat":        cell.values[lat_i],
            "lng":        cell.values[lng_i],
            "truncated":  cell.truncated,
            "recovered":  True,
            "confidence": "carved",
        })
    return recovered

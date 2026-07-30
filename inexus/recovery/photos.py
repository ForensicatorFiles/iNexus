"""Recovers deleted photo/video asset records from Photos.sqlite's ZASSET
table via freelist carving. See recovery/cache.py's docstring for the
general caveats — the same apply here."""
from ..utils import apple_ts, unix_ts
from ._common import carve_table, is_num

_TABLE = "ZASSET"
_REQUIRED_COLS = ("Z_PK", "ZFILENAME", "ZDATECREATED")


def _validate_factory(col_index):
    dc_i = col_index["ZDATECREATED"]

    def fn(values):
        if len(values) <= dc_i:
            return False
        dc = values[dc_i]
        # ZDATECREATED can legitimately be NULL for some asset kinds, so
        # only reject it when present and implausible — this is a weaker
        # filter than Cache.sqlite's (no lat/lng to cross-check against
        # here), so recovered photo rows carry a correspondingly wider
        # margin for a coincidental false match.
        if dc is not None and not (is_num(dc) and 0 <= dc <= 1.6e9):
            return False
        return True

    return fn


def recover_photos(path):
    """
    Returns a list of recovered-candidate dicts: rowid, page, filename,
    directory, ts, unix_ts, lat, lng, kind, trashed, truncated,
    recovered=True, confidence="carved".
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    fn_i   = col_index["ZFILENAME"]
    dir_i  = col_index.get("ZDIRECTORY")
    dc_i   = col_index["ZDATECREATED"]
    lat_i  = col_index.get("ZLATITUDE")
    lng_i  = col_index.get("ZLONGITUDE")
    kind_i = col_index.get("ZKIND")
    trash_i = col_index.get("ZTRASHEDSTATE")

    recovered = []
    for cell in carved:
        dc_raw = cell.values[dc_i]
        recovered.append({
            "rowid":      cell.rowid,
            "page":       cell.page,
            "filename":   cell.values[fn_i],
            "directory":  cell.values[dir_i] if dir_i is not None else None,
            "ts":         apple_ts(dc_raw) if dc_raw is not None else None,
            "unix_ts":    unix_ts(dc_raw) if dc_raw is not None else None,
            "lat":        cell.values[lat_i] if lat_i is not None else None,
            "lng":        cell.values[lng_i] if lng_i is not None else None,
            "kind":       cell.values[kind_i] if kind_i is not None else None,
            "trashed":    cell.values[trash_i] if trash_i is not None else None,
            "truncated":  cell.truncated,
            "recovered":  True,
            "confidence": "carved",
        })
    return recovered

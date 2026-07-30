"""Recovers deleted cross-app interaction records from interactionC.db's
ZINTERACTIONS table via freelist carving. See recovery/cache.py's
docstring for the general caveats — the same apply here."""
from ..utils import apple_ts, unix_ts
from ._common import carve_table, is_num

_TABLE = "ZINTERACTIONS"
_REQUIRED_COLS = ("Z_PK", "ZSTARTDATE", "ZBUNDLEID")


def _validate_factory(col_index):
    start_i = col_index["ZSTARTDATE"]
    creation_i = col_index.get("ZCREATIONDATE")

    def fn(values):
        if len(values) <= start_i:
            return False
        start = values[start_i]
        creation = values[creation_i] if creation_i is not None else None
        # Either timestamp column being a plausible Apple-epoch value is
        # enough — real rows are frequently missing one or the other.
        start_ok = start is not None and is_num(start) and 0 <= start <= 1.6e9
        creation_ok = creation is not None and is_num(creation) and 0 <= creation <= 1.6e9
        return start_ok or creation_ok

    return fn


def recover_interactions(path):
    """
    Returns a list of recovered-candidate dicts: rowid, page, bundle_id,
    target_bundle_id, ts, unix_ts, direction, recipient_count,
    truncated, recovered=True, confidence="carved".
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    start_i    = col_index["ZSTARTDATE"]
    creation_i = col_index.get("ZCREATIONDATE")
    bundle_i   = col_index["ZBUNDLEID"]
    target_i   = col_index.get("ZTARGETBUNDLEID")
    dir_i      = col_index.get("ZDIRECTION")
    recip_i    = col_index.get("ZRECIPIENTCOUNT")

    recovered = []
    for cell in carved:
        start_raw = cell.values[start_i]
        creation_raw = cell.values[creation_i] if creation_i is not None else None
        ts = apple_ts(start_raw) if start_raw is not None else apple_ts(creation_raw)
        unix = unix_ts(start_raw) if start_raw is not None else unix_ts(creation_raw)
        recovered.append({
            "rowid":            cell.rowid,
            "page":             cell.page,
            "bundle_id":        cell.values[bundle_i],
            "target_bundle_id": cell.values[target_i] if target_i is not None else None,
            "ts":               ts,
            "unix_ts":          unix,
            "direction":        cell.values[dir_i] if dir_i is not None else None,
            "recipient_count":  cell.values[recip_i] if recip_i is not None else None,
            "truncated":        cell.truncated,
            "recovered":        True,
            "confidence":       "carved",
        })
    return recovered

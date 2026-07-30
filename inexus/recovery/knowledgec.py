"""Recovers deleted app-usage session records from knowledgeC.db's ZOBJECT
table via freelist carving. See recovery/cache.py's docstring for the
general caveats — the same apply here.

Note: ZOBJECT holds many different stream types (app usage, notifications,
etc.), all in the same table — ZSTREAMNAME distinguishes them on live rows,
but that column isn't part of this recovery's required-columns fingerprint
since we still want to recover rows even when ZSTREAMNAME itself decoded
to something unexpected. Every recovered row is still passed through the
same start/end-date plausibility check as a live /app/usage row would need
to pass."""
from ..utils import apple_ts, unix_ts
from ._common import carve_table, is_num

_TABLE = "ZOBJECT"
_REQUIRED_COLS = ("Z_PK", "ZVALUESTRING", "ZSTARTDATE", "ZENDDATE")


def _validate_factory(col_index):
    start_i, end_i = col_index["ZSTARTDATE"], col_index["ZENDDATE"]

    def fn(values):
        if len(values) <= max(start_i, end_i):
            return False
        start, end = values[start_i], values[end_i]
        if not is_num(start):
            return False
        if not (0 <= start <= 1.6e9):
            return False
        if end is not None and (not is_num(end) or end < start):
            return False
        return True

    return fn


def recover_knowledgec(path):
    """
    Returns a list of recovered-candidate dicts: rowid, page, bundle_id
    (ZVALUESTRING), start, end, unix_start, unix_end, truncated,
    recovered=True, confidence="carved".
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    bundle_i = col_index["ZVALUESTRING"]
    start_i, end_i = col_index["ZSTARTDATE"], col_index["ZENDDATE"]

    recovered = []
    for cell in carved:
        start_raw, end_raw = cell.values[start_i], cell.values[end_i]
        bundle = cell.values[bundle_i]
        if not isinstance(bundle, str) or not bundle:
            continue  # a real /app/usage row always has a bundle-id string here
        recovered.append({
            "rowid":      cell.rowid,
            "page":       cell.page,
            "bundle_id":  bundle,
            "start":      apple_ts(start_raw),
            "end":        apple_ts(end_raw) if end_raw is not None else None,
            "unix_start": unix_ts(start_raw),
            "unix_end":   unix_ts(end_raw) if end_raw is not None else None,
            "truncated":  cell.truncated,
            "recovered":  True,
            "confidence": "carved",
        })
    return recovered

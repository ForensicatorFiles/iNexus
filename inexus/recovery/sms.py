"""Recovers deleted messages from sms.db's `message` table via freelist
carving. See recovery/cache.py's docstring for the general caveats — the
same apply here.

Note: sms.db predates Apple's Core Data schema convention used by the
other sources (no Z-prefixed columns, and `date`/`date_read` are
nanoseconds since the Apple epoch, not seconds — see utils.unix_ts_ns).
"""
from ..utils import unix_ts_ns
from ._common import carve_table, is_num

_TABLE = "message"
_REQUIRED_COLS = ("date", "is_from_me", "text")


def _validate_factory(col_index):
    date_i = col_index["date"]

    def fn(values):
        if len(values) <= date_i:
            return False
        date = values[date_i]
        # A real message row's date is either 0 (rare, but seen on some
        # system/junk rows) or a plausible nanosecond timestamp.
        if date not in (0, None) and not (is_num(date) and 0 < date <= 1.6e18):
            return False
        return True

    return fn


def recover_sms(path):
    """
    Returns a list of recovered-candidate dicts: rowid, page, text,
    is_from_me, service, ts, unix_ts, balloon_bundle_id, truncated,
    recovered=True, confidence="carved".
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    text_i    = col_index.get("text")
    fromme_i  = col_index["is_from_me"]
    service_i = col_index.get("service")
    date_i    = col_index["date"]
    bundle_i  = col_index.get("balloon_bundle_id")

    recovered = []
    for cell in carved:
        date_raw = cell.values[date_i]
        recovered.append({
            "rowid":            cell.rowid,
            "page":             cell.page,
            "text":             cell.values[text_i] if text_i is not None else None,
            "is_from_me":       bool(cell.values[fromme_i]),
            "service":          cell.values[service_i] if service_i is not None else None,
            "ts":               unix_ts_ns(date_raw),
            "balloon_bundle_id": cell.values[bundle_i] if bundle_i is not None else None,
            "truncated":        cell.truncated,
            "recovered":        True,
            "confidence":       "carved",
        })
    return recovered

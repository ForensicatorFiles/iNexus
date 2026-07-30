"""
Shared plumbing for every recovery/*.py module. Each module supplies:
  - which table it's targeting,
  - which columns are non-negotiable (schema fingerprint check — if these
    aren't present, this database's schema doesn't match what we expect
    and we bail out rather than guess),
  - a validate_fn(col_index) -> callable(values)->bool that rejects
    decodes which don't look like a real, plausible row for that table.

See sqlite_forensics/engine.py's module docstring for why validate_fn
matters as much as it does here.
"""
import sqlite3

from ..sqlite_forensics.engine import carve_freelist_rows, live_column_order


def get_live_columns(path, table):
    """Read-only, no WAL reconciliation needed — schema lives on page 1."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cols = live_column_order(conn, table)
        conn.close()
        return cols
    except sqlite3.OperationalError:
        return []


def carve_table(path, table, required_cols, validate_fn_factory):
    """
    Returns (carved_cells, col_index) where col_index maps column name ->
    position, or ([], {}) if this database's live schema doesn't include
    every column in `required_cols` (schema fingerprint mismatch — could
    be a different iOS version, a non-Apple database, or simply the wrong
    file passed to the wrong flag).
    """
    cols = get_live_columns(path, table)
    col_index = {name: i for i, name in enumerate(cols)}
    if not cols or not all(c in col_index for c in required_cols):
        return [], {}

    validate_fn = validate_fn_factory(col_index)
    carved = carve_freelist_rows(path, expected_ncols=len(cols), validate_fn=validate_fn)
    return carved, col_index


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

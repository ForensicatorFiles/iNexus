"""Shared SQLite connection helper used by every loaders/*.py module."""
import sqlite3

from .sqlite_forensics.walcopy import prepare_readable_copy


def _open_sqlite_or_die(path):
    """
    Open a SQLite file and confirm it's actually readable, failing with a
    clean RuntimeError rather than letting a file-access problem look
    identical to "this device recorded no location history" (a real
    forensic concern — those two situations must never be indistinguishable).

    If `path` has sibling -wal/-shm files, this transparently opens a
    reconciled temp copy instead (see sqlite_forensics/walcopy.py) so any
    committed-but-not-yet-checkpointed data in the WAL is included — without
    ever writing to the original three files. Callers never need to know
    this happened; `path` in any error message below still refers to what
    the user actually passed in.
    """
    prepared = prepare_readable_copy(path)
    try:
        conn = sqlite3.connect(prepared.path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # sqlite3.connect() defers actually opening the file until first use,
        # so the real error only surfaces once a query is attempted.
        cur.execute("SELECT name FROM sqlite_master LIMIT 1")
        return conn, cur
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            f"Could not read '{path}' as a SQLite database ({e}). "
            f"Check the file path and that it isn't locked or corrupted."
        ) from e

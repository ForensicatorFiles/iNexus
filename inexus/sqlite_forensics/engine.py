"""
Top-level freelist-carving engine. This is what recovery/*.py modules call.

IMPORTANT HONESTY NOTE, read before using this anywhere near a report:
A freelist page carries no record of which table it used to belong to —
that association is gone the moment SQLite frees it. If a database has
several tables, a recovered page's bytes could theoretically have come
from any of them. In practice this is rarely ambiguous for the databases
this tool targets: each one is dominated by a single huge table (location
pings, messages, calls, ...) that owns the overwhelming majority of pages,
so decoding every freelist leaf page against that one table's column
layout is a reasonable default — but it IS a heuristic, not a certainty.
That's why every recovered row carries confidence="carved" rather than
being merged into confirmed data anywhere in this tool, and why
`validate_fn` (a plausibility check specific to the target table — e.g.
"is this a real Apple-epoch timestamp, is this latitude in [-90,90]")
matters: it's the only thing separating "this page really held this
table's data" from "this decoded as *something* by coincidence."
"""
from .header import read_header, SqliteHeaderError
from .freelist import freelist_page_numbers
from .btree import parse_leaf_page


class RecoveredRow:
    __slots__ = ("page", "rowid", "values", "truncated")

    def __init__(self, page, rowid, values, truncated):
        self.page = page
        self.rowid = rowid
        self.values = values      # list of raw decoded values, table column order
        self.truncated = truncated


def carve_freelist_rows(path, expected_ncols, validate_fn=None):
    """
    Scans every freelist LEAF page in the SQLite file at `path` for residual
    table-leaf b-tree cells, keeping only cells that:
      1. Parse as a structurally valid SQLite record (see record.py), AND
      2. Decode to exactly `expected_ncols` values (filters out pages that
         belonged to some other table with a different column count), AND
      3. Pass `validate_fn(values)` if one is given (a source-specific
         plausibility check — see the module docstring above).

    Returns a list of RecoveredRow. Returns [] (not an error) if the file
    has no freelist pages at all — the normal case for a database that's
    never had anything deleted from it, or that's been VACUUMed.

    This never opens `path` with sqlite3 and never writes to it — it's a
    read-only, raw-bytes-only pass, safe to run directly against original
    evidence.
    """
    try:
        header = read_header(path)
    except (SqliteHeaderError, OSError):
        return []

    try:
        _trunk_pages, leaf_pages = freelist_page_numbers(path, header)
    except OSError:
        return []
    if not leaf_pages:
        return []

    recovered = []
    try:
        with open(path, "rb") as f:
            for page_no in leaf_pages:
                offset = (page_no - 1) * header.page_size
                f.seek(offset)
                page_bytes = f.read(header.page_size)
                if len(page_bytes) < header.page_size:
                    continue
                for cell in parse_leaf_page(page_bytes, page_no, header.usable_page_size,
                                             header.text_encoding):
                    if len(cell.values) != expected_ncols:
                        continue
                    if validate_fn is not None and not validate_fn(cell.values):
                        continue
                    recovered.append(RecoveredRow(cell.page, cell.rowid, cell.values, cell.truncated))
    except OSError:
        return []

    return recovered


def live_column_order(conn, table_name):
    """
    Returns the column names for `table_name` in on-disk declaration order,
    via PRAGMA table_info — this is the order carve_freelist_rows() must
    map recovered values back onto, since raw record bytes carry no column
    names, only positional values.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]  # row[1] = column name

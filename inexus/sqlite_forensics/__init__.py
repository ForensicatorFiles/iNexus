"""
Low-level, raw-bytes SQLite parsing — deliberately independent of Python's
sqlite3 module, since the standard SQLite engine only ever shows live,
committed, non-deleted data. This package looks at the parts of a SQLite
file the normal engine ignores: freelist pages (freed but not yet
overwritten — often still holding a deleted row's bytes intact).

    header.py     100-byte file header (page size, freelist location)
    freelist.py   walks the freelist trunk-page chain to list leaf pages
    varint.py     SQLite's variable-length integer encoding
    record.py     decodes a record payload into column values
    btree.py      parses a raw page as a residual table-leaf b-tree page
    engine.py     ties the above together: carve_freelist_rows()

Read-only, byte-level, and safe to point directly at original evidence —
nothing in this package ever opens a file for writing.
"""

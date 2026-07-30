"""
Attempts to parse one raw page as if it were still a table b-tree LEAF
page (type byte 0x0D). This is the actual "carving": a page that's been
added to the freelist is not zeroed or restructured by SQLite — its old
table-leaf-page bytes are simply left in place until something else
happens to reuse that page number. If this page hasn't been reused yet,
it still looks exactly like a live table-leaf page and parses cleanly;
if it's been repurposed (e.g. into a freelist trunk page, or a completely
different table's data), this will fail some structural check and the
caller treats that as "nothing recoverable here."

Table b-tree leaf page format (page_size bytes; header at page-relative
offset 0 — the special +100 offset only applies to page 1, which is never
a freelist page since it always holds the schema):
    offset 0:  page type (1 byte) — must be 0x0D for a table leaf page
    offset 1:  first freeblock offset (2 bytes) — ignored here
    offset 3:  number of cells on the page (2 bytes)
    offset 5:  start of the cell content area (2 bytes; 0 means 65536)
    offset 7:  fragmented free bytes count (1 byte)
    offset 8+: `ncells` x 2-byte big-endian cell pointers (page-relative offsets)

Table leaf CELL format (at each pointer's offset):
    varint  total payload length (including any overflow)
    varint  rowid
    bytes   payload — the record itself (see record.py), or its local
            portion only if the payload overflows onto separate pages
    [4 bytes overflow-page pointer, only present if the payload overflowed]

This module only reconstructs cells whose entire payload fits locally on
the page (the overwhelming majority of small forensic records — a
location ping, a text message, a call entry). A cell that overflowed is
reported as truncated rather than guessed at, since following an overflow
chain risks stitching together bytes from an unrelated, already-reused
page and calling it recovered data — a wrong answer is worse than no
answer here.
"""
import struct

from .varint import read_varint
from .record import decode_record


class CarvedCell:
    __slots__ = ("page", "rowid", "values", "truncated")

    def __init__(self, page, rowid, values, truncated):
        self.page = page
        self.rowid = rowid
        self.values = values
        self.truncated = truncated  # True if payload overflowed and was cut short


def _table_leaf_max_local(usable_size):
    """Max payload (bytes) a table-leaf cell can store fully on-page."""
    return usable_size - 35


def parse_leaf_page(page_bytes, page_number, usable_size, text_encoding="utf-8"):
    """
    Returns a list of CarvedCell for every cell that parsed as a
    structurally valid record. Returns [] (not an error) if this page
    doesn't look like a table-leaf page at all, or its structure doesn't
    check out — that's the expected, common case for a freelist page
    that's already been reused for something else.
    """
    if len(page_bytes) < 8 or page_bytes[0] != 0x0D:
        return []

    ncells, = struct.unpack(">H", page_bytes[3:5])
    content_start, = struct.unpack(">H", page_bytes[5:7])
    if content_start == 0:
        content_start = 65536
    if ncells == 0 or ncells > (usable_size - 8) // 2:
        return []  # implausible cell count for this page size — not a real leaf page

    ptr_array_start = 8
    ptr_array_end = ptr_array_start + ncells * 2
    if ptr_array_end > len(page_bytes):
        return []

    results = []
    max_local = _table_leaf_max_local(usable_size)
    for i in range(ncells):
        off = ptr_array_start + i * 2
        cell_offset, = struct.unpack(">H", page_bytes[off:off + 2])
        if cell_offset == 0 or cell_offset >= len(page_bytes):
            return []  # a single bad pointer means this isn't really a leaf page
        try:
            payload_len, pos = read_varint(page_bytes, cell_offset)
            rowid, pos = read_varint(page_bytes, pos)
        except ValueError:
            return []

        truncated = False
        if payload_len <= max_local:
            local_len = payload_len
        else:
            # Overflows onto separate page(s) — read only what's local and
            # flag it, rather than chase the overflow chain (see docstring).
            local_len = _table_leaf_max_local(usable_size)  # conservative local portion
            truncated = True

        payload = page_bytes[pos:pos + local_len]
        if len(payload) < local_len:
            # Page ended before the declared payload did — corrupt/reused page.
            continue

        try:
            values = decode_record(payload, text_encoding)
        except (ValueError, IndexError):
            continue  # this cell's bytes don't decode as a real record — skip it, don't guess

        results.append(CarvedCell(page_number, rowid, values, truncated))

    return results

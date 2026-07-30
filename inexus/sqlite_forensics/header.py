"""
Parses the 100-byte SQLite database file header. See the file format spec:
https://www.sqlite.org/fileformat2.html#the_database_header

This reads raw bytes directly — it does NOT use the sqlite3 module, since
the whole point of this package is to see structure (freelist pages,
unallocated space) that the normal SQLite engine deliberately hides from
any ordinary SELECT query.
"""
import struct


class SqliteHeaderError(ValueError):
    """Raised when a file doesn't look like a SQLite database at all."""


class SqliteHeader:
    __slots__ = ("page_size", "reserved_space", "freelist_trunk_page",
                 "freelist_page_count", "db_size_pages", "text_encoding")

    def __init__(self, raw100):
        if len(raw100) < 100 or raw100[:16] != b"SQLite format 3\x00":
            raise SqliteHeaderError("not a SQLite database (bad magic header)")

        page_size, = struct.unpack(">H", raw100[16:18])
        # Special case per spec: 1 means the actual page size is 65536,
        # since a 2-byte big-endian field can't represent that value directly.
        self.page_size = 65536 if page_size == 1 else page_size
        if self.page_size < 512 or (self.page_size & (self.page_size - 1)) != 0:
            raise SqliteHeaderError(f"implausible page size {self.page_size}")

        self.reserved_space = raw100[20]
        self.db_size_pages, = struct.unpack(">I", raw100[28:32])
        self.freelist_trunk_page, = struct.unpack(">I", raw100[32:36])
        self.freelist_page_count, = struct.unpack(">I", raw100[36:40])
        encoding, = struct.unpack(">I", raw100[56:60])
        self.text_encoding = {1: "utf-8", 2: "utf-16-le", 3: "utf-16-be"}.get(encoding, "utf-8")

    @property
    def usable_page_size(self):
        """Page size minus the reserved-space-per-page tail (usually 0)."""
        return self.page_size - self.reserved_space


def read_header(path):
    with open(path, "rb") as f:
        raw = f.read(100)
    return SqliteHeader(raw)

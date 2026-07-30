"""
Walks the SQLite freelist: the linked list of pages SQLite has marked as
no longer part of any table/index but hasn't overwritten yet. This is
where deleted rows live on, sometimes for a very long time, since SQLite
(with the default auto_vacuum=NONE) never bothers to zero a freed page —
it just adds the page number to this list and moves on.

Freelist trunk page format (page_size bytes, no relation to its former
content — trunk pages ARE overwritten with this structure):
    offset 0:  page number of the next trunk page (4 bytes, 0 = last one)
    offset 4:  number of leaf-page pointers on this trunk page (4 bytes)
    offset 8+: that many 4-byte freelist LEAF page numbers

Freelist LEAF pages have no structure of their own — they're just raw
bytes on the freelist, meaning whatever they held right up until the
moment they were freed is typically still sitting there completely
intact. That's the entire premise of this module: enumerate every leaf
page number, and btree.py then tries to parse each one as a residual
table-leaf b-tree page.
"""
import struct


def freelist_page_numbers(path, header):
    """
    Returns (trunk_pages, leaf_pages) — two lists of 1-indexed page numbers.
    trunk_pages are overwritten with the trunk-page structure above (not
    useful for row recovery). leaf_pages are the ones worth carving.
    """
    trunk_pages = []
    leaf_pages = []
    if header.freelist_trunk_page == 0 or header.freelist_page_count == 0:
        return trunk_pages, leaf_pages

    with open(path, "rb") as f:
        next_trunk = header.freelist_trunk_page
        seen = set()  # guards against a corrupt/cyclic chain hanging this loop
        while next_trunk != 0 and next_trunk not in seen:
            seen.add(next_trunk)
            trunk_pages.append(next_trunk)
            offset = (next_trunk - 1) * header.page_size
            f.seek(offset)
            trunk_data = f.read(header.page_size)
            if len(trunk_data) < 8:
                break
            next_trunk, n_leaves = struct.unpack(">II", trunk_data[0:8])
            max_leaves = (header.page_size - 8) // 4
            n_leaves = min(n_leaves, max_leaves)  # guard against corrupt counts
            for i in range(n_leaves):
                off = 8 + i * 4
                pg, = struct.unpack(">I", trunk_data[off:off + 4])
                if pg:
                    leaf_pages.append(pg)

    return trunk_pages, leaf_pages

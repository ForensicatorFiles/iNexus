"""Recovers deleted contact records from AddressBook.sqlitedb's ABPerson
table via freelist carving. See recovery/cache.py's docstring for the
general caveats — the same apply here.

Unlike the other sources, this isn't reconstructing timeline events — a
recovered contact just tells you a name that used to be associated with
this device's address book, which can still matter (e.g. explaining who a
resolved phone number used to belong to before the contact was deleted).
"""
from ._common import carve_table

_TABLE = "ABPerson"
_REQUIRED_COLS = ("First", "Last", "DisplayName", "Organization")


def _validate_factory(col_index):
    first_i, last_i, disp_i = col_index["First"], col_index["Last"], col_index["DisplayName"]

    def fn(values):
        if len(values) <= max(first_i, last_i, disp_i):
            return False
        first, last, disp = values[first_i], values[last_i], values[disp_i]
        # A real contact has at least one of these three actually be text —
        # an all-NULL/all-numeric decode here is almost certainly a
        # coincidental match on some other table's freed page.
        return any(isinstance(v, str) and v.strip() for v in (first, last, disp))

    return fn


def recover_addressbook(path):
    """
    Returns a list of recovered-candidate dicts: rowid, page, first, last,
    display_name, organization, truncated, recovered=True,
    confidence="carved".
    """
    carved, col_index = carve_table(path, _TABLE, _REQUIRED_COLS, _validate_factory)
    if not carved:
        return []

    first_i, last_i = col_index["First"], col_index["Last"]
    disp_i, org_i = col_index["DisplayName"], col_index["Organization"]

    recovered = []
    for cell in carved:
        recovered.append({
            "rowid":        cell.rowid,
            "page":         cell.page,
            "first":        cell.values[first_i],
            "last":         cell.values[last_i],
            "display_name": cell.values[disp_i],
            "organization": cell.values[org_i],
            "truncated":    cell.truncated,
            "recovered":    True,
            "confidence":   "carved",
        })
    return recovered

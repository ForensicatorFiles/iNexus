"""Load and resolve contact records from AddressBook.sqlitedb."""

import sqlite3

from ..db import _open_sqlite_or_die
from ..utils import normalize_phone

def load_addressbook(path):
    """
    Loads phone-number and email contact entries from an iOS
    AddressBook.sqlitedb, returning a dict mapping normalize_phone(number)
    or lowercased email → display name.

    Schema notes:
      - ABMultiValue.property 3 = phone, 4 = email (confirmed against
        ABMultiValueLabel in sample data — property 3 rows carry
        Home/Mobile/Main/Work labels, property 4 rows carry email
        addresses directly). Other property codes (URLs, IM handles,
        encrypted blob fields) are ignored here.
      - Display name is DisplayName if iOS populated it, else "First Last"
        (whichever parts exist), else Organization, else falls back to
        showing nothing useful — such a record is skipped rather than
        injecting an empty string as someone's "name".
      - The same person can have multiple ABPerson rows (e.g. a manually
        re-added contact) and the same number can appear under more than
        one row. First match wins; this is a display convenience for a
        report, not a forensic identity merge — the raw number is always
        preserved alongside the resolved name everywhere this is used, so
        nothing is hidden by the resolution.

    Returns an empty dict (not an error) if the file opens but has no
    matching rows.
    """
    conn, cur = _open_sqlite_or_die(path)

    try:
        cur.execute("SELECT 1 FROM ABPerson LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        raise RuntimeError(
            f"{path} doesn't look like an iOS AddressBook.sqlitedb — no "
            f"'ABPerson' table found. Confirm this is the Contacts database."
        )

    names = {}
    for row in cur.execute("SELECT ROWID, First, Last, DisplayName, Organization FROM ABPerson"):
        name = row["DisplayName"] or " ".join(p for p in (row["First"], row["Last"]) if p) or row["Organization"]
        if name:
            names[row["ROWID"]] = name.strip()

    contacts = {}
    for row in cur.execute("SELECT record_id, property, value FROM ABMultiValue WHERE property IN (3, 4)"):
        name = names.get(row["record_id"])
        if not name or not row["value"]:
            continue
        if row["property"] == 3:
            key = normalize_phone(row["value"])
        else:
            key = row["value"].strip().lower()
        if key and key not in contacts:
            contacts[key] = name

    conn.close()
    return contacts



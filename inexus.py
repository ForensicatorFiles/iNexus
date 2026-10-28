#!/usr/bin/env python3
"""
iNexus (v1.1.0) — thin backward-compatible entry point.

Launch without arguments to start the interactive desktop GUI:
    python3 inexus.py

Alternatively, keep a plain `python3 inexus.py ...` invocation style working 
against the package. Prefer `python3 -m inexus ...` for CLI usage. All flags,
behavior, and output are identical either way — this file only forwards to
inexus.cli.main().

FULL CLI EXAMPLE — every optional source supplied at once:

    python3 inexus.py \
        -cache        Cache.sqlite \
        -local        Local.sqlite \
        -cloud        Cloud-V2.sqlite \
        -photos       Photos.sqlite \
        -thumbnails   path/to/Thumbnails/V2 \
        -knowledgec   knowledgeC.db \
        -sms          sms.db \
        -calls        CallHistory.storedata \
        -addressbook  AddressBook.sqlitedb \
        -interactions interactionC.db \
        -output       report.html \
        -case         2026-001 \
        -examiner     "J. Smith" \
        -notes        "Full extraction, all sources" \
        -radius 150 -visit 4 -window 120 -reject 500 -minstay 3 \
        -convert-heic -dcim DCIM -jpeg-quality 85 \
        -recover-deleted

Run with -h for the full flag reference. See CHANGELOG.md for version history
and README.md for the package layout.
"""
from inexus.cli import main

if __name__ == "__main__":
    main()

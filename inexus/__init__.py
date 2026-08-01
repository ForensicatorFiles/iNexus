"""
iNexus  (v1.0.1)
Correlates iOS location artifacts (Cache.sqlite location history, plus
optional Cloud-V2.sqlite, knowledgeC.db app usage, sms.db, CallHistory.storedata,
interactionC.db, AddressBook.sqlitedb, and Photos.sqlite media) into a
self-contained HTML report with an interactive map, timeline of
stays/movements, and per-photo location inference.

Includes SHA-256 chain-of-custody hashing of every source database supplied
and full disclosure of every tunable analysis parameter, shown in the
report's "Integrity & Parameters" panel.

Usage:
    python3 -m inexus -cache Cache.sqlite -output report.html
    python3 -m inexus -cache Cache.sqlite -radius 100 -visit 2
    python3 -m inexus -cache Cache.sqlite -case "2024-001" -examiner "J. Smith"

Full example — every optional source supplied at once:
    python3 -m inexus \\
        -cache        Cache.sqlite \\
        -photos       Photos.sqlite \\
        -cloud        Cloud-V2.sqlite \\
        -knowledgec   knowledgeC.db \\
        -sms          sms.db \\
        -calls        CallHistory.storedata \\
        -addressbook  AddressBook.sqlitedb \\
        -interactions interactionC.db \\
        -output       report.html \\
        -case         2024-001 \\
        -examiner     "J. Smith" \\
        -notes        "Full extraction, all sources" \\
        -radius 150 -visit 4 -window 120 -reject 500 -minstay 3 \\
        -convert-heic -dcim DCIM -jpeg-quality 85 \\
        -recover-deleted

Run with -h for the full flag reference (-radius, -visit, -window, -reject,
-minstay, -case, -examiner, -notes, -convert-heic, -dcim, -jpeg-quality,
-recover-deleted, and one path flag per source above). Any flag not
supplied keeps this tool's built-in default — defaults are always shown
in the generated report regardless of whether they were overridden. See
CHANGELOG.md for version history.

Package layout:
    constants.py        tool identity + tunable analysis defaults
    utils.py             generic helpers: HTML escaping, hashing, timestamps, geo math
    db.py                shared SQLite-open helper
    media.py             HEIC -> JPEG batch conversion for -convert-heic
    classification.py    shared app bundle-ID category taxonomy
    analysis.py          cross-source correlation, clustering, interpolation
    loaders/             one module per forensic source (photos, cache,
                          cloud_v2, knowledgec, sms, calls, interactions,
                          addressbook)
    report/              HTML report assembly (styles, scripts, body,
                          integrity panel, place cards, builder)
    cli.py               argument parsing + the run pipeline (main())
"""
from .constants import TOOL_NAME, TOOL_VERSION
from .report.builder import build_html
from .cli import main, parse_args

__all__ = ["TOOL_NAME", "TOOL_VERSION", "build_html", "main", "parse_args"]

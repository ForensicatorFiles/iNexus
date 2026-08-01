# iNexus

```
=============================================
    _  _   _
   (_)| \ | |  ___  __  __ _  _  ___
   | ||  \| | / _ \ \ \/ /| || |/ __|
   | || |\  ||  __/  >  < | |_| |\__ \
   |_||_| \_| \___| /_/\_\ \__,_||___/
---------------------------------------------
iOS Forensic Artifact & Location Correlator
                v1.0.0
=============================================
```

TAGLINE = "iOS Forensic Artifact & Location Correlator"

**One report, every location artifact.** iNexus correlates iOS location history (`Cache.sqlite`) with photos, app usage, messages, calls, contacts, and cross-app interactions into a single self-contained HTML forensic report — with an interactive map, timeline, and optional recovery of deleted rows straight from SQLite's freelist pages.

Formerly *iOS Location Correlator*. See [`CHANGELOG.md`](CHANGELOG.md) for full version history, including the feature set carried over from that name.

---

## What it does

`Cache.sqlite` is the primary, recommended source (it's the one with a raw GPS ping track, and it drives automatic place/stay detection) — but it's not required. Every other source is optional and additive:

| Flag | Source | Adds |
|---|---|---|
| `-cache` | `Cache.sqlite` | Location history + GPS track (recommended anchor) |
| `-photos` | `Photos.sqlite` | Photo/video assets with thumbnails |
| `-cloud` | `Cloud-V2.sqlite` | Supplemental learned places/visits |
| `-knowledgec` | `knowledgeC.db` | App foreground/background usage sessions |
| `-sms` | `sms.db` | Messages (iMessage/SMS), including tapbacks |
| `-calls` | `CallHistory.storedata` | Phone/FaceTime/VoIP calls |
| `-interactions` | `interactionC.db` | Cross-app interaction log (Siri donations) |
| `-addressbook` | `AddressBook.sqlitedb` | Contact-name resolution for the three above |

Supply more sources, get more report tabs and more per-stay detail. Supply none but `-cache`, still get a full map + timeline. Supply nothing at all and it still runs — see [Reduced-functionality mode](#reduced-functionality-mode).

Every source file is SHA-256 hashed, and every tunable analysis parameter (clustering radius, GPS interpolation window, etc.) is disclosed in the report's own **Integrity & Parameters** panel — nothing is silently defaulted behind your back.

## Quick start

```bash
python3 -m inexus -cache Cache.sqlite -output report.html
```

Or, without installing as a module:

```bash
python3 inexus.py -cache Cache.sqlite -output report.html
```

### Full example — every optional source at once

```bash
python3 -m inexus \
    -cache        Cache.sqlite \
    -photos       Photos.sqlite \
    -cloud        Cloud-V2.sqlite \
    -knowledgec   knowledgeC.db \
    -sms          sms.db \
    -calls        CallHistory.storedata \
    -addressbook  AddressBook.sqlitedb \
    -interactions interactionC.db \
    -output       report.html \
    -case         2024-001 \
    -examiner     "J. Smith" \
    -notes        "Full extraction, all sources" \
    -radius 150 -visit 4 -window 120 -reject 500 -minstay 3 \
    -convert-heic -dcim DCIM -jpeg-quality 85 \
    -recover-deleted
```

Run `-h` for the full flag reference — every tunable documents its default and what it controls.

## Reduced-functionality mode

Running with no `-cache` (and no `-cloud` either) still produces a report, but with an explicit console notice explaining what's unavailable: no GPS ping track, no automatic place/stay detection, no interpolation fallback for photos without their own EXIF GPS, and app sessions/messages/calls/interactions shown as unlocated. Supply `-cloud` on its own and place/stay detection still works from its learned visits.

## Recovering deleted rows, and WAL/SHM files

Every source transparently picks up sibling `-wal`/`-shm` files if present (standard SQLite naming) — committed-but-not-yet-checkpointed data is included automatically via a temporary working copy, and the original files are **never** opened for writing.

Add `-recover-deleted` to also scan every supplied source's SQLite freelist pages — pages SQLite has freed but not yet overwritten, which often still hold an entire deleted row's bytes intact — for recoverable data. This is a real byte-level SQLite parser built for this project (`inexus/sqlite_forensics/`), not a wrapper around another tool. Recovered rows:

- Appear in a separate **RECOVERED DATA** report tab, with sortable columns and independent CSV/standalone-HTML export — never merged into the confirmed Map/Places/Timeline/etc. views, and never counted in any statistic shown elsewhere.
- Can optionally appear on the **Map** tab as their own toggleable layer ("Recovered points (unverified)") — off by default, visually distinct (dashed yellow markers), and excluded from the map's auto-fit-bounds so they can never silently skew the initial view.

This is necessarily partial recovery, not a guaranteed complete undelete — only pages that happened to survive intact on the freelist are recoverable.

## Output

A single self-contained HTML file. No external assets, no server, no internet connection required to view it — copy it, hash it, hand it off.

## Package layout

```
inexus/
├── constants.py        Tool identity + tunable analysis defaults
├── utils.py             Generic helpers: HTML escaping, hashing, timestamps, geo math
├── db.py                Shared SQLite-open helper
├── media.py             HEIC → JPEG batch conversion for -convert-heic
├── classification.py    Shared app bundle-ID category taxonomy
├── analysis.py          Cross-source correlation, clustering, interpolation
├── loaders/             One module per forensic source (photos, cache,
│                         cloud_v2, knowledgec, sms, calls, interactions,
│                         addressbook)
├── report/              HTML report assembly (styles, scripts, body,
│                         integrity panel, place cards, recovered-data view,
│                         builder)
├── sqlite_forensics/     Byte-level SQLite parsing (freelist walking, record
│                         decoding, WAL/SHM reconciliation) — independent of
│                         Python's sqlite3 module, which only shows live data
├── recovery/             One module per source calling sqlite_forensics to
│                         recover deleted rows (-recover-deleted)
├── cli.py                Argument parsing + the run pipeline (main())
├── __init__.py           Package docstring + public API
└── __main__.py           Lets you run `python3 -m inexus`
inexus.py                  Thin standalone entry point (same as -m inexus)
```

## Requirements

Python 3.9+, standard library only. `pillow-heif` is an optional extra, needed only if you use `-convert-heic`.

## Extending it

- **New artifact source**: write a `load_<source>(path, ...)` in `loaders/`, wire it into `cli.py`'s `main()`, and add a tab in `report/body.py`. See `loaders/interactions.py` as the simplest template.
- **New report tab/view**: the markup lives in `report/body.py`, rendering logic in `report/scripts.py`, JSON payload construction in `report/builder.py`.

## License

MIT License

Copyright (c) 2026 Forensicator Files

## Disclaimer

⚠️ Disclaimer: This tool is provided as-is, for educational and lawful forensic use, with no warranty of accuracy or fitness for purpose. Always independently verify results against source data before relying on them for investigative or legal purposes. Not legal advice. Use at your own risk.

[![BuyMeACoffee](https://raw.githubusercontent.com/pachadotdev/buymeacoffee-badges/main/bmc-black.svg)](https://www.buymeacoffee.com/forensicatorfiles)


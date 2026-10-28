# iNexus

```text
=============================================
    _  _   _
   (_)| \ | |  ___  __  __ _  _  ___
   | ||  \| | / _ \ \ \/ /| || |/ __|
   | || |\  ||  __/  >  < | |_| |\__ \
   |_||_| \_| \___| /_/\_\ \__,_||___/
---------------------------------------------
iOS Forensic Artifact & Location Correlator
                v1.1.0
=============================================
```

**One report, every location artifact.** iNexus correlates iOS location history (`Cache.sqlite`, `Local.sqlite`, `Cloud-V2.sqlite`) with photos, app usage, messages, calls, contacts, and cross-app interactions into a single self-contained HTML forensic report — complete with an interactive map, a split-view chronological timeline, and deleted row recovery straight from SQLite's freelist pages.

Formerly *iOS Location Correlator*. See [`CHANGELOG.md`](CHANGELOG.md) for full version history.

---

## 🚀 What's New
* **Interactive Desktop GUI:** Launch iNexus without command-line arguments to open a dark-themed Tkinter interface. Features a **1-Click Auto-Scan** that automatically recursively finds and loads all supported iOS databases from a raw extraction folder.
* **Local.sqlite Support:** Parses long-term Significant Locations and Learned Visits to provide historical location data months after `Cache.sqlite` has rolled over.
* **Deleted Photo Recovery (V2 Thumbnails):** Point iNexus at a `PhotoData/Thumbnails/V2` folder. It will intelligently isolate orphaned thumbnails for deleted images, extract them as Base64 Data URIs, and render them seamlessly inside the report as a fallback for missing media.
* **CARTO Map Tiles:** Support for `carto_key.txt` to seamlessly render high-quality interactive map backgrounds.

---

## What it does

Every source is optional and additive. The more you supply, the richer the correlation and per-stay detail.

| Flag / GUI Input | Source | Adds |
|---|---|---|
| `-cache` | `Cache.sqlite` | Location history + GPS track (high-frequency, short retention) |
| `-local` | `Local.sqlite` | Significant Locations / Learned Visits (long-term retention) |
| `-cloud` | `Cloud-V2.sqlite` | Supplemental iCloud synced places/visits |
| `-photos` | `Photos.sqlite` | Photo/video assets with metadata and previews |
| `-thumbnails` | `Thumbnails/V2/` | Recovers cached visual thumbnails for deleted/unindexed media |
| `-knowledgec` | `knowledgeC.db` | App foreground/background usage sessions |
| `-sms` | `sms.db` | Messages (iMessage/SMS), including tapbacks & attachments |
| `-calls` | `CallHistory.storedata` | Phone/FaceTime/VoIP calls |
| `-interactions` | `interactionC.db` | Cross-app interaction log (Siri donations) |
| `-addressbook` | `AddressBook.sqlitedb` | Contact-name resolution for the three communication DBs above |
| `-carto-key` | `carto_key.txt` | API key for map tile rendering (can also be saved in root folder) |

Every source file is SHA-256 hashed, and every tunable analysis parameter (clustering radius, GPS interpolation window, etc.) is disclosed in the report's **Integrity & Parameters** panel — nothing is silently defaulted behind your back.

## Quick start

### Launch the Interactive GUI
Simply run the script with no arguments (or use `-gui`). Use the **Auto-Scan Extraction Folder** button to automatically populate all paths.
```bash
python3 inexus.py
```

### Command-Line Interface
```bash
python3 -m inexus -cache Cache.sqlite -output report.html
```

**Full CLI Example — every optional source at once:**
```bash
python3 -m inexus \
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
```

Run `-h` for the full flag reference.

## Recovering deleted rows, and WAL/SHM files

Every source transparently picks up sibling `-wal`/`-shm` files if present (standard SQLite naming) — committed-but-not-yet-checkpointed data is included automatically via a temporary working copy, and the original files are **never** opened for writing.

Add `-recover-deleted` to also scan every supplied source's SQLite freelist pages — pages SQLite has freed but not yet overwritten, which often still hold an entire deleted row's bytes intact — for recoverable data. This is a real byte-level SQLite parser built for this project (`inexus/sqlite_forensics/`), not a wrapper around another tool. Recovered rows:

- Appear in a separate **RECOVERED DATA** report tab, with sortable columns and independent CSV/standalone-HTML export — never merged into the confirmed Map/Places/Timeline/etc. views, and never counted in any statistic shown elsewhere.
- Can optionally appear on the **Map** tab as their own toggleable layer ("Recovered points (unverified)") — off by default, visually distinct (dashed yellow markers), and excluded from the map's auto-fit-bounds.

## Output

A single self-contained HTML file. No external assets, no server, no internet connection required to view it — copy it, hash it, hand it off. Base64 thumbnail data is embedded directly into the payload.

## Package layout

```text
inexus/
├── gui.py               Tkinter desktop interface & extraction auto-scanner
├── constants.py         Tool identity + tunable analysis defaults
├── utils.py             Generic helpers: HTML escaping, hashing, timestamps, geo math
├── db.py                Shared SQLite-open helper
├── media.py             HEIC → JPEG batch conversion for -convert-heic
├── classification.py    Shared app bundle-ID category taxonomy
├── analysis.py          Cross-source correlation, clustering, interpolation
├── loaders/             One module per forensic source (photos, cache, local_db,
│                         cloud_v2, knowledgec, sms, calls, interactions,
│                         addressbook)
├── report/              HTML report assembly (styles, scripts, body,
│                         integrity panel, place cards, recovered-data view,
│                         builder, data_injection)
├── sqlite_forensics/    Byte-level SQLite parsing (freelist walking, record
│                         decoding, WAL/SHM reconciliation)
├── recovery/            One module per source calling sqlite_forensics to
│                         recover deleted rows (-recover-deleted)
├── cli.py               Argument parsing + the run pipeline (main())
├── __init__.py          Package docstring + public API
└── __main__.py          Lets you run `python3 -m inexus`
inexus.py                Thin standalone entry point (same as -m inexus)
carto_key.txt            (Optional) Drop your CARTO API key here for map rendering
```

## Requirements

Python 3.9+, standard library only. `pillow-heif` is an optional extra, needed only if you use `-convert-heic`.

## License

MIT License

Copyright (c) 2026 Forensicator Files

## Disclaimer

⚠️ Disclaimer: This tool is provided as-is, for educational and lawful forensic use, with no warranty of accuracy or fitness for purpose. Always independently verify results against source data before relying on them for investigative or legal purposes. Not legal advice. Use at your own risk.

[![BuyMeACoffee](https://raw.githubusercontent.com/pachadotdev/buymeacoffee-badges/main/bmc-black.svg)](https://www.buymeacoffee.com/forensicatorfiles)

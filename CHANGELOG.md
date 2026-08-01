# Changelog

All notable changes to iNexus (formerly "iOS Location Correlator") are
documented here.

## 1.0.1

Added a plain-ASCII banner, shown on `-h` and `-version`:

```
 _  _   _
(_)| \ | |  ___  __  __ _  _  ___
| ||  \| | / _ \ \ \/ /| || |/ __|
| || |\  ||  __/  >  < | |_| |\__ \
|_||_| \_| \___| /_/\_\ \__,_||___/
iOS Forensic Artifact & Location Correlator
               v1.0.1
```

Built in a new `banner.py` module using nothing but the standard library —
a raw triple-quoted string plus `str.center()`, no `figlet`/`pyfiglet`/
`rich`/`colorama` or any other dependency, and no ANSI color codes — so it
renders identically on any terminal this tool might run in, including
older or restricted ones and Windows' default console codepage. `-h`'s
existing detailed description/epilog/full-example text is unchanged below
it. `-version` keeps its original immediate-exit behavior (via a small
custom `argparse.Action`), just with the banner printed first. Ordinary
report-generation runs are unaffected — `main()`'s existing plain
`TOOL_NAME vX.Y.Z` startup line is unchanged, so scripted/automated
invocations see no new output.

## 1.0.0 — Rebranded to iNexus

Renamed from "iOS Location Correlator" to **iNexus**, and the version
counter reset to mark this as the first public release under the new
name. This is a rename only — no functional change from iOS Location
Correlator v1.3.0. Verified by diffing generated report output
byte-for-byte before and after the rename: the only differences are the
tool-name string and version number everywhere they appear (report title,
header, footer, `REPORT_META`, the standalone Recovered Data export, and
the `-h`/`-version` CLI output).

Everything below this point is the feature history carried over from the
prior name — included here for continuity, not as iNexus's own version
sequence (iNexus starts fresh at 1.0.0 above).

### Legacy history, as iOS Location Correlator

#### 1.3.0

Recovered points from `-recover-deleted` that carry coordinates (Cache.sqlite,
Cloud-V2.sqlite, and Photos.sqlite are the recovery sources that can) now
optionally appear on the **Map** tab as their own layer, alongside GPS
track / Stays / Photo locations in the same layer-toggle panel:

- **"Recovered points (unverified)"** checkbox, toggled exactly like the
  existing layers (`toggleLayer('recovered')`) — but **off by default**,
  unlike the confirmed-data layers, since this is unverified data and
  shouldn't appear on first load without the person asking for it.
- Visually distinct from confirmed data: dashed yellow circle markers
  rather than the solid colors used for GPS pings/photos, and each
  marker's popup repeats the same "UNVERIFIED — RECOVERED" warning and
  page/rowid provenance shown on the RECOVERED DATA tab.
- Deliberately **excluded** from the map's auto-fit-bounds calculation —

  a single stale or slightly-off recovered coordinate can never silently
  pan/zoom the map away from where the confirmed data actually is.
- The checkbox itself only renders when at least one recovered row
  actually has coordinates — running `-recover-deleted` against sources
  with no coordinate-bearing recoveries (e.g. only sms.db/CallHistory
  data recovered) doesn't add a dead/empty toggle to the panel.

Verified with a real headless-browser test (`jsdom`, not just a syntax
check): loaded an actual generated report, ran its real `initMap()` and
`toggleLayer()` functions, and confirmed the layer is built with the
correct marker count and coordinates, defaults to off, and correctly
toggles on/off — while the pre-existing GPS track layer's default-on
behavior stays unaffected.

#### 1.2.1

**Fixed:** "Export CSV" on the RECOVERED DATA tab only showed the ROWID
column when opened in a spreadsheet app (Excel, Google Sheets, Numbers).

Cause: the export combined every source into one file, with a non-tabular
`=== label ===` divider line at the top of each section. Spreadsheet apps
sniff a CSV's column count/delimiter from the file's *first* line — a
divider line with zero commas made the entire import collapse to one
unsplit text column, hiding every field past the first.

Fix: exports one clean CSV file per source instead (`recovered_cache.csv`,
`recovered_knowledgec.csv`, etc.), each with a consistent column count on
every row and no divider lines. Verified this time with `jsdom` (a real
simulated browser DOM, actually running the exported report's JS end to
end) piped through Python's `csv` module to confirm every row parses to
the same column count — not just inspected as raw text, which is what let
the original bug ship.

#### 1.2.0

The **RECOVERED DATA** tab (`-recover-deleted`) gained two usability
features on top of 1.1.0's recovery engine itself:

- **Click-to-sort columns.** Every column header sorts its table ascending,
  then descending, then back, on repeated clicks — numeric columns (rowid,
  page, lat/lng, duration, ...) sort numerically, timestamp columns sort
  chronologically, everything else sorts as text. Rows missing a value for
  the sorted column always sort to the bottom regardless of direction.
- **Export, independent of the rest of the report.** Two buttons sit above
  the tables: "Export CSV" (one labeled section per source, since each
  source has a different column layout) and "Export Standalone HTML" (a
  self-contained copy of just the Recovered Data tab — same dark styling,
  copied live from the report's own `<style>` block so there's nothing to
  keep in sync — that opens and reads fine on its own, separate from the
  full multi-tab report).

Verified with `node --check` against both the isolated script module and
the actual `<script>` block of a generated report, plus a runtime
smoke-test of the CSV-escaping logic in Node — not just a Python-side
syntax check, since this is JS embedded in a Python string and needs its
own validation pass.

#### 1.1.0

**New: deleted-row recovery (`-recover-deleted`).** After normally loading
each supplied source, this optionally scans that same file's SQLite
freelist pages — pages SQLite has freed but not yet overwritten, which
often still hold an entire deleted row's bytes intact — for recoverable
data. This is a genuine byte-level SQLite parser built from scratch for
this tool (`sqlite_forensics/`: file header, freelist trunk/leaf-page
walking, varint decoding, record/serial-type decoding, table-leaf b-tree
page reconstruction), not a wrapper around a third-party library.

- One recovery module per source (`recovery/cache.py`, `photos.py`,
  `cloud_v2.py`, `knowledgec.py`, `sms.py`, `calls.py`, `addressbook.py`,
  `interactions.py`), each deriving the target table's column layout from
  the database's own live schema (`PRAGMA table_info`) rather than a
  hardcoded assumption, and each applying a plausibility check specific to
  that table (timestamp range, lat/lng bounds, etc.) before accepting a
  decoded row as a real candidate.
- Recovered rows appear in a new **RECOVERED DATA** report tab — never
  merged into the Map/Places/Timeline/Photos/App Usage/Messages/Calls/
  Interactions views, and never counted in any statistic shown elsewhere.
  Every row is labeled with its source page number and whether its payload
  was truncated (overflowed onto pages this tool didn't attempt to
  reassemble).
- Verified against a real deleted-row scenario (rows deleted from a test
  Cache.sqlite, freelist pages confirmed via `PRAGMA freelist_count`,
  recovered output compared field-by-field against the actual deleted
  values — zero incorrect values recovered). This is necessarily partial
  recovery, not a guaranteed complete undelete: only pages that happened
  to survive intact on the freelist (rather than being immediately reused
  during the same transaction) are recoverable.

**New: transparent WAL/SHM support.** Every source now automatically
detects sibling `-wal`/`-shm` files next to the path you pass and, if
found, reconciles them via a temporary working copy before reading —
picking up committed-but-not-yet-checkpointed data — without ever opening
the original three files for writing. This matters for forensic integrity:
opening a WAL-mode database read-write can silently trigger a checkpoint
that modifies the main file, which is unacceptable against original
evidence. The integrity panel discloses which sources this applied to and
hashes the original WAL/SHM files alongside the main database.

#### 1.0.1

- **Cache.sqlite is optional, not required** — this already worked (the
  pipeline has always gracefully handled an absent Cache.sqlite), but the
  documentation incorrectly called it required in several places (`cli.py`'s
  docstring/`-h` text, `README.md`). Corrected throughout.
- `main()` now prints an explicit **reduced-functionality notice** at the
  start of any run missing `-cache`, spelling out exactly what's lost for
  that run: no GPS ping track, no automatic place/stay detection (unless
  `-cloud` is supplied instead), no interpolation fallback for photos
  without their own EXIF GPS, and no place correlation for app
  sessions/messages/calls/interactions (unless `-cloud` is supplied).
- Fixed a pre-existing bug (present since before 1.0.0) where supplying
  `-knowledgec` under-counted the run's total step count by one — e.g. the
  progress display would show `[5/4]` instead of `[5/5]`. Cosmetic only;
  never affected report output.

#### 1.0.0 — First stable release

**No behavior change from 4.5.3.** This release is the rearchitecture from
a single ~5,000-line script into a proper package, plus a full documentation
pass. Verified by diffing generated report HTML byte-for-byte against the
prior monolithic script on identical input (only the "Generated <timestamp>"
line differs, as expected between any two separate runs).

- Rearchitected into `constants.py` / `utils.py` / `db.py` / `media.py` /
  `classification.py` / `analysis.py`, one `loaders/*.py` module per
  forensic source (Photos, Cache, Cloud-V2, knowledgeC, sms, Calls,
  AddressBook, Interactions), and one `report/*.py` module per report
  concern (styles, scripts, data injection, integrity panel, body markup,
  place cards, builder/orchestrator).
- The report's static CSS and JS are now genuine, unescaped CSS/JS text
  (`report/styles.py`, `report/scripts.py`) instead of living inside one
  giant Python f-string with every literal `{`/`}` doubled to `{{`/`}}`.
  Only the small per-report data payload (`report/data_injection.py`)
  still needs Python interpolation.
- `-h` now uses a raw-text formatter so the epilog's worked examples and
  line breaks render as written instead of being re-wrapped into one
  paragraph, and includes a full example command exercising every
  optional data source together.
- Expanded documentation throughout: this changelog, an expanded
  `README.md`, an expanded package docstring (`__init__.py`), and an
  expanded module docstring + inline comments in `cli.py`.

#### 4.5.3

- HEIC→JPEG batch conversion (`-convert-heic`) plus in-report photo
  previews sourced from a DCIM folder beside the report.

#### 4.5.2

- Map stay clustering: same-location stays collapse to a single pin with
  a visit-count badge and a visit list, instead of one pin per visit.

#### 4.5.1

- Messages/Calls/Interactions now appear on the Timeline tab, with
  per-type toggles.

#### 4.5.0

- `interactionC.db` cross-app interaction log support (new Interactions
  tab), with overlap flagging against `sms.db`/CallHistory activity.

#### 4.4.0

- `AddressBook.sqlitedb` contact resolution for Messages/Calls/Interactions
  senders, recipients, and callers.

#### 4.3.0

- `CallHistory.storedata` integration (new Calls tab).

#### 4.2.0

- `sms.db` integration (new Messages tab).

#### 4.1.0

- Per-stay exportable report, optional `Photos.sqlite` support, and
  name-resolution fixes.

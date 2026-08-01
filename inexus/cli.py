"""
Command-line entry point: argument parsing (parse_args()) and the run
pipeline that wires every loader/analysis step together and writes the
final self-contained HTML report (main()).

WHAT THIS TOOL DOES
    Every flag below is optional and additive — there is no single
    required source. Cache.sqlite is the primary, recommended anchor
    source (it's the only one with a raw GPS ping track, and it drives
    automatic place/stay detection), but if it isn't available — not
    recovered, or the device never had one — the tool still runs. Each
    source you do supply gets correlated against whatever location data
    exists the same way: matched to a detected Stay when possible, or an
    interpolated GPS location otherwise. Supplying more sources adds more
    report tabs and more per-stay detail.

        -cache          Cache.sqlite               location history + GPS track (recommended anchor)
        -photos         Photos.sqlite              photo/video assets + thumbnails
        -cloud          Cloud-V2.sqlite            supplemental learned places/visits
        -knowledgec     knowledgeC.db              app foreground/background usage
        -sms            sms.db                     Messages (iMessage/SMS)
        -calls          CallHistory.storedata       Phone/FaceTime/VoIP calls
        -interactions   interactionC.db             cross-app interaction log (Siri donations)
        -addressbook    AddressBook.sqlitedb        contact-name resolution for
                                                     -sms/-calls/-interactions

    REDUCED-FUNCTIONALITY MODE (no -cache)
        Running without -cache still produces a complete report, but with
        these tradeoffs:
          • No GPS ping track on the map (Cache.sqlite is the only source
            of raw pings).
          • Automatic place/stay detection only happens if -cloud is
            supplied instead — Cloud-V2.sqlite's own learned visits still
            get clustered into stays on their own. With neither -cache
            nor -cloud, the Places/Map views will show no stays at all.
          • Photos keep only their own embedded EXIF GPS — there's no
            ping stream left to interpolate a location for photos that
            lack it.
          • App sessions/messages/calls/interactions can still be matched
            to Cloud-V2 stays if -cloud is supplied; otherwise they're
            shown as unlocated rather than dropped.
        main() prints an explicit notice at the start of any run missing
        -cache, spelling out exactly which of the above apply that run.

FULL EXAMPLE — every optional source supplied at once:

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

Run `-h` for the full flag reference, including each tunable parameter's
default and what it controls.
"""
import argparse, os, sys, textwrap

from .constants import (
    TOOL_NAME, TOOL_VERSION,
    DEFAULT_CLUSTER_RADIUS_M, DEFAULT_CLUSTER_TIME_GAP_HRS,
    DEFAULT_INTERP_WINDOW_SECS, DEFAULT_PLACE_GPS_REJECT_M,
    DEFAULT_MIN_STAY_MINUTES,
)
from .utils import sha256_file, fmt_dt, fmt_dur
from .banner import banner_text
from .sqlite_forensics.walcopy import find_wal_shm, cleanup_all as _cleanup_wal_copies
from .media import convert_dcim_heic, find_existing_jpeg_tree
from .analysis import (
    merge_location_sources, correlate_app_sessions, cluster_visits,
    assign_photos_to_places, attach_photos_to_places,
)
from .loaders.photos import load_photos
from .loaders.addressbook import load_addressbook
from .loaders.cache import load_cache
from .loaders.cloud_v2 import load_cloud_v2
from .loaders.knowledgec import load_knowledgec
from .loaders.sms import load_sms
from .loaders.calls import load_calls
from .loaders.interactions import load_interactions
from .recovery.cache import recover_cache
from .recovery.photos import recover_photos
from .recovery.cloud_v2 import recover_cloud_v2
from .recovery.knowledgec import recover_knowledgec
from .recovery.sms import recover_sms
from .recovery.calls import recover_calls
from .recovery.addressbook import recover_addressbook
from .recovery.interactions import recover_interactions
from .report.builder import build_html


class _HelpFormatter(argparse.RawDescriptionHelpFormatter,
                      argparse.ArgumentDefaultsHelpFormatter):
    """Preserves the manual line breaks/indentation in description and
    epilog (RawDescriptionHelpFormatter) while still appending each
    argument's default value to its help text (ArgumentDefaultsHelpFormatter).
    Plain ArgumentDefaultsHelpFormatter alone re-wraps the epilog into one
    run-on paragraph, which mangles the worked examples below."""
    pass


class _VersionAction(argparse.Action):
    """Replaces argparse's built-in action="version" so `-version` shows
    the ASCII banner (see banner.py) above the version line, rather than
    just a bare "TOOL vX.Y.Z" string. Same immediate-exit behavior as the
    built-in action — this only changes what gets printed first."""
    def __init__(self, option_strings, dest, **kwargs):
        kwargs.setdefault("nargs", 0)
        kwargs.setdefault("default", argparse.SUPPRESS)
        kwargs.setdefault("help", "Show version information and exit.")
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print(banner_text())
        parser.exit()


def parse_args():
    _para1 = textwrap.fill(
        "If a flag is omitted, the tool's built-in default is used and the "
        "report's Integrity & Parameters panel will show that field in white. "
        "Any value you explicitly pass is shown in yellow with a "
        "'MODIFIED FROM DEFAULT' flag so reviewers can immediately see what "
        "was tuned for this run.", width=78)
    _para2 = textwrap.fill(
        "NOTE on argument order: if you're using any -flag (like -cloud or "
        "-case) AND want to set a custom output filename, prefer -output "
        "FILENAME over the positional output argument — argparse can "
        "misparse 'cache.sqlite -cloud X report.html' (the positional "
        "output after a flag gets dropped). Either of these is safe:", width=78)
    p = argparse.ArgumentParser(
        prog="inexus.py",
        description=(
            banner_text() + "\n\n"
            "Correlates Cache.sqlite location history (the primary,\n"
            "recommended source — not strictly required, see -cache's help\n"
            "below) with any combination of Photos.sqlite, Cloud-V2.sqlite,\n"
            "knowledgeC.db, sms.db, CallHistory.storedata, AddressBook.sqlitedb,\n"
            "and interactionC.db into one self-contained, offline HTML\n"
            "forensic report. Every source is additive: supplying more of\n"
            "them adds more report tabs and more per-stay detail; supplying\n"
            "none still produces a report, though without -cache or -cloud\n"
            "no stays/places can be automatically detected.\n\n"
            "FULL EXAMPLE — every optional source supplied at once:\n\n"
            "  python3 -m inexus \\\n"
            "      -cache        Cache.sqlite \\\n"
            "      -photos       Photos.sqlite \\\n"
            "      -cloud        Cloud-V2.sqlite \\\n"
            "      -knowledgec   knowledgeC.db \\\n"
            "      -sms          sms.db \\\n"
            "      -calls        CallHistory.storedata \\\n"
            "      -addressbook  AddressBook.sqlitedb \\\n"
            "      -interactions interactionC.db \\\n"
            "      -output       report.html \\\n"
            "      -case         2024-001 \\\n"
            "      -examiner     \"J. Smith\" \\\n"
            "      -notes        \"Full extraction, all sources\" \\\n"
            "      -radius 150 -visit 4 -window 120 -reject 500 -minstay 3 \\\n"
            "      -convert-heic -dcim DCIM -jpeg-quality 85 \\\n"
            "      -recover-deleted"
        ),
        formatter_class=_HelpFormatter,
        epilog=(
            _para1 + "\n\n" + _para2 + "\n"
            "  ...Cache.sqlite report.html -cloud Cloud-V2.sqlite\n"
            "  ...Cache.sqlite -cloud Cloud-V2.sqlite -output report.html"
        ),
    )
    p.add_argument("-cache", dest="cache_db", default=None, metavar="CACHE_DB",
                    help="Path to Cache.sqlite — the primary location-history "
                         "source, and the only source that provides a raw GPS "
                         "ping track. Recommended, but NOT required: if it "
                         "isn't available (not recovered, or the device never "
                         "had one), the tool still runs in reduced-"
                         "functionality mode — see the module docstring "
                         "('reduced-functionality mode') for exactly what's "
                         "lost. -cloud can substitute for place/stay "
                         "detection on its own if supplied.")
    p.add_argument("-output", dest="output_flag", default=None, metavar="PATH",
                    help="Output HTML report path (flag form — safe to use in any "
                         "position; takes precedence over the positional output "
                         "argument if both are somehow given)")
    p.add_argument("-version", action=_VersionAction)

    p.add_argument("-photos", default=None, metavar="PHOTOS_DB",
                    help="Optional path to Photos.sqlite. When provided, photo "
                         "assets are correlated against the location data — "
                         "matched to a detected Stay when possible, or an "
                         "interpolated location from the ping stream otherwise. "
                         "Adds a Photos tab and per-stay photo thumbnails. "
                         "When omitted, the report focuses purely on the "
                         "location/temporal datasets (Cache, Cloud-V2, "
                         "knowledgeC, and any future sources).")
    p.add_argument("-cloud", default=None, metavar="CLOUD_DB",
                    help="Optional path to Cloud-V2.sqlite. When provided, its "
                         "learned visits/places/transitions are merged with "
                         "Cache.sqlite's data rather than replacing it — a stay "
                         "recorded in both files is flagged as CORROBORATED, and "
                         "Cloud-V2's human-readable place names/addresses are "
                         "used to label stays wherever available.")
    p.add_argument("-knowledgec", default=None, metavar="KNOWLEDGEC_DB",
                    help="Optional path to knowledgeC.db. When provided, app "
                         "foreground/background usage sessions ('/app/usage' "
                         "stream) are correlated against the location data the "
                         "same way photos are — each session gets matched to a "
                         "detected Stay when possible, or an interpolated "
                         "location from the ping stream otherwise. Adds an "
                         "App Usage tab and a per-stay 'apps used here' list.")

    p.add_argument("-sms", default=None, metavar="SMS_DB",
                    help="Optional path to sms.db (the Messages app database). "
                         "When provided, messages — including tapback "
                         "reactions, attachment-only messages, and system/"
                         "group-action events — are correlated against the "
                         "location data the same way photos and app usage "
                         "sessions are. Senders/recipients are shown as the "
                         "raw phone number/email, or a name resolved via "
                         "-addressbook when supplied. Adds a Messages tab "
                         "and a per-stay 'messages sent/received here' list.")

    p.add_argument("-calls", default=None, metavar="CALLHISTORY_DB",
                    help="Optional path to CallHistory.storedata (the Phone/"
                         "FaceTime call log, including third-party VoIP apps "
                         "registered with CallKit — WhatsApp, Signal, "
                         "Telegram, FaceTime, etc.). When provided, calls are "
                         "correlated against the location data the same way "
                         "messages and app usage sessions are, anchored on "
                         "each call's midpoint so multi-minute calls aren't "
                         "mis-located to their very first second. Callers are "
                         "shown as the raw number, or the on-device cached "
                         "name from CallHistory.storedata itself when "
                         "present, or a name resolved via -addressbook when "
                         "supplied. Adds a Calls tab and a per-stay 'calls "
                         "made/received here' list.")

    p.add_argument("-addressbook", default=None, metavar="ADDRESSBOOK_DB",
                    help="Optional path to AddressBook.sqlitedb (the Contacts "
                         "database). When provided, raw phone numbers in "
                         "Messages, Calls, and Interactions are resolved to "
                         "contact names — phone numbers are matched after "
                         "stripping punctuation/spacing/country-code "
                         "differences (e.g. '+15828887553' and "
                         "'(919) 888-7386' for the same underlying number "
                         "both resolve), and emails are matched case-"
                         "insensitively. The raw number/email is always kept "
                         "and shown alongside the resolved name — this never "
                         "replaces or hides the original artifact value, "
                         "only labels it. Has no effect without -sms, "
                         "-calls, and/or -interactions also supplied.")

    p.add_argument("-interactions", default=None, metavar="INTERACTIONC_DB",
                    help="Optional path to interactionC.db (CoreDuet's "
                         "cross-app Interactions database — the donation log "
                         "Siri uses for 'frequently contacted' predictions). "
                         "Unlike -sms/-calls, which only cover Apple's native "
                         "Messages and Phone/FaceTime, this captures activity "
                         "from every app that donates interactions to Siri — "
                         "Mail, Snapchat, Skype, Telegram, WhatsApp, Signal, "
                         "Zoom, Teams, and more. Rows that DO overlap with "
                         "native Messages/FaceTime/InCallService activity are "
                         "still included (not deduplicated against -sms/"
                         "-calls) but are flagged with an overlap badge in "
                         "the UI. Adds an Interactions tab and a per-stay "
                         "'app interactions here' list.")

    p.add_argument("-radius", type=float, default=DEFAULT_CLUSTER_RADIUS_M,
                    metavar="METRES",
                    help="Clustering radius: visits within this many metres of "
                         "each other are considered the same place")
    p.add_argument("-visit", type=float, default=DEFAULT_CLUSTER_TIME_GAP_HRS,
                    metavar="HOURS",
                    help="Visit-merge gap: max hours between visits to the same "
                         "location before they're treated as separate, distinct stays")
    p.add_argument("-window", type=float, default=DEFAULT_INTERP_WINDOW_SECS,
                    metavar="SECONDS",
                    help="GPS interpolation window: how many seconds forward/"
                         "backward to search for a usable location ping when a "
                         "photo has no embedded GPS")
    p.add_argument("-reject", type=float, default=DEFAULT_PLACE_GPS_REJECT_M,
                    metavar="METRES",
                    help="Reject a time-window place match if the photo's own "
                         "GPS is farther than this from the place centroid")
    p.add_argument("-minstay", type=float, default=DEFAULT_MIN_STAY_MINUTES,
                    metavar="MINUTES",
                    help="Minimum visit duration to be considered a reportable stay")

    p.add_argument("-case", default=None, metavar="CASE_NUMBER",
                    help="Case number to display in the report's integrity panel")
    p.add_argument("-examiner", default=None, metavar="NAME",
                    help="Examiner name to display in the report's integrity panel")
    p.add_argument("-notes", default=None, metavar="TEXT",
                    help="Free-text note to display in the report's integrity panel")

    p.add_argument("-convert-heic", dest="convert_heic", action="store_true",
                    help="Before building the report, batch-convert every HEIC/HEIF "
                         "image found under the DCIM folder into JPEGs, written to a "
                         "separate parallel folder tree (the original DCIM is left "
                         "untouched). The report then shows the JPEG preview for HEIC "
                         "assets automatically. Requires the 'pillow-heif' package "
                         "(pip install pillow-heif). DCIM is expected to sit in the "
                         "same directory as the output report unless -dcim is given. "
                         "If a matching JPEG tree from a previous run is found it is "
                         "reused, and only newly-added images are converted (no full "
                         "re-encode).")
    p.add_argument("-dcim", dest="dcim", default=None, metavar="PATH",
                    help="Explicit path to the DCIM folder to convert (use with "
                         "-convert-heic). Defaults to a 'DCIM' folder next to the "
                         "output HTML report.")
    p.add_argument("-jpeg-quality", dest="jpeg_quality", type=int, default=85,
                    metavar="N",
                    help="JPEG quality (1-100) for -convert-heic output.")
    p.add_argument("-recover-deleted", dest="recover_deleted", action="store_true",
                    help="After normally loading each source supplied above, also scan "
                         "that same file's SQLite freelist pages for deleted rows that "
                         "haven't been overwritten yet (see sqlite_forensics/ for how). "
                         "Recovered rows are shown in a separate 'RECOVERED DATA' report "
                         "tab, clearly marked and never merged into the confirmed map/"
                         "timeline/places views — a recovered row means a freed page "
                         "still held old data when this ran, not confirmed live data. "
                         "This is necessarily partial: only pages that happened to "
                         "survive intact on the freelist are recoverable, so an empty "
                         "or small result here does not mean nothing was ever deleted.")

    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    """
    The run pipeline, in order:
      1. Hash every source file supplied (SHA-256), for the integrity panel.
      2. Load Cache.sqlite (required) and merge in Cloud-V2.sqlite (optional).
      3. Cluster visits into places (cluster_visits()), using -radius/-visit.
      4. For each optional source supplied (-photos/-knowledgec/-sms/-calls/
         -interactions), load it and correlate it against the places/ping
         stream (correlate_app_sessions() / assign_photos_to_places()),
         resolving contact names via -addressbook where applicable.
      5. Build the self-contained HTML report (report.builder.build_html())
         and write it to -output (or the positional output path, or the
         default filename).
    See parse_args() / `-h` for the full flag reference.
    """
    args = parse_args()
    print(f"{TOOL_NAME} v{TOOL_VERSION}")

    photos_path = args.photos
    cache_path  = args.cache_db
    cloud_path  = args.cloud
    kc_path     = args.knowledgec
    sms_path    = args.sms
    calls_path  = args.calls
    addressbook_path = args.addressbook
    interactions_path = args.interactions
    # -output flag takes precedence; fall back to the positional form;
    # fall back to the tool's default filename if neither was given.
    out_path = args.output_flag or "location_report.html"

    # Surface the actual values used this run — defaults or overridden —
    # so build_html() can disclose them transparently in the report.
    run_params = {
        "radius_m":           args.radius,
        "time_gap_hours":     args.visit,
        "interp_window_secs": args.window,
        "gps_reject_m":       args.reject,
        "min_stay_minutes":   args.minstay,
    }
    overridden = []
    if args.radius  != DEFAULT_CLUSTER_RADIUS_M:     overridden.append(f"-radius={args.radius}m")
    if args.visit    != DEFAULT_CLUSTER_TIME_GAP_HRS: overridden.append(f"-visit={args.visit}h")
    if args.window  != DEFAULT_INTERP_WINDOW_SECS:   overridden.append(f"-window={args.window}s")
    if args.reject   != DEFAULT_PLACE_GPS_REJECT_M:   overridden.append(f"-reject={args.reject}m")
    if args.minstay  != DEFAULT_MIN_STAY_MINUTES:     overridden.append(f"-minstay={args.minstay}min")

    case_info = {
        "case_number": args.case,
        "examiner":    args.examiner,
        "notes":       args.notes,
    }

    # Base steps: cache load, clustering, HTML generation, writing.
    # Photos (load + assign + attach), Cloud-V2, knowledgeC, sms.db, and
    # CallHistory.storedata each add steps only when supplied. AddressBook
    # adds one lightweight lookup-table-build step when supplied — it's
    # only useful alongside -sms/-calls, but is hashed/logged independently
    # regardless, same as every other source.
    n_steps = 3
    if cache_path:       n_steps += 1
    if photos_path:      n_steps += 3
    if cloud_path:        n_steps += 1
    if kc_path:           n_steps += 2
    if sms_path:           n_steps += 2
    if calls_path:         n_steps += 2
    if addressbook_path:    n_steps += 1
    if interactions_path:    n_steps += 2
    if args.recover_deleted: n_steps += 1

    def _hash_source(label, path, hash_key):
        """Hashes `path`, prints it, and — if sibling -wal/-shm files exist —
        hashes/prints those too and records a note for the integrity panel.
        Returns the dict of hash values to merge into file_hashes."""
        h = sha256_file(path)
        print(f"      {label}: {h or '⚠ could not be computed'}")
        out = {hash_key: h}
        wal_path, shm_path = find_wal_shm(path)
        if wal_path or shm_path:
            wal_notes.append(label)
            print("        + found sibling WAL/SHM — reconciling via a temporary "
                  "working copy (originals untouched)")
            if wal_path:
                wal_hash = sha256_file(wal_path)
                print(f"        WAL SHA-256: {wal_hash or '⚠ could not be computed'}")
                out[hash_key.replace("_sha256", "_wal_sha256")] = wal_hash
            if shm_path:
                shm_hash = sha256_file(shm_path)
                print(f"        SHM SHA-256: {shm_hash or '⚠ could not be computed'}")
                out[hash_key.replace("_sha256", "_shm_sha256")] = shm_hash
        return out

    print("[0/{}] Computing source file hashes (SHA-256)…".format(n_steps))
    wal_notes = []  # labels of sources where a sibling WAL/SHM was found and used
    file_hashes = {"cache_sha256": None}
    if cache_path:
        file_hashes.update(_hash_source("Cache.sqlite", cache_path, "cache_sha256"))
    if photos_path:
        file_hashes.update(_hash_source("Photos.sqlite", photos_path, "photos_sha256"))
    if cloud_path:
        file_hashes.update(_hash_source("Cloud-V2.sqlite", cloud_path, "cloud_v2_sha256"))
    if kc_path:
        file_hashes.update(_hash_source("knowledgeC.db", kc_path, "knowledgec_sha256"))
    if sms_path:
        file_hashes.update(_hash_source("sms.db", sms_path, "sms_sha256"))
    if calls_path:
        file_hashes.update(_hash_source("CallHistory.storedata", calls_path, "calls_sha256"))
    if addressbook_path:
        file_hashes.update(_hash_source("AddressBook.sqlitedb", addressbook_path, "addressbook_sha256"))
    if interactions_path:
        file_hashes.update(_hash_source("interactionC.db", interactions_path, "interactions_sha256"))

    if overridden:
        print(f"[!] Non-default parameters in use: {', '.join(overridden)}")
    else:
        print("[i] Using all default parameters")

    if not cache_path:
        print("[!] No Cache.sqlite supplied — running in reduced-functionality mode:")
        print("      • No GPS ping track will be drawn on the map (Cache.sqlite is the "
              "only ping source)")
        if cloud_path:
            print("      • Places/stays will come only from Cloud-V2.sqlite's learned visits")
        else:
            print("      • No automatic place/stay detection — Map/Places views will show "
                  "no stays (supply -cloud to still get stays without Cache.sqlite)")
        print("      • Photos keep only their own embedded EXIF GPS — no interpolation "
              "fallback for photos without it")
        if kc_path or sms_path or calls_path or interactions_path:
            print("      • App sessions/messages/calls/interactions will show as unlocated "
                  "unless -cloud is also supplied")

    step = 1
    photos = []
    if photos_path:
        print(f"[{step}/{n_steps}] Loading photos from {photos_path}…")
        photos = load_photos(photos_path)
        print(f"      {len(photos)} assets loaded")
        step += 1

    if cache_path:
        print(f"[{step}/{n_steps}] Loading location cache from {cache_path}…")
        try:
            cache_result = load_cache(cache_path, min_stay_minutes=args.minstay)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        c_pings, c_visits, c_trips = cache_result
        print(f"      {len(c_pings)} GPS pings, {len(c_visits)} visits, {len(c_trips)} trip segments")
        step += 1
    else:
        cache_result = ([], [], [])
        c_pings, c_visits, c_trips = cache_result

    if cloud_path:
        print(f"[{step}/{n_steps}] Loading supplemental location data from {cloud_path}…")
        try:
            cloud_result = load_cloud_v2(cloud_path, min_stay_minutes=args.minstay)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        cl_pings, cl_visits, cl_trips = cloud_result
        print(f"      {len(cl_visits)} learned visits, {len(cl_trips)} learned transitions "
              f"({sum(1 for v in cl_visits if v.get('place_name'))} with named places)")
        pings, visits, trips = merge_location_sources(cache_result, cloud_result)
        print(f"      Merged total: {len(pings)} pings, {len(visits)} visits "
              f"({len(c_visits)} from Cache + {len(cl_visits)} from Cloud-V2), {len(trips)} trip/transition segments")
        step += 1
    else:
        pings, visits, trips = c_pings, c_visits, c_trips

    print(f"[{step}/{n_steps}] Clustering visits into places (radius={args.radius}m, "
          f"visit-gap={args.visit}h)…")
    places = cluster_visits(visits, radius_m=args.radius,
                             time_gap_secs=args.visit * 3600)
    n_corroborated = sum(1 for p in places if len(p.get("source_dbs", [])) > 1)
    print(f"      {len(places)} distinct stays detected"
          + (f" ({n_corroborated} corroborated by both sources)" if cloud_path else ""))
    step += 1

    pings_sorted = sorted(pings, key=lambda p: p["ts"])

    unplaced = []
    if photos_path:
        print(f"[{step}/{n_steps}] Assigning photos to places and inferring locations "
              f"(reject={args.reject}m, window=±{args.window}s)…")
        photos = assign_photos_to_places(photos, places, pings_sorted,
                                          gps_reject_m=args.reject,
                                          interp_window_secs=args.window)

        n_inferred = sum(1 for p in photos if not p["has_gps"] and p.get("inferred_lat"))
        print(f"      {n_inferred} photos got inferred coordinates")
        step += 1

        print(f"[{step}/{n_steps}] Attaching photos to places…")
        places, unplaced = attach_photos_to_places(places, photos)
        step += 1
    else:
        # No photos.sqlite supplied — still attach (a no-op against an empty
        # photos list) so every place dict carries the "photos" key the
        # report template expects.
        places, unplaced = attach_photos_to_places(places, photos)

    app_sessions = []
    if kc_path:
        print(f"[{step}/{n_steps}] Loading app usage sessions from {kc_path}…")
        try:
            app_sessions = load_knowledgec(kc_path)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        print(f"      {len(app_sessions)} app usage sessions loaded")
        step += 1

        print(f"[{step}/{n_steps}] Correlating app sessions to places/locations…")
        app_sessions = correlate_app_sessions(app_sessions, places, pings_sorted,
                                               gps_reject_m=args.reject,
                                               interp_window_secs=args.window)
        n_in_stay = sum(1 for s in app_sessions if s["place_id"] is not None)
        n_interp  = sum(1 for s in app_sessions
                         if s["place_id"] is None and s["location_method"] not in (None, "unknown"))
        print(f"      {n_in_stay} sessions matched to a known stay, "
              f"{n_interp} got interpolated coordinates")
        step += 1

    address_book = {}
    if addressbook_path:
        print(f"[{step}/{n_steps}] Loading contacts from {addressbook_path}…")
        try:
            address_book = load_addressbook(addressbook_path)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        print(f"      {len(address_book)} phone/email → name entries loaded")
        step += 1

    messages = []
    if sms_path:
        print(f"[{step}/{n_steps}] Loading messages from {sms_path}…")
        try:
            messages = load_sms(sms_path, address_book=address_book)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        print(f"      {len(messages)} messages loaded")
        if address_book:
            n_resolved = sum(1 for m in messages if m["sender_source"] == "addressbook")
            print(f"      {n_resolved} senders resolved via AddressBook.sqlitedb")
        step += 1

        print(f"[{step}/{n_steps}] Correlating messages to places/locations…")
        # correlate_app_sessions() is generic over any list of dicts with
        # start/end/place_id/lat/lng/location_method/location_accuracy keys —
        # messages are instantaneous events (start==end==ts), so it applies
        # unchanged rather than duplicating the same stay/interpolation logic.
        messages = correlate_app_sessions(messages, places, pings_sorted,
                                           gps_reject_m=args.reject,
                                           interp_window_secs=args.window)
        n_in_stay = sum(1 for m in messages if m["place_id"] is not None)
        n_interp  = sum(1 for m in messages
                         if m["place_id"] is None and m["location_method"] not in (None, "unknown"))
        print(f"      {n_in_stay} messages matched to a known stay, "
              f"{n_interp} got interpolated coordinates")
        step += 1

    calls = []
    if calls_path:
        print(f"[{step}/{n_steps}] Loading calls from {calls_path}…")
        try:
            calls = load_calls(calls_path, address_book=address_book)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        print(f"      {len(calls)} calls loaded")
        if address_book:
            n_resolved = sum(1 for c in calls if c["caller_source"] == "addressbook")
            print(f"      {n_resolved} callers resolved via AddressBook.sqlitedb")
        step += 1

        print(f"[{step}/{n_steps}] Correlating calls to places/locations…")
        # Reused again (see messages above) — calls carry a real duration,
        # so start/end span the call rather than being a single instant,
        # and correlate_app_sessions() already anchors on the midpoint,
        # which is the right behavior for a multi-minute call.
        calls = correlate_app_sessions(calls, places, pings_sorted,
                                        gps_reject_m=args.reject,
                                        interp_window_secs=args.window)
        n_in_stay = sum(1 for c in calls if c["place_id"] is not None)
        n_interp  = sum(1 for c in calls
                         if c["place_id"] is None and c["location_method"] not in (None, "unknown"))
        print(f"      {n_in_stay} calls matched to a known stay, "
              f"{n_interp} got interpolated coordinates")
        step += 1

    interactions = []
    if interactions_path:
        print(f"[{step}/{n_steps}] Loading interactions from {interactions_path}…")
        try:
            interactions = load_interactions(interactions_path, address_book=address_book)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        n_overlap = sum(1 for i in interactions if i["is_overlap"])
        print(f"      {len(interactions)} interactions loaded "
              f"({n_overlap} overlap with native Messages/Calls)")
        step += 1

        print(f"[{step}/{n_steps}] Correlating interactions to places/locations…")
        interactions = correlate_app_sessions(interactions, places, pings_sorted,
                                               gps_reject_m=args.reject,
                                               interp_window_secs=args.window)
        n_in_stay = sum(1 for i in interactions if i["place_id"] is not None)
        n_interp  = sum(1 for i in interactions
                         if i["place_id"] is None and i["location_method"] not in (None, "unknown"))
        print(f"      {n_in_stay} interactions matched to a known stay, "
              f"{n_interp} got interpolated coordinates")
        step += 1

    # Optional HEIC→JPEG batch conversion so the report can show previews for
    # HEIC assets. Runs against the DCIM folder beside the report (or -dcim),
    # writes a separate JPEG tree, and never touches the originals.
    heic_map = None
    if getattr(args, "convert_heic", False):
        out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
        dcim_path = args.dcim or os.path.join(out_dir, "DCIM")
        print(f"[heic] Scanning {dcim_path} for HEIC/HEIF images…")

        # First, see if a previous run already produced a matching JPEG tree.
        existing, existing_map, einfo = find_existing_jpeg_tree(out_dir, dcim_path)

        if existing and einfo["missing"] == 0:
            # Complete prior conversion — reuse it, encode nothing.
            heic_map = existing_map
            print(f"      Reusing existing {existing}/ "
                  f"({einfo['matched']}/{einfo['total_heic']} images already converted)")
        else:
            target = existing if existing else None   # top up partial tree, else fresh
            if existing:
                print(f"      Found {existing}/ with {einfo['matched']}/"
                      f"{einfo['total_heic']} already done — converting "
                      f"{einfo['missing']} new image(s) into it.")
            convbase, heic_map, hstats = convert_dcim_heic(
                out_dir, dcim_path, quality=args.jpeg_quality, target_dir=target)
            if hstats.get("error"):
                print(f"      ⚠ {hstats['error']}")
                print(f"      Report will still build; HEIC previews won't be available.")
            else:
                print(f"      {hstats['found']} HEIC found · {hstats['converted']} converted"
                      f" → {convbase}/"
                      + (f" · {hstats['skipped']} reused" if hstats['skipped'] else "")
                      + (f" · {hstats['failed']} failed" if hstats['failed'] else ""))

    recovered_data = None
    if args.recover_deleted:
        print(f"[{step}/{n_steps}] Scanning freelist pages for recoverable deleted rows…")
        recovered_data = {}
        if cache_path:
            recovered_data["cache"] = recover_cache(cache_path)
            print(f"      Cache.sqlite: {len(recovered_data['cache'])} candidate row(s) recovered")
        if photos_path:
            recovered_data["photos"] = recover_photos(photos_path)
            print(f"      Photos.sqlite: {len(recovered_data['photos'])} candidate row(s) recovered")
        if cloud_path:
            recovered_data["cloud_v2"] = recover_cloud_v2(cloud_path)
            print(f"      Cloud-V2.sqlite: {len(recovered_data['cloud_v2'])} candidate row(s) recovered")
        if kc_path:
            recovered_data["knowledgec"] = recover_knowledgec(kc_path)
            print(f"      knowledgeC.db: {len(recovered_data['knowledgec'])} candidate row(s) recovered")
        if sms_path:
            recovered_data["sms"] = recover_sms(sms_path)
            print(f"      sms.db: {len(recovered_data['sms'])} candidate row(s) recovered")
        if calls_path:
            recovered_data["calls"] = recover_calls(calls_path)
            print(f"      CallHistory.storedata: {len(recovered_data['calls'])} candidate row(s) recovered")
        if addressbook_path:
            recovered_data["addressbook"] = recover_addressbook(addressbook_path)
            print(f"      AddressBook.sqlitedb: {len(recovered_data['addressbook'])} candidate row(s) recovered")
        if interactions_path:
            recovered_data["interactions"] = recover_interactions(interactions_path)
            print(f"      interactionC.db: {len(recovered_data['interactions'])} candidate row(s) recovered")
        total_recovered = sum(len(v) for v in recovered_data.values())
        if total_recovered == 0:
            print("      No recoverable rows found — either nothing relevant was ever "
                  "deleted from these files, the freed pages were already reused, or "
                  "(if applicable) the database was VACUUMed since deletion.")
        step += 1

    print(f"[{step}/{n_steps}] Generating HTML…")
    html = build_html(photos, places, unplaced, pings_sorted, trips,
                       photos_path, cache_path,
                       run_params=run_params, file_hashes=file_hashes,
                       case_info=case_info, cloud_db_path=cloud_path,
                       app_sessions=app_sessions, knowledgec_db_path=kc_path,
                       messages=messages, sms_db_path=sms_path,
                       calls=calls, calls_db_path=calls_path,
                       interactions=interactions, interactions_db_path=interactions_path,
                       addressbook_db_path=addressbook_path, heic_map=heic_map,
                       wal_sources=wal_notes, recovered_data=recovered_data)
    step += 1

    print(f"[{step}/{n_steps}] Writing report…")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✓ Report written to: {out_path} ({os.path.getsize(out_path)//1024} KB)")
    if photos_path:
        print(f"  SHA-256 Photos.sqlite: {file_hashes.get('photos_sha256') or 'N/A'}")
    print(f"  SHA-256 Cache.sqlite:  {file_hashes.get('cache_sha256') or 'N/A'}")
    if cloud_path:
        print(f"  SHA-256 Cloud-V2.sqlite: {file_hashes.get('cloud_v2_sha256') or 'N/A'}")
    if kc_path:
        print(f"  SHA-256 knowledgeC.db: {file_hashes.get('knowledgec_sha256') or 'N/A'}")
    if sms_path:
        print(f"  SHA-256 sms.db: {file_hashes.get('sms_sha256') or 'N/A'}")
    if calls_path:
        print(f"  SHA-256 CallHistory.storedata: {file_hashes.get('calls_sha256') or 'N/A'}")
    if addressbook_path:
        print(f"  SHA-256 AddressBook.sqlitedb: {file_hashes.get('addressbook_sha256') or 'N/A'}")
    if interactions_path:
        print(f"  SHA-256 interactionC.db: {file_hashes.get('interactions_sha256') or 'N/A'}")
    for p in places:
        n = len(p["photos"])
        src = "+".join(p.get("source_dbs", ["cache"]))
        name = p.get("device_place_name")
        label = f" \"{name}\"" if name else ""
        print(f"  Stay #{p['id']:2d} [{src}]{label}: {fmt_dt(p['entry'])} → {fmt_dt(p['exit'])}  "
              f"({fmt_dur(p['duration'])})  lat={p['lat']:.4f} lng={p['lng']:.4f}  photos={n}")

    _cleanup_wal_copies()

if __name__ == "__main__":
    main()

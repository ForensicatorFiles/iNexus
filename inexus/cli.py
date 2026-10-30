"""
Command-line and GUI entry point: argument parsing (parse_args()), GUI
launcher handoff, and the run pipeline (run_pipeline()) that wires every
loader/analysis step together and writes the final self-contained HTML report.
"""
import argparse, os, sys, textwrap
from datetime import datetime, timezone

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
from .loaders.local_db import load_local_db
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
    pass


class _VersionAction(argparse.Action):
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
        "TIP: Run `python3 inexus.py` with no arguments (or `-gui`) to open "
        "the interactive desktop GUI with file pickers and 1-click extraction "
        "folder auto-discovery.", width=78)
    p = argparse.ArgumentParser(
        prog="inexus.py",
        description=(
            banner_text() + "\n\n"
            "Correlates iOS location history across Cache.sqlite, Local.sqlite,\n"
            "and/or Cloud-V2.sqlite with any combination of Photos.sqlite,\n"
            "knowledgeC.db, sms.db, CallHistory.storedata, AddressBook.sqlitedb,\n"
            "and interactionC.db into one self-contained, offline HTML\n"
            "forensic report.\n\n"
            "Run with no arguments or pass `-gui` to launch the interactive GUI."
        ),
        formatter_class=_HelpFormatter,
        epilog=_para1 + "\n\n" + _para2,
    )
    p.add_argument("-gui", "--gui", dest="gui", action="store_true",
                    help="Launch the Tkinter graphical interface for selecting "
                         "databases and tuning parameters interactively.")
    p.add_argument("-cache", dest="cache_db", default=None, metavar="CACHE_DB",
                    help="Path to Cache.sqlite — high-frequency GPS ping track "
                         "and short-term visit history.")
    p.add_argument("-local", dest="local", default=None, metavar="LOCAL_DB",
                    help="Optional path to Local.sqlite (routined). Provides "
                         "long-term Significant Location / learned visits and "
                         "transitions — ideal when the target date has rolled "
                         "off Cache.sqlite or to corroborate stays.")
    p.add_argument("-cloud", default=None, metavar="CLOUD_DB",
                    help="Optional path to Cloud-V2.sqlite. Provides learned "
                         "visits, place names/addresses, and transitions.")
    p.add_argument("-output", dest="output_flag", default=None, metavar="PATH",
                    help="Output HTML report path.")
    p.add_argument("-version", action=_VersionAction)

    p.add_argument("-photos", default=None, metavar="PHOTOS_DB",
                    help="Optional path to Photos.sqlite.")
    p.add_argument("-knowledgec", default=None, metavar="KNOWLEDGEC_DB",
                    help="Optional path to knowledgeC.db.")
    p.add_argument("-sms", default=None, metavar="SMS_DB",
                    help="Optional path to sms.db.")
    p.add_argument("-calls", default=None, metavar="CALLHISTORY_DB",
                    help="Optional path to CallHistory.storedata.")
    p.add_argument("-addressbook", default=None, metavar="ADDRESSBOOK_DB",
                    help="Optional path to AddressBook.sqlitedb.")
    p.add_argument("-interactions", default=None, metavar="INTERACTIONC_DB",
                    help="Optional path to interactionC.db.")

    p.add_argument("-radius", type=float, default=DEFAULT_CLUSTER_RADIUS_M,
                    metavar="METRES",
                    help="Clustering radius in metres.")
    p.add_argument("-visit", type=float, default=DEFAULT_CLUSTER_TIME_GAP_HRS,
                    metavar="HOURS",
                    help="Visit-merge gap in hours.")
    p.add_argument("-window", type=float, default=DEFAULT_INTERP_WINDOW_SECS,
                    metavar="SECONDS",
                    help="GPS interpolation window in seconds.")
    p.add_argument("-reject", type=float, default=DEFAULT_PLACE_GPS_REJECT_M,
                    metavar="METRES",
                    help="Reject a time-window place match if photo GPS is farther than this.")
    p.add_argument("-minstay", type=float, default=DEFAULT_MIN_STAY_MINUTES,
                    metavar="MINUTES",
                    help="Minimum visit duration in minutes.")

    p.add_argument("-case", default=None, metavar="CASE_NUMBER",
                    help="Case number for the report's integrity panel.")
    p.add_argument("-examiner", default=None, metavar="NAME",
                    help="Examiner name for the report's integrity panel.")
    p.add_argument("-notes", default=None, metavar="TEXT",
                    help="Free-text note for the report's integrity panel.")

    p.add_argument("-convert-heic", dest="convert_heic", action="store_true",
                    help="Batch-convert DCIM HEIC/HEIF images into JPEGs.")
    p.add_argument("-dcim", dest="dcim", default=None, metavar="PATH",
                    help="Explicit path to the DCIM folder.")
    p.add_argument("-jpeg-quality", dest="jpeg_quality", type=int, default=85,
                    metavar="N",
                    help="JPEG quality (1-100) for -convert-heic output.")
    p.add_argument("-recover-deleted", dest="recover_deleted", action="store_true",
                    help="Scan SQLite freelist pages for deleted rows.")
    p.add_argument("-carto-key", dest="carto_key", default=None, metavar="KEY",
                    help="CARTO API key for map tiles. If omitted, the tool "
                         "automatically looks for a 'carto_key.txt' file in "
                         "the working directory.")
    p.add_argument("-thumbnails", dest="thumbnails_dir", default=None, metavar="V2_PATH",
                help="Optional path to the exported PhotoData/Thumbnails/V2 folder. "
                     "When provided, the tool scans for cached thumbnails belonging "
                     "to deleted or unindexed photos and adds them as recovered assets.")
    p.add_argument("-start", dest="start_date", default=None, metavar="YYYY-MM-DD", help="Start date (UTC)")
    p.add_argument("-end", dest="end_date", default=None, metavar="YYYY-MM-DD", help="End date (UTC)")

    return p.parse_args()

def apply_date_filters(data_list, start_str, end_str, time_key='ts'):
    """Filters a list of artifact dictionaries based on a target time key."""
    if not start_str and not end_str:
        return data_list
        
    start_unix = 0
    end_unix = float('inf')
    
    if start_str:
        dt_start = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_unix = dt_start.timestamp()
        
    if end_str:
        dt_end = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_unix = dt_end.timestamp() + 86399
        
    filtered = []
    for item in data_list:
        item_time = item.get(time_key)
        if item_time is None:
            filtered.append(item) 
        elif start_unix <= item_time <= end_unix:
            filtered.append(item)
            
    return filtered


def run_pipeline(args):
    """Executes the full iNexus loading, correlation, and HTML report pipeline."""
    print(f"{TOOL_NAME} v{TOOL_VERSION}")

    photos_path       = args.photos
    cache_path        = args.cache_db
    local_path        = getattr(args, "local", None)
    cloud_path        = args.cloud
    kc_path           = args.knowledgec
    sms_path          = args.sms
    calls_path        = args.calls
    addressbook_path  = args.addressbook
    interactions_path = args.interactions
    out_path          = args.output_flag or "location_report.html"

    # Load CARTO API key from argument or local carto_key.txt fallback
    carto_api_key = getattr(args, "carto_key", None)
    if not carto_api_key and os.path.exists("carto_key.txt"):
        try:
            with open("carto_key.txt", "r", encoding="utf-8") as f:
                carto_api_key = f.read().strip()
                if carto_api_key:
                    print("[i] Loaded CARTO API key from carto_key.txt")
        except Exception as e:
            print(f"[!] Warning: could not read carto_key.txt: {e}")

    run_params = {
        "radius_m":           args.radius,
        "time_gap_hours":     args.visit,
        "interp_window_secs": args.window,
        "gps_reject_m":       args.reject,
        "min_stay_minutes":   args.minstay,
        "start_date":         getattr(args, "start_date", None), 
        "end_date":           getattr(args, "end_date", None),   
    }
    overridden = []
    if args.radius  != DEFAULT_CLUSTER_RADIUS_M:     overridden.append(f"-radius={args.radius}m")
    if args.visit   != DEFAULT_CLUSTER_TIME_GAP_HRS: overridden.append(f"-visit={args.visit}h")
    if args.window  != DEFAULT_INTERP_WINDOW_SECS:   overridden.append(f"-window={args.window}s")
    if args.reject  != DEFAULT_PLACE_GPS_REJECT_M:   overridden.append(f"-reject={args.reject}m")
    if args.minstay != DEFAULT_MIN_STAY_MINUTES:     overridden.append(f"-minstay={args.minstay}min")

    case_info = {
        "case_number": args.case,
        "examiner":    args.examiner,
        "notes":       args.notes,
    }

    n_steps = 3
    if cache_path:           n_steps += 1
    if local_path:           n_steps += 1
    if cloud_path:           n_steps += 1
    if photos_path:          n_steps += 3
    if kc_path:              n_steps += 2
    if sms_path:             n_steps += 2
    if calls_path:           n_steps += 2
    if addressbook_path:     n_steps += 1
    if interactions_path:    n_steps += 2
    if args.recover_deleted: n_steps += 1

    def _hash_source(label, path, hash_key):
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
    wal_notes = []
    file_hashes = {"cache_sha256": None}
    if cache_path:
        file_hashes.update(_hash_source("Cache.sqlite", cache_path, "cache_sha256"))
    if local_path:
        file_hashes.update(_hash_source("Local.sqlite", local_path, "local_sha256"))
    if cloud_path:
        file_hashes.update(_hash_source("Cloud-V2.sqlite", cloud_path, "cloud_v2_sha256"))
    if photos_path:
        file_hashes.update(_hash_source("Photos.sqlite", photos_path, "photos_sha256"))
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
        print("[!] No Cache.sqlite supplied — running without raw GPS ping stream:")
        if local_path or cloud_path:
            active_loc = [ name for name, p in [("Local.sqlite", local_path), ("Cloud-V2.sqlite", cloud_path)] if p ]
            print(f"      • Places/stays will be built from {' + '.join(active_loc)}")
        else:
            print("      • No location database supplied (-cache, -local, or -cloud) — "
                  "Map/Places views will show no stays")

    step = 1
    photos = []
    if photos_path or getattr(args, "thumbnails_dir", None):
        thumbnails_dir = getattr(args, "thumbnails_dir", None)
        print(f"[{step}/{n_steps}] Loading photos (and V2 thumbnails) from {photos_path or 'thumbnails folder'}…")
        photos = load_photos(photos_path, thumbnails_dir=thumbnails_dir)  # Passed here correctly
        print(f"      {len(photos)} total assets loaded (including cached/orphaned thumbnails)")
        step += 1

    cache_result = ([], [], [])
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

    local_result = ([], [], [])
    if local_path:
        print(f"[{step}/{n_steps}] Loading learned location history from {local_path}…")
        try:
            local_result = load_local_db(local_path, min_stay_minutes=args.minstay)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        _, l_visits, l_trips = local_result
        print(f"      {len(l_visits)} learned visits, {len(l_trips)} learned transitions "
              f"({sum(1 for v in l_visits if v.get('place_name'))} with named places)")
        step += 1

    cloud_result = ([], [], [])
    if cloud_path:
        print(f"[{step}/{n_steps}] Loading Cloud-V2 location data from {cloud_path}…")
        try:
            cloud_result = load_cloud_v2(cloud_path, min_stay_minutes=args.minstay)
        except RuntimeError as e:
            print(f"\n✗ ERROR: {e}")
            sys.exit(1)
        _, cl_visits, cl_trips = cloud_result
        print(f"      {len(cl_visits)} learned visits, {len(cl_trips)} learned transitions "
              f"({sum(1 for v in cl_visits if v.get('place_name'))} with named places)")
        step += 1

    pings, visits, trips = merge_location_sources(cache_result, local_result, cloud_result)
    if sum(bool(x) for x in (cache_path, local_path, cloud_path)) > 1:
        print(f"      Merged location total: {len(pings)} pings, {len(visits)} visits, "
              f"{len(trips)} trip/transition segments")

    print(f"[{step}/{n_steps}] Clustering visits into places (radius={args.radius}m, "
          f"visit-gap={args.visit}h)…")
    places = cluster_visits(visits, radius_m=args.radius,
                             time_gap_secs=args.visit * 3600)
    n_corroborated = sum(1 for p in places if len(p.get("source_dbs", [])) > 1)
    print(f"      {len(places)} distinct stays detected"
          + (f" ({n_corroborated} corroborated across multiple location databases)" if n_corroborated else ""))
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

    heic_map = None
    if getattr(args, "convert_heic", False):
        out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
        dcim_path = args.dcim or os.path.join(out_dir, "DCIM")
        print(f"[heic] Scanning {dcim_path} for HEIC/HEIF images…")

        existing, existing_map, einfo = find_existing_jpeg_tree(out_dir, dcim_path)

        if existing and einfo["missing"] == 0:
            heic_map = existing_map
            print(f"      Reusing existing {existing}/ "
                  f"({einfo['matched']}/{einfo['total_heic']} images already converted)")
        else:
            target = existing if existing else None
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
        if local_path:
            # Local.sqlite shares the routined learned-visit schema with Cloud-V2
            recovered_data["local"] = recover_cloud_v2(local_path)
            print(f"      Local.sqlite: {len(recovered_data['local'])} candidate row(s) recovered")
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

    # Apply backend time filters before building the HTML
    sd, ed = getattr(args, "start_date", None), getattr(args, "end_date", None)
    if sd or ed:
        print(f"[{step}/{n_steps}] Applying global date filters ({sd or 'Start'} to {ed or 'End'})…")
        photos = apply_date_filters(photos, sd, ed, time_key='unix_ts')
        places = apply_date_filters(places, sd, ed, time_key='entry')
        app_sessions = apply_date_filters(app_sessions, sd, ed, time_key='start')
        messages = apply_date_filters(messages, sd, ed, time_key='ts')
        calls = apply_date_filters(calls, sd, ed, time_key='ts')
        interactions = apply_date_filters(interactions, sd, ed, time_key='ts')
        step += 1

    print(f"[{step}/{n_steps}] Generating HTML…")
    html = build_html(photos, places, unplaced, pings_sorted, trips,
                       photos_path, cache_path,
                       run_params=run_params, file_hashes=file_hashes,
                       case_info=case_info, cloud_db_path=cloud_path or local_path,
                       app_sessions=app_sessions, knowledgec_db_path=kc_path,
                       messages=messages, sms_db_path=sms_path,
                       calls=calls, calls_db_path=calls_path,
                       interactions=interactions, interactions_db_path=interactions_path,
                       addressbook_db_path=addressbook_path, heic_map=heic_map,
                       wal_sources=wal_notes, recovered_data=recovered_data,
                       carto_api_key=carto_api_key)
    step += 1

    print(f"[{step}/{n_steps}] Writing report…")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✓ Report written to: {out_path} ({os.path.getsize(out_path)//1024} KB)")
    if cache_path:
        print(f"  SHA-256 Cache.sqlite:          {file_hashes.get('cache_sha256') or 'N/A'}")
    if local_path:
        print(f"  SHA-256 Local.sqlite:          {file_hashes.get('local_sha256') or 'N/A'}")
    if cloud_path:
        print(f"  SHA-256 Cloud-V2.sqlite:       {file_hashes.get('cloud_v2_sha256') or 'N/A'}")
    if photos_path:
        print(f"  SHA-256 Photos.sqlite:         {file_hashes.get('photos_sha256') or 'N/A'}")
    if kc_path:
        print(f"  SHA-256 knowledgeC.db:         {file_hashes.get('knowledgec_sha256') or 'N/A'}")
    if sms_path:
        print(f"  SHA-256 sms.db:                {file_hashes.get('sms_sha256') or 'N/A'}")
    if calls_path:
        print(f"  SHA-256 CallHistory.storedata: {file_hashes.get('calls_sha256') or 'N/A'}")
    if addressbook_path:
        print(f"  SHA-256 AddressBook.sqlitedb:  {file_hashes.get('addressbook_sha256') or 'N/A'}")
    if interactions_path:
        print(f"  SHA-256 interactionC.db:       {file_hashes.get('interactions_sha256') or 'N/A'}")
    for p in places:
        n = len(p["photos"])
        src = "+".join(p.get("source_dbs", ["cache"]))
        name = p.get("device_place_name")
        label = f" \"{name}\"" if name else ""
        print(f"  Stay #{p['id']:2d} [{src}]{label}: {fmt_dt(p['entry'])} → {fmt_dt(p['exit'])}  "
              f"({fmt_dur(p['duration'])})  lat={p['lat']:.4f} lng={p['lng']:.4f}  photos={n}")

    _cleanup_wal_copies()


def main():
    # If launched with no CLI arguments (e.g., `python3 inexus.py`), open the GUI
    if len(sys.argv) == 1:
        from .gui import launch_gui
        launch_gui(run_pipeline)
        return

    args = parse_args()
    if getattr(args, "gui", False):
        from .gui import launch_gui
        launch_gui(run_pipeline)
        return

    run_pipeline(args)


if __name__ == "__main__":
    main()

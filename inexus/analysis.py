"""
Cross-source correlation and geospatial analysis: merging Cache.sqlite +
Cloud-V2.sqlite location results into one place list, clustering visits
into stays, and correlating any timestamped artifact (photos, app
sessions, messages, calls, interactions) against the GPS ping stream.
"""
from collections import defaultdict

from .constants import (
    DEFAULT_CLUSTER_RADIUS_M, DEFAULT_CLUSTER_TIME_GAP_HRS,
    DEFAULT_INTERP_WINDOW_SECS, DEFAULT_PLACE_GPS_REJECT_M,
)
from .utils import haversine, centroid

def merge_location_sources(cache_result, cloud_result):
    """
    Combine a load_cache() result and a load_cloud_v2() result into one
    unified (pings, visits, trips) tuple, correlating data from both
    databases rather than picking only one.

    - Pings: concatenated (only Cache.sqlite supplies these today, but this
      stays additive so a future file with its own raw pings is handled too).
    - Visits: concatenated. Overlapping stops from each source are NOT
      deduplicated here — cluster_visits() already merges visits that are
      both spatially close and temporally contiguous into one "place," so a
      stop recorded by both Cache and Cloud-V2 naturally collapses into a
      single place there, and that place inherits the Cloud-V2 name/address
      enrichment automatically (see cluster_visits()'s device_place_name logic).
    - Trips: concatenated, each still tagged with source_db for traceability.

    If only one source has data (the other file is missing or empty for that
    category), this is equivalent to using that one source alone — no
    behavior change for callers that only have one file.
    """
    cache_pings,  cache_visits,  cache_trips  = cache_result
    cloud_pings,  cloud_visits,  cloud_trips  = cloud_result

    all_pings = sorted(cache_pings + cloud_pings, key=lambda p: p["ts"] or 0)
    all_visits = sorted(cache_visits + cloud_visits, key=lambda v: v["entry"] or 0)
    all_trips = cache_trips + cloud_trips   # trips aren't clustered, order doesn't matter downstream

    return all_pings, all_visits, all_trips





# ── Clustering visits into "places" ──────────────────────────────────────────
# Maximum gap between visits to consider them the same stay session is now
# passed in as a parameter (cluster_time_gap_secs) — see cluster_visits() below.

# ── Source / origin classification ───────────────────────────────────────────
# ZIMPORTEDBY enum values observed in Photos.sqlite
_IMPORTEDBY = {
    0: ('Unknown',        'Pre-iOS / Unknown'),
    1: ('Camera Captured','Device Camera'),
    2: ('Device Library', 'Local Save / Sync'),
    3: ('Third-Party App','App Import'),
    5: ('iCloud',         'Cloud Download'),
    6: ('Cable Transfer', 'iTunes / Finder Sync'),
    8: ('System Save',    'iOS System'),
    9: ('Camera Captured','FaceTime / System Camera'),
}

def correlate_app_sessions(sessions, places, pings_sorted,
                            gps_reject_m=DEFAULT_PLACE_GPS_REJECT_M,
                            interp_window_secs=DEFAULT_INTERP_WINDOW_SECS):
    """
    Give each app-usage session an inferred location, using the exact same
    two-step approach as assign_photos_to_places(): first check whether the
    session's midpoint timestamp falls inside a known Stay's time window
    (tagging place_id when so), then fall back to ping-stream interpolation
    for sessions that don't land inside any detected stay.

    A session's MIDPOINT (not start) is used as the correlation timestamp,
    since sessions can run long enough that start and end fall in different
    places — the midpoint is the least-wrong single instant to anchor a
    session that may not be perfectly localizable to one spot.

    Mutates and returns the same `sessions` list for convenience.
    """
    place_windows = []
    for p in places:
        for v in p["visits"]:
            exit_ts = v["exit"] or v["entry"] + 60
            place_windows.append((v["entry"], exit_ts, p["id"]))
        place_windows.append((p["entry"], p["exit"] or p["entry"] + 1, p["id"]))
    place_by_id = {p["id"]: p for p in places}

    GRACE = 300
    for s in sessions:
        t = (s["start"] + s["end"]) / 2

        candidate_pids = {pid for entry, exit_, pid in place_windows
                           if entry <= t <= exit_ + GRACE}
        best_pid = None
        if candidate_pids:
            # No GPS of its own to disambiguate by distance — pick the
            # candidate place whose window midpoint is temporally tightest,
            # same tie-break rule used for photos with no EXIF GPS.
            best_dt = float("inf")
            for pid in candidate_pids:
                p = place_by_id[pid]
                mid = (p["entry"] + (p["exit"] or p["entry"])) / 2
                dt = abs(t - mid)
                if dt < best_dt:
                    best_dt = dt
                    best_pid = pid

        s["place_id"] = best_pid
        if best_pid is not None:
            p = place_by_id[best_pid]
            s["lat"], s["lng"] = p["lat"], p["lng"]
            s["location_method"] = "stay"
        else:
            ilat, ilng, method, acc, pzpk, pts, phacc = interpolate_location(
                t, pings_sorted, window_secs=interp_window_secs)
            if ilat is not None:
                s["lat"], s["lng"] = ilat, ilng
                s["location_method"] = method
                s["location_accuracy"] = acc
            else:
                s["location_method"] = "unknown"

    return sessions


def cluster_visits(visits, radius_m=DEFAULT_CLUSTER_RADIUS_M,
                    time_gap_secs=DEFAULT_CLUSTER_TIME_GAP_HRS * 3600):
    """
    Group visits into logical "places."

    A visit is merged into an existing place only when BOTH conditions hold:
      1. Spatially close: within `radius_m` metres of the place centroid.
      2. Temporally contiguous: the gap between the visit's entry and the place's
         current exit is within `time_gap_secs`.

    This prevents the same home/office location visited on different days from
    being collapsed into one giant time window that swallows unrelated photos.
    Visits are processed in chronological order so the gap check is meaningful.

    Parameters
    ----------
    radius_m      : clustering radius in metres (CLI: -radius)
    time_gap_secs : max gap in seconds between visits to merge into the same
                    stay session (CLI: -visit, given in hours)
    """
    if not visits:
        return []

    # Process in chronological order so temporal gap check is reliable
    visits_sorted = sorted(visits, key=lambda v: v["entry"])

    places = []
    for v in visits_sorted:
        merged = False
        best_place = None
        best_dist  = float("inf")

        for p in places:
            dist = haversine(v["lat"], v["lng"], p["lat"], p["lng"])
            if dist > radius_m:
                continue
            # Temporal gap: how far is this visit's entry from the place's current exit?
            gap = v["entry"] - (p["exit"] or p["entry"])
            if gap > time_gap_secs:
                # Same physical location but a separate visit session — keep distinct
                continue
            # Prefer the spatially nearest matching place
            if dist < best_dist:
                best_dist  = dist
                best_place = p

        if best_place is not None:
            p = best_place
            p["visits"].append(v)
            p["entry"] = min(p["entry"], v["entry"])
            p["exit"]  = max(p["exit"] or v["exit"] or p["entry"],
                             v["exit"] or v["entry"])
            pts = [(vv["lat"], vv["lng"]) for vv in p["visits"]]
            p["lat"], p["lng"] = centroid(pts)
        else:
            places.append({
                "entry":  v["entry"],
                "exit":   v["exit"] or v["entry"],
                "lat":    v["lat"],
                "lng":    v["lng"],
                "visits": [v],
            })

    # Sort chronologically and assign stable IDs
    places.sort(key=lambda p: p["entry"])
    for i, p in enumerate(places):
        p["id"]       = i + 1
        p["duration"] = p["exit"] - p["entry"] if p["exit"] else None
        p["n_visits"] = len(p["visits"])

        # Consolidate any Cloud-V2 "learned place" enrichment from constituent
        # visits. When multiple visits to the same location were merged, prefer
        # the longest/most specific place_name and address seen among them —
        # this is purely cosmetic and never affects clustering or assignment.
        named = [v for v in p["visits"] if v.get("place_name")]
        if named:
            best = max(named, key=lambda v: len(v["place_name"]))
            p["device_place_name"] = best["place_name"]
            p["device_place_category"] = best.get("place_category")
            p["device_address"] = best.get("address")
        else:
            p["device_place_name"] = None
            p["device_place_category"] = None
            p["device_address"] = None

        devices = sorted({v["device_name"] for v in p["visits"] if v.get("device_name")})
        p["device_names"] = devices or None

        # Which source database(s) contributed to this place — lets the report
        # show when a stay is corroborated by both Cache.sqlite and Cloud-V2.sqlite
        # independently, which is stronger evidence than either source alone.
        p["source_dbs"] = sorted({v.get("source_db", "cache") for v in p["visits"]})

    return places


# ── GPS interpolation for photos without coordinates ─────────────────────────
def interpolate_location(photo_unix_ts, pings_sorted, window_secs=DEFAULT_INTERP_WINDOW_SECS):
    """
    Find the nearest GPS ping(s) within `window_secs` and interpolate.
    Uses binary search to locate the insertion point for photo_unix_ts, then
    checks only the small neighbourhood of pings within the time window.

    Parameters
    ----------
    window_secs : ± seconds to search for a usable ping (CLI: -window)

    Returns (lat, lng, method, accuracy_m, ping_zpk, ping_unix_ts, ping_hacc)
    where ping_zpk / ping_unix_ts / ping_hacc identify the Cache.sqlite anchor row.
    Returns (None, None, None, None, None, None, None) when no match found.
    """
    NO_MATCH = (None, None, None, None, None, None, None)

    if photo_unix_ts is None or not pings_sorted:
        return NO_MATCH

    t = photo_unix_ts

    # Binary search for insertion point
    lo, hi = 0, len(pings_sorted)
    while lo < hi:
        mid = (lo + hi) // 2
        if pings_sorted[mid]["ts"] < t:
            lo = mid + 1
        else:
            hi = mid
    # lo is now the index of the first ping with ts >= t

    best_idx = None
    best_dt  = float("inf")

    # Scan rightward (pings after t) stopping when beyond window
    for i in range(lo, len(pings_sorted)):
        dt = pings_sorted[i]["ts"] - t   # always >= 0
        if dt > window_secs:
            break
        if dt < best_dt:
            best_dt  = dt
            best_idx = i

    # Scan leftward (pings before t) stopping when beyond window
    for i in range(lo - 1, -1, -1):
        dt = t - pings_sorted[i]["ts"]   # always >= 0
        if dt > window_secs:
            break
        if dt < best_dt:
            best_dt  = dt
            best_idx = i

    if best_idx is None or best_dt > window_secs:
        return NO_MATCH

    p = pings_sorted[best_idx]

    # Interpolate between the surrounding pings if available
    prev  = pings_sorted[best_idx - 1] if best_idx > 0 else None
    next_ = pings_sorted[best_idx + 1] if best_idx < len(pings_sorted) - 1 else None

    if prev and next_:
        span = next_["ts"] - prev["ts"]
        if span > 0:
            frac = (t - prev["ts"]) / span
            lat  = prev["lat"] + frac * (next_["lat"] - prev["lat"])
            lng  = prev["lng"] + frac * (next_["lng"] - prev["lng"])
            # Report the temporally nearer anchor ping as the reference row.
            # IMPORTANT: the returned accuracy_m must describe THIS SAME anchor
            # ping (anchor["hacc"]), not some other combination — otherwise the
            # "Location → Accuracy" field and the "Cache Anchor Pin → Accuracy"
            # field shown in the report disagree, which looks like a bug.
            anchor = prev if abs(t - prev["ts"]) <= abs(t - next_["ts"]) else next_
            acc = anchor["hacc"]
            return lat, lng, "interpolated", acc, anchor["zpk"], anchor["ts"], anchor["hacc"]

    return p["lat"], p["lng"], "nearest-ping", p["hacc"], p["zpk"], p["ts"], p["hacc"]


# ── Assign each photo to a place or movement ─────────────────────────────────
def assign_photos_to_places(photos, places, pings_sorted,
                             gps_reject_m=DEFAULT_PLACE_GPS_REJECT_M,
                             interp_window_secs=DEFAULT_INTERP_WINDOW_SECS):
    """
    For every photo:
    - Collect all places whose time window contains the photo timestamp.
    - Among those candidates, pick the BEST one:
        * If the photo has its own GPS coords, pick the spatially nearest place
          centroid — and reject any match farther than `gps_reject_m`.
        * If no GPS, pick the place with the smallest time-delta to the
          midpoint of its window (i.e. tightest temporal fit).
    - If no place matched, try to interpolate GPS from the ping stream
      (within ± `interp_window_secs`).
    - Otherwise mark as unlocated.

    Parameters
    ----------
    gps_reject_m        : metres (CLI: -reject) — see module docstring above
    interp_window_secs  : seconds (CLI: -window) — passed through to interpolate_location

    Populates photo["place_id"], photo["inferred_lat/lng"], photo["location_method"].
    """
    # Build per-visit windows as well so we can use the tighter individual visit
    # time boundaries rather than the merged place boundaries alone.
    # Each entry: (entry_unix, exit_unix, place_id)
    place_windows = []
    for p in places:
        for v in p["visits"]:
            exit_ts = v["exit"] or v["entry"] + 60
            place_windows.append((v["entry"], exit_ts, p["id"]))
        # Also add the merged place window as a fallback (covers gaps between visits)
        place_windows.append((p["entry"], p["exit"] or p["entry"] + 1, p["id"]))

    # Build a quick lookup: place_id → place dict
    place_by_id = {p["id"]: p for p in places}

    for photo in photos:
        t = photo["unix_ts"]
        photo["place_id"]          = None
        photo["inferred_lat"]      = photo["lat"]
        photo["inferred_lng"]      = photo["lng"]
        photo["location_method"]   = "exif-gps" if photo["has_gps"] else None
        photo["location_accuracy"] = None
        photo["ping_zpk"]          = None   # Cache.sqlite ZRTCLLOCATIONMO.Z_PK
        photo["ping_ts"]           = None   # Unix timestamp of anchor ping
        photo["ping_hacc"]         = None   # ZHORIZONTALACCURACY of anchor ping

        if t is None:
            continue

        # ── Step 1: collect all candidate places whose window contains t ──────
        GRACE = 300   # 5-minute grace period on exit
        candidate_pids = set()
        for entry, exit_, pid in place_windows:
            if entry <= t <= exit_ + GRACE:
                candidate_pids.add(pid)

        # ── Step 2: choose the best candidate ─────────────────────────────────
        best_pid = None
        if candidate_pids:
            if photo["has_gps"] and photo["lat"] is not None:
                # Pick the spatially nearest place centroid
                plat, plng = photo["lat"], photo["lng"]
                best_dist = float("inf")
                for pid in candidate_pids:
                    p = place_by_id[pid]
                    d = haversine(plat, plng, p["lat"], p["lng"])
                    if d < best_dist:
                        best_dist = d
                        best_pid  = pid
                # Sanity check: reject if the nearest place is still too far away.
                # This handles cases where the photo's GPS puts it clearly elsewhere.
                if best_dist > gps_reject_m:
                    best_pid = None
            else:
                # No photo GPS — pick the place whose window midpoint is closest
                # in time to the photo (tightest temporal fit among candidates)
                best_dt = float("inf")
                for pid in candidate_pids:
                    p = place_by_id[pid]
                    mid = (p["entry"] + (p["exit"] or p["entry"])) / 2
                    dt  = abs(t - mid)
                    if dt < best_dt:
                        best_dt = dt
                        best_pid = pid

        photo["place_id"] = best_pid

        # ── Step 3: infer GPS from ping stream if photo has no own coords ─────
        if not photo["has_gps"]:
            ilat, ilng, method, acc, pzpk, pts, phacc = interpolate_location(
                t, pings_sorted, window_secs=interp_window_secs)
            if ilat is not None:
                photo["inferred_lat"]      = ilat
                photo["inferred_lng"]      = ilng
                photo["location_method"]   = method
                photo["location_accuracy"] = acc
                photo["ping_zpk"]          = pzpk
                photo["ping_ts"]           = pts
                photo["ping_hacc"]         = phacc
            else:
                photo["location_method"] = "unknown"

    return photos


# ── Build place photo lists ───────────────────────────────────────────────────
def attach_photos_to_places(places, photos):
    pm = defaultdict(list)
    unplaced = []
    for photo in photos:
        if photo["place_id"] is not None:
            pm[photo["place_id"]].append(photo)
        else:
            unplaced.append(photo)
    for p in places:
        p["photos"] = sorted(pm[p["id"]], key=lambda x: x["unix_ts"] or 0)
    return places, unplaced


# ── Build GPS track (downsampled for map) ────────────────────────────────────
def build_track(pings, max_points=4000):
    """Downsample ping list to max_points for JSON embed."""
    if len(pings) <= max_points:
        return pings
    step = len(pings) // max_points
    return pings[::step]


# ── HTML generation ──────────────────────────────────────────────────────────

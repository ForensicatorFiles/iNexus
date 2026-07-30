"""
Top-level report assembly. build_html() is the single public entry point:
it takes every analysis result this run produced (photos, places, pings,
and whichever optional sources were supplied) and returns one
self-contained HTML string — no external CSS/JS files, everything needed
to view the report is embedded, by design, since this report needs to be
portable evidence output (a single file that can be copied, hashed, and
handed off without carrying a folder of assets alongside it).

Internally this just wires together the other report/ modules:
  - data_injection.build_data_injection() -> the JS `const ... = ...;` payload
  - integrity.build_integrity_html()      -> the Integrity & Parameters panel
  - body.build_body_html()                -> the tabbed <body> markup
  - place_cards / styles / scripts        -> static or near-static pieces
"""
import json

from ..constants import TOOL_NAME
from ..utils import esc_html, fmt_dt
from ..analysis import build_track
from .styles import MAIN_STYLES
from .scripts import STATIC_SCRIPT
from .data_injection import build_data_injection
from .integrity import build_integrity_html
from .body import build_body_html


_RECOVERED_SOURCE_LABELS = {
    "cache":        "Cache.sqlite",
    "cloud_v2":     "Cloud-V2.sqlite",
    "photos":       "Photos.sqlite",
}
# Every recovered-row dict field that might hold this source's timestamp,
# in priority order (cache/photos use "ts", cloud_v2 uses "entry" — see
# each recovery/*.py module's return shape).
_RECOVERED_TS_FIELDS = ("ts", "entry")


def _extract_recovered_points(recovered_data):
    """
    Pulls every recovered row that has a real lat/lng out of recovered_data
    (cache/cloud_v2/photos are the only recovery/*.py modules that carry
    coordinates at all) into one flat list for the map's optional
    "Recovered points" layer. Returns [] if recovered_data is empty/None,
    or if nothing recovered happened to include coordinates.
    """
    if not recovered_data:
        return []

    points = []
    for source_key, label in _RECOVERED_SOURCE_LABELS.items():
        for row in recovered_data.get(source_key, []):
            lat, lng = row.get("lat"), row.get("lng")
            if lat is None or lng is None:
                continue
            ts = None
            for field in _RECOVERED_TS_FIELDS:
                if row.get(field) is not None:
                    ts = row[field]
                    break
            points.append({
                "lat": lat, "lng": lng,
                "source": label,
                "ts_str": fmt_dt(ts) if ts else None,
                "page": row.get("page"), "rowid": row.get("rowid"),
                "truncated": bool(row.get("truncated")),
            })
    return points


def build_html(photos, places, unplaced, pings, trips, photos_db_path, cache_db_path,
                run_params=None, file_hashes=None, case_info=None, cloud_db_path=None,
                app_sessions=None, knowledgec_db_path=None, messages=None, sms_db_path=None,
                calls=None, calls_db_path=None, addressbook_db_path=None,
                interactions=None, interactions_db_path=None, heic_map=None,
                wal_sources=None, recovered_data=None):
    """
    run_params         : dict of the actual parameter values used for this run
                          (radius_m, time_gap_hours, interp_window_secs, gps_reject_m,
                           min_stay_minutes) — always populated, defaults or overridden.
    file_hashes        : dict {cache_sha256[, photos_sha256, cloud_v2_sha256,
                          knowledgec_sha256, sms_sha256, calls_sha256, addressbook_sha256,
                          interactions_sha256]} — None entries shown as "could not be
                          computed" rather than silently omitted.
    case_info          : optional dict {case_number, examiner, notes} for the report header.
    cloud_db_path      : optional path to a supplemental Cloud-V2.sqlite, when one
                          was merged into this analysis. None if Cache.sqlite alone
                          was used for this run.
    app_sessions       : optional list of correlated app-usage session dicts from
                          load_knowledgec() + correlate_app_sessions(). None/empty
                          if knowledgeC.db wasn't supplied for this run.
    knowledgec_db_path : optional path to knowledgeC.db, when app_sessions came
                          from one. None if not used for this run.
    messages           : optional list of correlated message dicts from
                          load_sms() + correlate_app_sessions(). None/empty if
                          sms.db wasn't supplied for this run. Sender resolution
                          (raw/device/addressbook) is already baked into each
                          message dict by load_sms() — build_html() just displays it.
    sms_db_path        : optional path to sms.db, when messages came from one.
                          None if not used for this run.
    calls              : optional list of correlated call dicts from
                          load_calls() + correlate_app_sessions(). None/empty if
                          CallHistory.storedata wasn't supplied for this run. Caller
                          resolution is likewise already resolved by load_calls().
    calls_db_path      : optional path to CallHistory.storedata, when calls came
                          from one. None if not used for this run.
    addressbook_db_path : optional path to AddressBook.sqlitedb, when it was used
                          to resolve message/call contact names this run. None if
                          not used — note this only affects the integrity panel
                          and chain-of-custody disclosure here, since the actual
                          resolution already happened in load_sms()/load_calls().
    interactions        : optional list of correlated cross-app interaction dicts
                          from load_interactions() + correlate_app_sessions().
                          None/empty if interactionC.db wasn't supplied. Each
                          carries is_overlap, flagging rows already covered by
                          messages/calls (native SMS/FaceTime/InCallService).
    interactions_db_path : optional path to interactionC.db, when interactions
                          came from one. None if not used for this run.
    """
    run_params   = run_params   or {}
    file_hashes  = file_hashes  or {}
    case_info    = case_info    or {}
    app_sessions = app_sessions or []
    calls        = calls or []
    interactions = interactions or []
    messages     = messages     or []
    track = build_track(pings)

    # All photos with inferred coordinates for the map
    map_photos = [p for p in photos
                  if p.get("inferred_lat") and p["inferred_lat"] not in (None, 0, -180)]

    # Determine overall date range — prefer photo timestamps, but fall back
    # to the GPS ping stream when photos.sqlite wasn't supplied for this run.
    all_ts  = [p["ts"] for p in photos if p["ts"]]
    if not all_ts and pings:
        from datetime import datetime as _dt
        all_ts = [_dt.fromtimestamp(pg["ts"]) for pg in pings if pg.get("ts")]
    date_min = min(all_ts).strftime("%Y-%m-%d") if all_ts else "—"
    date_max = max(all_ts).strftime("%Y-%m-%d") if all_ts else "—"

    # Stats
    n_gps_orig    = sum(1 for p in photos if p["has_gps"])
    n_inferred    = sum(1 for p in photos if not p["has_gps"] and p.get("inferred_lat"))
    n_unlocated   = sum(1 for p in photos if not p.get("inferred_lat"))
    n_overlap     = len([p for p in photos if p["unix_ts"] and pings
                         and pings[0]["ts"] <= p["unix_ts"] <= pings[-1]["ts"]])

    # JSON payloads
    places_json  = json.dumps([{
        "id":       p["id"],
        "lat":      p["lat"],
        "lng":      p["lng"],
        "entry":    p["entry"],
        "exit":     p["exit"],
        "duration": p["duration"],
        "n_visits": p["n_visits"],
        "n_photos": len(p["photos"]),
        "photo_ids":[ph["id"] for ph in p["photos"]],
        # Cloud-V2.sqlite "learned place" enrichment, when available — a name
        # and address resolved from the device's own cached map data rather
        # than a live third-party geocoding lookup. None when not available
        # (e.g. when sourced from the legacy Cache.sqlite schema).
        "device_place_name":     p.get("device_place_name"),
        "device_place_category": p.get("device_place_category"),
        "device_address":        p.get("device_address"),
        "device_names":          p.get("device_names"),
        # Which database(s) corroborate this stay — ["cache"], ["cloud_v2"],
        # or ["cache", "cloud_v2"] when both sources independently recorded it.
        "source_dbs":            p.get("source_dbs", ["cache"]),
    } for p in places], default=str)

    photos_json = json.dumps([{
        "id":        p["id"],
        "filename":  p["filename"],
        "ts":        p["unix_ts"],
        "ts_str":    fmt_dt(p["ts"]) if p["ts"] else "—",
        "lat":       p["inferred_lat"],
        "lng":       p["inferred_lng"],
        "has_gps":   p["has_gps"],
        "method":    p.get("location_method", "unknown"),
        "place_id":  p.get("place_id"),
        "kind":      p.get("kind", 0),
        "uti":       p.get("uti", ""),
        "trashed":   p.get("trashed", False),
        "w":         p.get("w"),
        "h":         p.get("h"),
        "duration":  p.get("duration", 0),
        "directory": p.get("directory",""),
        "accuracy":  p.get("location_accuracy"),
        # Cache.sqlite anchor ping that provided or corroborated this location
        "ping_zpk":  p.get("ping_zpk"),   # ZRTCLLOCATIONMO.Z_PK
        "ping_ts":   p.get("ping_ts"),    # Unix timestamp of that ping
        "ping_hacc": p.get("ping_hacc"),  # ZHORIZONTALACCURACY of that ping (metres)
        # Asset origin / source classification
        "src_cat":   p.get("source_category",    "Unknown"),
        "src_sub":   p.get("source_subcategory", ""),
        "src_bundle":p.get("source_bundle_id"),
        "src_app":   p.get("source_display_name"),
        "src_conf":  p.get("source_confidence",  "low"),
        "importedby":p.get("importedby"),
    } for p in photos], default=str)

    track_json = json.dumps([[round(p["lat"],6), round(p["lng"],6)] for p in track])

    app_sessions_json = json.dumps([{
        "zpk":          s["zpk"],
        "bundle_id":    s["bundle_id"],
        "category":     s["category"],
        "subcategory":  s["subcategory"],
        "confidence":   s["confidence"],
        "start":        s["start"],
        "end":          s["end"],
        "start_str":    s["start_str"],
        "end_str":      s["end_str"],
        "duration":     s["duration"],
        "lat":          s.get("lat"),
        "lng":          s.get("lng"),
        "location_method": s.get("location_method"),
        "place_id":     s.get("place_id"),
    } for s in app_sessions], default=str)

    messages_json = json.dumps([{
        "id":               m["id"],
        "sender":           m["sender"],
        "sender_raw":       m["sender_raw"],
        "sender_source":    m["sender_source"],
        "text":             m["text"],
        "display_text":     m["display_text"],
        "service":          m["service"],
        "chat_name":        m["chat_name"],
        "is_group":         m["is_group"],
        "n_participants":   m["n_participants"],
        "is_from_me":       m["is_from_me"],
        "has_attachment":   m["has_attachment"],
        "attachment_count": m["attachment_count"],
        "attachment_names": m["attachment_names"],
        "is_tapback":       m["is_tapback"],
        "tapback_type":     m["tapback_type"],
        "is_system":        m["is_system"],
        "is_read":          m["is_read"],
        "category":         m["category"],
        "subcategory":      m["subcategory"],
        "confidence":       m["confidence"],
        "ts":               m["ts"],
        "lat":              m.get("lat"),
        "lng":              m.get("lng"),
        "location_method":  m.get("location_method"),
        "place_id":         m.get("place_id"),
    } for m in messages], default=str)

    calls_json = json.dumps([{
        "id":               c["id"],
        "ts":               c["ts"],
        "duration":         c["duration"],
        "address":          c["address"],
        "name":             c["name"],
        "caller":           c["caller"],
        "caller_source":    c["caller_source"],
        "direction":        c["direction"],
        "status":           c["status"],
        "call_type_label":  c["call_type_label"],
        "service_provider": c["service_provider"],
        "category":         c["category"],
        "subcategory":      c["subcategory"],
        "confidence":       c["confidence"],
        "is_read":          c["is_read"],
        "disconnect_cause": c["disconnect_cause"],
        "lat":              c.get("lat"),
        "lng":              c.get("lng"),
        "location_method":  c.get("location_method"),
        "place_id":         c.get("place_id"),
    } for c in calls], default=str)

    interactions_json = json.dumps([{
        "id":               i["id"],
        "ts":               i["ts"],
        "end_ts":           i["end_ts"],
        "bundle_id":        i["bundle_id"],
        "category":         i["category"],
        "subcategory":      i["subcategory"],
        "confidence":       i["confidence"],
        "direction":        i["direction"],
        "is_overlap":       i["is_overlap"],
        "counterpart":      i["counterpart"],
        "counterpart_raw":  i["counterpart_raw"],
        "counterpart_source": i["counterpart_source"],
        "recipient_count":  i["recipient_count"],
        "group_name":       i["group_name"],
        "is_response":      i["is_response"],
        "lat":              i.get("lat"),
        "lng":              i.get("lng"),
        "location_method":  i.get("location_method"),
        "place_id":         i.get("place_id"),
    } for i in interactions], default=str)

    pings_ts_min = pings[0]["ts"] if pings else None
    pings_ts_max = pings[-1]["ts"] if pings else None

    # HEIC→JPEG preview map (empty unless -convert-heic ran this session)
    heic_map_json = json.dumps(heic_map or {})

    # Recovered points with coordinates (empty unless -recover-deleted found
    # any) — a separate, optional map layer, never merged into TRACK/PLACES.
    recovered_points = _extract_recovered_points(recovered_data)
    recovered_points_json = json.dumps(recovered_points, default=str)

    integrity_html = build_integrity_html(
        run_params=run_params, file_hashes=file_hashes, case_info=case_info,
        cache_db_path=cache_db_path, photos_db_path=photos_db_path,
        cloud_db_path=cloud_db_path, knowledgec_db_path=knowledgec_db_path,
        sms_db_path=sms_db_path, calls_db_path=calls_db_path,
        addressbook_db_path=addressbook_db_path,
        interactions_db_path=interactions_db_path,
        wal_sources=wal_sources,
    )

    body_html = build_body_html(
        photos=photos, places=places, pings=pings, app_sessions=app_sessions,
        messages=messages, calls=calls, interactions=interactions,
        photos_db_path=photos_db_path, cache_db_path=cache_db_path,
        cloud_db_path=cloud_db_path, sms_db_path=sms_db_path,
        calls_db_path=calls_db_path, interactions_db_path=interactions_db_path,
        addressbook_db_path=addressbook_db_path,
        date_min=date_min, date_max=date_max, integrity_html=integrity_html,
        n_gps_orig=n_gps_orig, n_inferred=n_inferred, n_unlocated=n_unlocated,
        n_overlap=n_overlap, recovered_data=recovered_data,
        has_recovered_points=bool(recovered_points),
    )

    data_injection_js = build_data_injection(
        places_json=places_json, photos_json=photos_json, track_json=track_json,
        app_sessions_json=app_sessions_json, messages_json=messages_json,
        calls_json=calls_json, interactions_json=interactions_json,
        heic_map_json=heic_map_json, recovered_points_json=recovered_points_json,
        pings_ts_min=pings_ts_min, pings_ts_max=pings_ts_max,
        case_info=case_info, cache_db_path=cache_db_path, file_hashes=file_hashes,
        photos_db_path=photos_db_path, cloud_db_path=cloud_db_path,
        knowledgec_db_path=knowledgec_db_path, sms_db_path=sms_db_path,
        calls_db_path=calls_db_path, addressbook_db_path=addressbook_db_path,
        interactions_db_path=interactions_db_path, run_params=run_params,
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc_html(TOOL_NAME)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
{MAIN_STYLES}
</head>
{body_html}
<script>
{data_injection_js}
{STATIC_SCRIPT}
</script>
</body>
</html>"""
    return html

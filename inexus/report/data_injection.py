"""
Builds the small `<script>` header that injects this run's data payloads
(as JSON) into fixed JS global constants (PLACES, PHOTOS, TRACK, ...) plus
a REPORT_META object carrying case info and chain-of-custody hashes. This
is the one part of the client-side script that varies per report; the rest
of the script (report/scripts.py) is fully static.
"""
import json

from ..constants import TOOL_NAME, TOOL_VERSION


def build_data_injection(*, places_json, photos_json, track_json,
                          app_sessions_json, messages_json, calls_json,
                          interactions_json, heic_map_json,
                          recovered_points_json,
                          pings_ts_min, pings_ts_max,
                          case_info, cache_db_path, file_hashes,
                          photos_db_path, cloud_db_path, knowledgec_db_path,
                          sms_db_path, calls_db_path, addressbook_db_path,
                          interactions_db_path, run_params, carto_api_key=None):
    """Returns the JS `const ... = ...;` declarations (no <script> tags)."""
    file_hashes = file_hashes or {}
    case_info = case_info or {}

    report_meta = json.dumps({
        "tool_name":    TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "case_number":  case_info.get("case_number"),
        "examiner":     case_info.get("examiner"),
        "notes":        case_info.get("notes"),
        "cache_db_path":   cache_db_path,
        "cache_sha256":    file_hashes.get("cache_sha256"),
        "photos_db_path":  photos_db_path,
        "photos_sha256":   file_hashes.get("photos_sha256"),
        "cloud_db_path":   cloud_db_path,
        "cloud_sha256":    file_hashes.get("cloud_v2_sha256"),
        "kc_db_path":      knowledgec_db_path,
        "kc_sha256":       file_hashes.get("knowledgec_sha256"),
        "sms_db_path":     sms_db_path,
        "sms_sha256":      file_hashes.get("sms_sha256"),
        "calls_db_path":   calls_db_path,
        "calls_sha256":    file_hashes.get("calls_sha256"),
        "addressbook_db_path": addressbook_db_path,
        "addressbook_sha256":  file_hashes.get("addressbook_sha256"),
        "interactions_db_path": interactions_db_path,
        "interactions_sha256":  file_hashes.get("interactions_sha256"),
        "run_params":      run_params or {},
    })

    return f"""// ── Data ─────────────────────────────────────────────────────────────────────
const PLACES  = {places_json};
const PHOTOS  = {photos_json};
const TRACK   = {track_json};
const APP_SESSIONS = {app_sessions_json};
const MESSAGES = {messages_json};
const CALLS = {calls_json};
const INTERACTIONS = {interactions_json};
const HEIC_MAP = {heic_map_json};
const RECOVERED_POINTS = {recovered_points_json};
const PINGS_START = {pings_ts_min or 'null'};
const PINGS_END   = {pings_ts_max or 'null'};
const REPORT_META = {report_meta};
window.INEXUS_CARTO_KEY = {json.dumps(carto_api_key or "")};
"""

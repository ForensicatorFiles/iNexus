"""Builds the "Integrity & Analysis Parameters" overlay panel shown in
every report: case info, per-source SHA-256 chain-of-custody hashes, and
disclosure of every tunable analysis parameter (default vs overridden)."""
from datetime import datetime

from ..constants import (
    TOOL_NAME, TOOL_VERSION,
    DEFAULT_CLUSTER_RADIUS_M, DEFAULT_CLUSTER_TIME_GAP_HRS,
    DEFAULT_INTERP_WINDOW_SECS, DEFAULT_PLACE_GPS_REJECT_M,
    DEFAULT_MIN_STAY_MINUTES,
)
from ..utils import esc_html


def build_integrity_html(*, run_params, file_hashes, case_info,
                          cache_db_path, photos_db_path, cloud_db_path,
                          knowledgec_db_path, sms_db_path, calls_db_path,
                          addressbook_db_path, interactions_db_path,
                          wal_sources=None):
    """Returns the full <div id="integrity-overlay">...</div> markup."""
    run_params  = run_params or {}
    file_hashes = file_hashes or {}
    case_info   = case_info or {}
    wal_sources = wal_sources or []

    def _hash_row(label, value):
        if value:
            return (f'<tr><td class="lbl">{label}</td>'
                     f'<td class="val hash-ok">{value}</td></tr>')
        return (f'<tr><td class="lbl">{label}</td>'
                f'<td class="val hash-missing">⚠ could not be computed '
                f'(file unavailable or unreadable at report-generation time)</td></tr>')

    def _param_row(label, value, is_default, unit=""):
        cls = "param-default" if is_default else "param-overridden"
        flag = "" if is_default else " <b>(MODIFIED FROM DEFAULT)</b>"
        return (f'<tr><td class="lbl">{label}</td>'
                f'<td class="val {cls}">{value}{unit}{flag}</td></tr>')

    radius_m       = run_params.get("radius_m", DEFAULT_CLUSTER_RADIUS_M)
    gap_hours      = run_params.get("time_gap_hours", DEFAULT_CLUSTER_TIME_GAP_HRS)
    window_secs    = run_params.get("interp_window_secs", DEFAULT_INTERP_WINDOW_SECS)
    reject_m       = run_params.get("gps_reject_m", DEFAULT_PLACE_GPS_REJECT_M)
    min_stay       = run_params.get("min_stay_minutes", DEFAULT_MIN_STAY_MINUTES)

    start_date     = run_params.get("start_date")
    end_date       = run_params.get("end_date")
    date_row       = ""
    if start_date or end_date:
        date_row = f'<tr><td class="lbl">Date Range Filter</td><td class="val param-overridden">{start_date or "Beginning of record"} to {end_date or "End of record"}</td></tr>'

    return f"""
    <div id="integrity-overlay">
      <div id="integrity-panel">
    <button id="integrity-close" onclick="document.getElementById('integrity-overlay').classList.remove('open')">✕ CLOSE</button>
    <h2>🔒 INTEGRITY &amp; ANALYSIS PARAMETERS</h2>
    <div class="sub">Generated {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} local time · Disclose this panel alongside any findings derived from this report.</div>

    <h3>Case Information</h3>
    <table>
      <tr><td class="lbl">Case Number</td><td class="val">{case_info.get("case_number") or "— not specified —"}</td></tr>
      <tr><td class="lbl">Examiner</td><td class="val">{case_info.get("examiner") or "— not specified —"}</td></tr>
      <tr><td class="lbl">Notes</td><td class="val">{case_info.get("notes") or "—"}</td></tr>
    </table>

    <h3>Source File Integrity (SHA-256)</h3>
    <table>
      {f'<tr><td class="lbl">Photos.sqlite path</td><td class="val">{photos_db_path}</td></tr>' + _hash_row("Photos.sqlite SHA-256", file_hashes.get("photos_sha256")) if photos_db_path else ''}
      {f'<tr><td class="lbl">Cache.sqlite path</td><td class="val">{cache_db_path}</td></tr>' + _hash_row("Cache.sqlite SHA-256", file_hashes.get("cache_sha256")) if cache_db_path else ''}
      {f'<tr><td class="lbl">Cloud-V2.sqlite path</td><td class="val">{cloud_db_path}</td></tr>' + _hash_row("Cloud-V2.sqlite SHA-256", file_hashes.get("cloud_v2_sha256")) if cloud_db_path else ''}
      {f'<tr><td class="lbl">knowledgeC.db path</td><td class="val">{knowledgec_db_path}</td></tr>' + _hash_row("knowledgeC.db SHA-256", file_hashes.get("knowledgec_sha256")) if knowledgec_db_path else ''}
      {f'<tr><td class="lbl">sms.db path</td><td class="val">{sms_db_path}</td></tr>' + _hash_row("sms.db SHA-256", file_hashes.get("sms_sha256")) if sms_db_path else ''}
      {f'<tr><td class="lbl">CallHistory.storedata path</td><td class="val">{calls_db_path}</td></tr>' + _hash_row("CallHistory.storedata SHA-256", file_hashes.get("calls_sha256")) if calls_db_path else ''}
      {f'<tr><td class="lbl">AddressBook.sqlitedb path</td><td class="val">{addressbook_db_path}</td></tr>' + _hash_row("AddressBook.sqlitedb SHA-256", file_hashes.get("addressbook_sha256")) if addressbook_db_path else ''}
      {f'<tr><td class="lbl">interactionC.db path</td><td class="val">{interactions_db_path}</td></tr>' + _hash_row("interactionC.db SHA-256", file_hashes.get("interactions_sha256")) if interactions_db_path else ''}
    </table>
    <div style="color:var(--dim);font-size:9px;margin-top:4px">
      These hashes were computed at report-generation time from the file paths above.
      To verify integrity, recompute SHA-256 on the same source files and confirm the
      digests match. A mismatch indicates the file was modified after this report was generated
      (or a different file was substituted) — it does NOT by itself indicate tampering with the
      original extraction, only that the bytes analyzed here differ from whatever is being compared.
      {"This report merges location data from both Cache.sqlite and Cloud-V2.sqlite; stays independently recorded in both sources are marked CORROBORATED in the Places view." if cloud_db_path else ""}
      {"App usage sessions from knowledgeC.db were correlated to detected stays and the GPS ping stream using the same interpolation logic applied to photos." if knowledgec_db_path else ""}
      {f"A sibling -wal/-shm file was found alongside: {', '.join(wal_sources)}. Committed data from the WAL was included by reconciling it in a temporary working copy — the original files listed above were never opened for writing, and the SHA-256 hashes above are of those original files exactly as supplied." if wal_sources else ""}
    </div>

    <h3>Analysis Parameters Used For This Run</h3>
    <table>
      {date_row}
      {_param_row("Clustering radius (-radius)", radius_m, radius_m == DEFAULT_CLUSTER_RADIUS_M, " m")}
      {_param_row("Visit merge gap (-visit)", gap_hours, gap_hours == DEFAULT_CLUSTER_TIME_GAP_HRS, " hours")}
      {_param_row("GPS interpolation window (-window)", window_secs, window_secs == DEFAULT_INTERP_WINDOW_SECS, " sec")}
      {_param_row("Place GPS rejection distance (-reject)", reject_m, reject_m == DEFAULT_PLACE_GPS_REJECT_M, " m")}
      {_param_row("Minimum stay duration (-minstay)", min_stay, min_stay == DEFAULT_MIN_STAY_MINUTES, " min")}
    </table>
    <div style="color:var(--dim);font-size:9px;margin-top:6px">
      <b>What these mean:</b> the clustering radius determines how close two GPS visits must be
      to be considered the "same place." The visit merge gap caps how much time may elapse between
      visits to the same place before they're treated as separate, distinct stays (preventing e.g.
      a January visit home from being merged with a June visit home into one giant window). The GPS
      interpolation window is how far forward/backward (in seconds) the tool will search for a usable
      location ping when a photo has no embedded GPS. The rejection distance discards a time-window
      place match if the photo's own GPS coordinates are implausibly far from that place. Values shown
      in yellow were explicitly overridden via command-line flags and differ from this tool's defaults —
      any finding sensitive to these parameters should be re-run at default settings to confirm it holds.
    </div>

    {f'''<div style="color:var(--dim);font-size:9px;margin-top:10px;border-top:1px solid var(--border);padding-top:8px">
      <b>Contact resolution:</b> names shown for message senders and call participants come from three
      possible sources, distinguished in each message/call's detail view: <b>device</b> — a name iOS itself
      had already cached on the call/message record at the time it was recorded; <b>addressbook</b> — resolved
      here by matching the raw number/email against AddressBook.sqlitedb (phone numbers matched after
      stripping punctuation/spacing/country-code formatting differences); <b>raw</b> — no name available,
      showing the unresolved number/email as recorded. The raw value is preserved alongside the resolved
      name in every case — resolution only labels the artifact, it never replaces or hides what was
      actually recorded in sms.db/CallHistory.storedata. AddressBook.sqlitedb reflects the state of Contacts
      at the time of extraction, which is not necessarily the state of Contacts at the time of each
      message/call — a contact added or renamed afterward will resolve using its current name, not
      whatever (if anything) was true historically.
    </div>''' if addressbook_db_path else ''}

    <div class="case-note">
      {esc_html(TOOL_NAME)} v{TOOL_VERSION} · Self-contained HTML report · No data in this report was transmitted
      off this device during generation.
    </div>
      </div>
    </div>
    """

"""
Renders the "RECOVERED DATA" tab shown only when -recover-deleted found
something. Deliberately a separate, simple, server-rendered view (plain
HTML tables, no client-side JS data model) rather than woven into the
map/timeline/places views — recovered rows are a fundamentally different
evidentiary category (carved from freed pages, not read from a live
table) and this tool never lets them look like confirmed data, including
visually.

Columns are click-to-sort (ascending/descending, tri-state via repeated
clicks) using the generic sortRecoveredTable() JS in scripts.py — no
per-column JS needed here, just a data-col/data-type attribute per header
and a data-sort attribute per cell holding a machine-sortable value
separate from its human-readable display text (e.g. an ISO timestamp
behind a "Mar 9, 2023 02:26" display).

Export buttons (CSV / standalone HTML) are likewise handled by generic,
already-static JS in scripts.py — this module only needs to lay out
tables the export functions can find via #view-recovered's DOM structure.
"""
from ..utils import esc_html, fmt_dt

_TABLE_WRAP_STYLE = "width:100%;border-collapse:collapse;font-size:10px;margin-bottom:18px"
_TH_STYLE = ("text-align:left;padding:4px 8px;border-bottom:1px solid var(--border);"
             "color:var(--dim);text-transform:uppercase;letter-spacing:0.5px;font-size:8px;"
             "cursor:pointer;user-select:none;white-space:nowrap")
_TD_STYLE = "padding:4px 8px;border-bottom:1px solid var(--border);color:var(--text)"


def _cell(value, kind="text"):
    """Returns (display_html, sort_key) for one cell. sort_key is always a
    plain string suitable for the <td>'s data-sort attribute — numeric/date
    kinds get a zero-padded or ISO form so lexicographic and numeric JS
    comparison both behave, text kinds just get the lowercased text."""
    if value is None:
        return '<span style="color:var(--dim)">—</span>', ""
    if kind == "dt":
        return esc_html(fmt_dt(value)), value.isoformat()
    if kind == "bool":
        return ("yes" if value else "no"), ("1" if value else "0")
    if kind == "num":
        return esc_html(str(value)), repr(value)
    return esc_html(str(value)), str(value).lower()


def _render_source_table(source_key, label, rows, columns):
    """columns: list of (header, dict_key, kind) tuples."""
    if not rows:
        return ""
    header_html = "".join(
        f'<th data-col="{i}" data-type="{kind}" onclick="sortRecoveredTable(this)">'
        f'{h} <span class="sort-arrow"></span></th>'
        for i, (h, _, kind) in enumerate(columns)
    )
    header_html += (f'<th data-col="{len(columns)}" data-type="text" '
                     f'onclick="sortRecoveredTable(this)">TRUNCATED '
                     f'<span class="sort-arrow"></span></th>')

    body_rows = []
    for r in rows:
        cells = []
        for _, k, kind in columns:
            html, sort_key = _cell(r.get(k), kind)
            cells.append(f'<td data-sort="{esc_html(sort_key)}" style="{_TD_STYLE}">{html}</td>')
        trunc_html = '<span style="color:var(--orange)">⚠ partial</span>' if r.get("truncated") else "—"
        trunc_sort = "1" if r.get("truncated") else "0"
        cells.append(f'<td data-sort="{trunc_sort}" style="{_TD_STYLE}">{trunc_html}</td>')
        body_rows.append(f'<tr>{"".join(cells)}</tr>')

    return f"""
    <h3 style="margin-top:18px">{esc_html(label)} <span style="color:var(--dim);
        font-weight:normal;font-size:9px">({len(rows)} candidate row(s))</span></h3>
    <table id="recovered-table-{source_key}" data-source="{esc_html(label)}"
           style="{_TABLE_WRAP_STYLE}">
      <thead><tr>{header_html}</tr></thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>"""


# One column spec per source, matching the dict keys each recovery/*.py
# module returns (see recovery/__init__.py for the full field lists).
# kind: "num" (numeric sort), "dt" (datetime sort), "bool", or "text".
_SOURCE_SPECS = {
    "cache": ("Cache.sqlite — location pings", [
        ("ROWID (Z_PK)", "rowid", "num"), ("PAGE", "page", "num"),
        ("TIMESTAMP", "ts", "dt"), ("LATITUDE", "lat", "num"),
        ("LONGITUDE", "lng", "num"), ("ACCURACY (m)", "hacc", "num"),
        ("SPEED", "speed", "num"),
    ]),
    "photos": ("Photos.sqlite — assets", [
        ("ROWID (Z_PK)", "rowid", "num"), ("PAGE", "page", "num"),
        ("FILENAME", "filename", "text"), ("DIRECTORY", "directory", "text"),
        ("DATE CREATED", "ts", "dt"), ("LATITUDE", "lat", "num"),
        ("LONGITUDE", "lng", "num"), ("TRASHED", "trashed", "bool"),
    ]),
    "cloud_v2": ("Cloud-V2.sqlite — learned visits", [
        ("ROWID (Z_PK)", "rowid", "num"), ("PAGE", "page", "num"),
        ("ENTRY", "entry", "dt"), ("EXIT", "exit", "dt"),
        ("LATITUDE", "lat", "num"), ("LONGITUDE", "lng", "num"),
    ]),
    "knowledgec": ("knowledgeC.db — app usage sessions", [
        ("ROWID (Z_PK)", "rowid", "num"), ("PAGE", "page", "num"),
        ("BUNDLE ID", "bundle_id", "text"), ("START", "start", "dt"),
        ("END", "end", "dt"),
    ]),
    "sms": ("sms.db — messages", [
        ("ROWID", "rowid", "num"), ("PAGE", "page", "num"),
        ("TEXT", "text", "text"), ("FROM ME", "is_from_me", "bool"),
        ("SERVICE", "service", "text"), ("TIMESTAMP", "ts", "dt"),
        ("BALLOON BUNDLE ID", "balloon_bundle_id", "text"),
    ]),
    "calls": ("CallHistory.storedata — calls", [
        ("ROWID (Z_PK)", "rowid", "num"), ("PAGE", "page", "num"),
        ("TIMESTAMP", "ts", "dt"), ("DURATION (s)", "duration", "num"),
        ("ADDRESS", "address", "text"), ("NAME", "name", "text"),
        ("SERVICE PROVIDER", "service_provider", "text"),
    ]),
    "addressbook": ("AddressBook.sqlitedb — contacts", [
        ("ROWID", "rowid", "num"), ("PAGE", "page", "num"),
        ("FIRST", "first", "text"), ("LAST", "last", "text"),
        ("DISPLAY NAME", "display_name", "text"), ("ORGANIZATION", "organization", "text"),
    ]),
    "interactions": ("interactionC.db — cross-app interactions", [
        ("ROWID (Z_PK)", "rowid", "num"), ("PAGE", "page", "num"),
        ("BUNDLE ID", "bundle_id", "text"), ("TARGET BUNDLE ID", "target_bundle_id", "text"),
        ("TIMESTAMP", "ts", "dt"), ("DIRECTION", "direction", "num"),
        ("RECIPIENT COUNT", "recipient_count", "num"),
    ]),
}


def render_recovered_view(recovered_data):
    """
    Returns the full '<div class="view" id="view-recovered">...</div>'
    markup, or '' if recovered_data is None/empty/every source came back
    with zero candidate rows (in which case the tab isn't shown at all —
    see body.py, which only includes the nav-tab button when this is
    non-empty).
    """
    if not recovered_data:
        return ""
    total = sum(len(v) for v in recovered_data.values())
    if total == 0:
        return ""

    sections = []
    for key, (label, columns) in _SOURCE_SPECS.items():
        rows = recovered_data.get(key)
        sections.append(_render_source_table(key, label, rows, columns))

    return f"""
  <div class="view" id="view-recovered" style="flex-direction:column;padding:16px;overflow:auto">
    <div class="unplaced-banner" style="margin-bottom:14px">
      ⚠ <b>UNVERIFIED — recovered from SQLite freelist pages, not the live database.</b>
      Every row below comes from a page that has been deleted from its original table but
      not yet overwritten on disk — this is inherently partial (only pages that happened to
      survive intact are recoverable) and cannot be cross-checked the way live data can.
      A row marked "⚠ partial" overflowed onto pages this tool did not attempt to reassemble,
      so some of its values may be missing entirely. Treat everything on this tab as an
      investigative lead requiring independent corroboration, not a confirmed fact — nothing
      here is merged into the Map, Places, Timeline, Photos, App Usage, Messages, Calls, or
      Interactions tabs, and nothing here contributes to any statistic shown elsewhere in
      this report.
    </div>
    <div style="margin-bottom:10px;display:flex;gap:8px">
      <button onclick="exportRecoveredCSV()"
              style="background:var(--panel2);color:var(--text);border:1px solid var(--border);
                     padding:5px 10px;font-family:var(--font);font-size:9px;cursor:pointer;
                     text-transform:uppercase;letter-spacing:0.5px">⬇ Export CSV</button>
      <button onclick="exportRecoveredHTML()"
              style="background:var(--panel2);color:var(--text);border:1px solid var(--border);
                     padding:5px 10px;font-family:var(--font);font-size:9px;cursor:pointer;
                     text-transform:uppercase;letter-spacing:0.5px">⬇ Export Standalone HTML</button>
      <span style="color:var(--dim);font-size:9px;align-self:center">Click a column header to sort.</span>
    </div>
    {"".join(sections)}
  </div>"""

# Adding a New Artifact Source and Report Tab to iNexus

This walks through both halves of extending iNexus, using the existing
`interactions` source (interactionC.db) as the reference implementation
throughout — it's the simplest complete example already in the codebase,
so every step below points at real, working code you can open side-by-side
with this guide.

**Worked example used throughout:** we'll pretend we're adding it fresh,
calling it `widget` / `Widget.db` / `ZWIDGET`, so you can see the pattern
independent of interactions' specific business logic. Swap in your real
source's names as you go.

---

## Part 1 — New artifact source

### Step 1: Write the loader

Create `inexus/loaders/widget.py`. Every loader follows the same shape:

```python
"""Load <what> records from Widget.db."""
import sqlite3

from ..db import _open_sqlite_or_die
from ..utils import unix_ts  # or unix_ts_ns if this source uses nanosecond
                              # CoreData timestamps like sms.db does — check
                              # your schema before assuming seconds
from ..classification import categorize_bundle_id  # only if this source has
                                                     # an app bundle-ID column


def load_widget(path):
    """
    Loads records from an iOS Widget.db.

    Returns a list of widget-event dicts. Returns an empty list (not an
    error) if the file opens but has no rows.
    """
    conn, cur = _open_sqlite_or_die(path)

    # Fail loudly and specifically if this isn't really the database the
    # flag claims it is — see every existing loader for this exact pattern.
    try:
        cur.execute("SELECT 1 FROM ZWIDGET LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        raise RuntimeError(
            f"{path} doesn't look like Widget.db — no 'ZWIDGET' table "
            f"found. Confirm this is the right database."
        )

    cur.execute("""
        SELECT Z_PK, ZTIMESTAMP, ZBUNDLEID, ZVALUE
        FROM ZWIDGET
        ORDER BY ZTIMESTAMP
    """)

    events = []
    for r in cur.fetchall():
        d = dict(r)
        ts = unix_ts(d["ZTIMESTAMP"])
        if ts is None:
            continue  # malformed/zero timestamp — skip rather than mis-sort to epoch

        category, subcategory, confidence = categorize_bundle_id(d["ZBUNDLEID"], None)

        events.append({
            "id":          d["Z_PK"],
            "ts":          ts,
            "bundle_id":   d["ZBUNDLEID"],
            "value":       d["ZVALUE"],
            "category":    category,
            "subcategory": subcategory,
            "confidence":  confidence,
            # Filled in by correlate_app_sessions() — see Step 3. Every
            # loader ends its dicts with these five placeholder keys.
            "start": ts, "end": ts,
            "lat": None, "lng": None, "location_method": None,
            "location_accuracy": None, "place_id": None,
        })

    conn.close()
    return events
```

Real considerations to get right (all visible in `loaders/interactions.py`
and `loaders/sms.py`):

- **Confirm the timestamp convention before writing a line of code.** Most
  sources (Cache.sqlite, Photos.sqlite, knowledgeC.db, CallHistory.storedata,
  interactionC.db) use whole-second CoreData timestamps (`unix_ts()`).
  sms.db is the one exception — nanoseconds (`unix_ts_ns()`). Getting this
  wrong silently produces a timestamp ~22 billion years in the future rather
  than an error, so verify against a real sample database rather than
  assuming.
- **Skip rows with no usable timestamp** rather than defaulting them to
  epoch — a `None` timestamp defaulted to `0` would sort to 1970 and corrupt
  every chronological view.
- **Never drop or hide a raw value when resolving it to something friendlier**
  (a contact name, a bundle-ID category). Keep both — see how
  `loaders/sms.py` and `loaders/interactions.py` always preserve
  `sender_raw`/`counterpart_raw` alongside the resolved name.
- If this source has an address-book-resolvable identifier (phone/email),
  accept an optional `address_book=None` parameter and follow the
  `_resolve()` pattern in `loaders/interactions.py`.

### Step 2: Add the CLI flag

In `inexus/cli.py`, add the import near the other loader imports:

```python
from .loaders.widget import load_widget
```

Add the argparse flag (put it near `-interactions` in `parse_args()`):

```python
p.add_argument("-widget", default=None, metavar="WIDGET_DB",
                help="Optional path to Widget.db. Adds a Widget tab and "
                     "per-stay widget-event correlation.")
```

### Step 3: Wire it into the run pipeline (`main()`)

This is the part with the most moving pieces — five separate places in
`main()` need a small addition. Search for every existing `interactions_path`
reference in `cli.py` as your checklist; here's each one with a `widget`
equivalent:

**a) Capture the path from args, right after the other `*_path` assignments:**
```python
widget_path = args.widget
```

**b) Add to the step counter** (loading + correlating = 2 steps, same as
knowledgeC/sms/calls/interactions):
```python
if widget_path:          n_steps += 2
```

**c) Hash the file** (in the hashing block, alongside the others):
```python
if widget_path:
    file_hashes.update(_hash_source("Widget.db", widget_path, "widget_sha256"))
```

**d) Load and correlate it** (this is the real work — mirrors the
interactions block exactly):
```python
widget_events = []
if widget_path:
    print(f"[{step}/{n_steps}] Loading widget events from {widget_path}…")
    try:
        widget_events = load_widget(widget_path)
        print(f"      {len(widget_events)} widget events loaded")
    except RuntimeError as e:
        print(f"      ⚠ {e}")
    step += 1

    print(f"[{step}/{n_steps}] Correlating widget events to places/locations…")
    widget_events = correlate_app_sessions(widget_events, places, pings_sorted,
                                            gps_reject_m=args.reject,
                                            interp_window_secs=args.window)
    n_in_stay = sum(1 for w in widget_events if w["place_id"] is not None)
    print(f"      {n_in_stay} widget events matched to a known stay")
    step += 1
```

`correlate_app_sessions()` is generic — the same function correlates app
sessions, messages, calls, *and* interactions against places/pings. You
don't write new correlation logic; you reuse it, which is why every
loader's dicts end with that `start`/`end`/`lat`/`lng`/... placeholder
block from Step 1 — those are exactly the fields `correlate_app_sessions()`
fills in.

**e) Pass it into `build_html()`** (find the call near the end of `main()`):
```python
html = build_html(..., widget_events=widget_events, widget_db_path=widget_path, ...)
```

**f) (Optional) Wire up `-recover-deleted`** — see Part 3 below if you want
freelist-recovery support for this source too; it's a separate, optional
addition, not required for the source/tab to work.

### Step 4: Accept the new data in `build_html()`

In `inexus/report/builder.py`, add `widget_events=None, widget_db_path=None`
to `build_html()`'s signature, default it to `[]` near the top of the
function body (same pattern as `interactions = interactions or []`), and
build its JSON payload — copy the `interactions_json` block as a template,
renaming fields to match your dict:

```python
widget_json = json.dumps([{
    "id":          w["id"],
    "ts":          w["ts"],
    "bundle_id":   w["bundle_id"],
    "value":       w["value"],
    "category":    w["category"],
    "subcategory": w["subcategory"],
    "confidence":  w["confidence"],
    "lat":         w.get("lat"),
    "lng":         w.get("lng"),
    "location_method": w.get("location_method"),
    "place_id":    w.get("place_id"),
} for w in widget_events], default=str)
```

Pass `widget_json` and `widget_db_path` through to `build_body_html()` and
`build_data_injection()` (both calls are further down the same function).

### Step 5: Inject it as a JS global

In `inexus/report/data_injection.py`, add a `widget_json` parameter to
`build_data_injection()` and one line to the returned f-string, next to the
existing `const INTERACTIONS = ...;` line:

```python
const WIDGET = {widget_json};
```

That's the entire data-plumbing half done. Part 2 covers making it visible.

---

## Part 2 — New report tab

Continuing the `widget` example — this is where the data from Part 1
actually becomes a tab a person can click on.

### Step 1: Add the nav-tab button

In `inexus/report/body.py`, `build_body_html()` needs a `widget_events`
parameter (add it to the signature). Then, next to the existing
Interactions nav-tab line:

```python
{f'''<div class="nav-tab" onclick="switchTab('widget', event)">🔧 WIDGET</div>''' if widget_events else ''}
```

Conditioning on `if widget_events else ''` is the established pattern
throughout — a tab only appears when that source was actually supplied
*and* returned rows, so running without `-widget` doesn't leave a dead,
empty tab in the nav bar.

### Step 2: Add the view `<div>`

Right before the `{recovered_view_html}` line near the end of
`build_body_html()`'s returned f-string, add the view markup. The
interactions view (`view-interactions`) is the closest template — a
sidebar list + detail panel is the standard shape for a one-record-at-a-time
browsing tab:

```python
{f'''<div class="view" id="view-widget" style="flex-direction:row">
  <div class="sidebar" id="widget-sidebar">
    <div class="search-bar">
      <input type="text" id="widget-search" placeholder="Search…" oninput="filterWidget()">
    </div>
    <div class="sidebar-head" id="widget-count-label">WIDGET EVENTS</div>
    <div class="sidebar-body" id="widget-list"></div>
  </div>
  <div class="detail-panel" id="widget-detail">
    <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select an event to view details</div>
  </div>
</div>''' if widget_events else ''}
```

(If your tab is more map-like or timeline-like than list-like, look at the
Photos or App Usage views in the same file instead — the sidebar+detail
shape isn't mandatory, just the most common.)

### Step 3: Add the render/filter/select JS functions

In `inexus/report/scripts.py`, three functions per list-style tab, modeled
directly on `renderInteractionList()` / `filterInteractions()` /
`selectInteraction()`:

```javascript
let selectedWidgetId = null;
let widgetSearch = '';

function filterWidget() {
  widgetSearch = document.getElementById('widget-search').value.toLowerCase();
  renderWidgetList();
}

function getFilteredWidget() {
  return WIDGET.filter(w =>
    !widgetSearch || (w.value || '').toLowerCase().includes(widgetSearch)
  );
}

function renderWidgetList() {
  const items = getFilteredWidget();
  const list = document.getElementById('widget-list');
  const label = document.getElementById('widget-count-label');
  if (!list || !label) return;
  label.textContent = `WIDGET EVENTS (${items.length} / ${WIDGET.length})`;
  list.innerHTML = items.map(w => `
    <div class="photo-row${selectedWidgetId===w.id?' selected':''}" onclick="selectWidget(${w.id})">
      <div class="pr-name">${esc(w.value || '(no value)')}</div>
      <div class="pr-meta">${fmtTs(w.ts)} · ${esc(w.category)}</div>
      ${w.place_id != null ? `<div class="pr-ping">📍 Stay #${w.place_id}</div>` : ''}
    </div>
  `).join('');
}

function selectWidget(id) {
  selectedWidgetId = id;
  renderWidgetList();
  const w = WIDGET.find(x => x.id === id);
  if (!w) return;
  const det = document.getElementById('widget-detail');
  det.innerHTML = `
    <div class="detail-block">
      <div class="detail-label">VALUE</div>
      <div>${esc(w.value)}</div>
      <div class="detail-label" style="margin-top:10px">TIME</div>
      <div>${fmtTs(w.ts)}</div>
    </div>`;
}
```

`esc()` and `fmtTs()` are existing shared helpers — reuse them, don't
reimplement escaping or timestamp formatting per tab.

### Step 4: Wire the tab switch

`switchTab()` already exists and is generic (it shows/hides the right
`.view` div and highlights the right nav-tab) — you only need to add one
line so your list actually populates the first time the tab is opened,
next to the existing `if (tab === 'interactions') renderInteractionList();`:

```javascript
if (tab === 'widget') renderWidgetList();
```

### Step 5: Wire the data payload into `body.py`'s call site

Back in `report/builder.py`, make sure the `build_body_html(...)` call
passes `widget_events=widget_events` (Step 4 of Part 1 already builds the
JSON; this is passing the *Python* list so `body.py` can decide whether to
render the tab/checkbox at all — the JS gets the JSON separately via
`data_injection.py`).

### Step 6 (optional): Add it to the Timeline tab too

If widget events should also show up interleaved on the Timeline (the way
Messages/Calls/Interactions do), add a filter-toggle button in `body.py`
next to the existing ones:

```python
{f'''<button class="fb-btn" data-tltype="widget" onclick="toggleTimelineType('widget',this)">🔧 WIDGET ({len(widget_events)})</button>''' if widget_events else ''}
```

...and add a case for `'widget'` wherever `buildTimeline()` in
`scripts.py` currently branches on `'interaction'`. This is genuinely
optional — a source can have its own dedicated tab without also appearing
on the Timeline.

---

## Part 3 (optional) — Freelist recovery for the new source

If you also want `-recover-deleted` to work against Widget.db, this is a
separate, smaller addition — see `inexus/recovery/interactions.py` as the
template. In short:

1. Create `inexus/recovery/widget.py` with a `_validate_factory(col_index)`
   closure (a plausibility check — timestamp range, non-null bundle ID,
   whatever rules out a coincidental garbage match) and a
   `recover_widget(path)` function calling `carve_table()` from
   `recovery/_common.py`.
2. Wire it into `cli.py`'s recovery block (`recovered_data["widget"] = recover_widget(widget_path)`)
   and into `report/recovered_view.py`'s `_SOURCE_SPECS` dict so it gets a
   table on the RECOVERED DATA tab.
3. If Widget.db rows carry coordinates, also add `"widget"` to
   `_RECOVERED_SOURCE_LABELS` in `report/builder.py` so recovered widget
   points can appear on the map layer too.

None of this is required for the source/tab itself to work — it's purely
additive, same as every other flag.

---

## Checklist summary

| File | What to add |
|---|---|
| `loaders/widget.py` | `load_widget(path)` — new file |
| `cli.py` | import, `-widget` flag, path capture, step count, hashing, load+correlate block, `build_html()` call |
| `report/builder.py` | `widget_events`/`widget_db_path` params, JSON payload, pass-through to `build_body_html()`/`build_data_injection()` |
| `report/data_injection.py` | `widget_json` param, `const WIDGET = ...;` line |
| `report/body.py` | `widget_events` param, nav-tab button, view `<div>` |
| `report/scripts.py` | render/filter/select functions, `switchTab()` case |
| `recovery/widget.py` *(optional)* | freelist-recovery support |

Test the same way every existing feature in this project was verified before
shipping: run the full pipeline against real or synthetic data, diff report
output when touching shared code, and — since a chunk of this lives in a
Python string containing JavaScript — run `node --check` against the
generated `<script>` block (see `report/scripts.py`'s own docstring for
why that matters) rather than trusting a Python syntax check alone.

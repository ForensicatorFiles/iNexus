"""
Renders the report's <body>: nav bar, stats bar, and the six tabbed views
(Map, Places, Timeline, Photos, App Usage, Messages, Calls, Interactions).
The last four views only render when that data source was supplied.
"""
import os

from ..constants import TOOL_NAME, TOOL_VERSION
from ..utils import esc_html
from .place_cards import _render_place_cards_map, _render_place_cards_list
from .recovered_view import render_recovered_view


def build_body_html(*, photos, places, pings, app_sessions, messages, calls,
                     interactions, photos_db_path, cache_db_path,
                     cloud_db_path, sms_db_path, calls_db_path,
                     interactions_db_path, addressbook_db_path,
                     date_min, date_max, integrity_html,
                     n_gps_orig, n_inferred, n_unlocated, n_overlap,
                     recovered_data=None, has_recovered_points=False):
    """Returns the full <body>...</body> markup (minus the trailing tag,
    added by builder.py once the <script> block follows it)."""
    recovered_view_html = render_recovered_view(recovered_data)
    return f"""<body>

<div id="nav">
  <h1>{esc_html(TOOL_NAME.upper())} <span style="color:var(--dim);font-weight:normal;font-size:11px">v{TOOL_VERSION}</span></h1>
  <div class="nav-tab active" onclick="switchTab('map', event)">🗺 MAP</div>
  <div class="nav-tab" onclick="switchTab('places', event)">📍 PLACES</div>
  <div class="nav-tab" onclick="switchTab('timeline', event)">📅 TIMELINE</div>
  {f'''<div class="nav-tab" onclick="switchTab('photos', event)">📷 PHOTOS</div>''' if photos else ''}
  {f'''<div class="nav-tab" onclick="switchTab('appusage', event)">📱 APP USAGE</div>''' if app_sessions else ''}
  {f'''<div class="nav-tab" onclick="switchTab('messages', event)">💬 MESSAGES</div>''' if messages else ''}
  {f'''<div class="nav-tab" onclick="switchTab('calls', event)">📞 CALLS</div>''' if calls else ''}
  {f'''<div class="nav-tab" onclick="switchTab('interactions', event)">🔄 INTERACTIONS</div>''' if interactions else ''}
  {f'''<div class="nav-tab" onclick="switchTab('recovered', event)" style="color:var(--yellow)">🗑 RECOVERED</div>''' if recovered_view_html else ''}
  <div class="nav-tab" onclick="document.getElementById('integrity-overlay').classList.add('open')" style="margin-left:auto">🔒 INTEGRITY &amp; PARAMETERS</div>
  <div id="nav-right">
    {f'Photos: <b>{os.path.basename(photos_db_path)}</b> &nbsp;·&nbsp;' if photos_db_path else ''}
    {f'Cache: <b>{os.path.basename(cache_db_path)}</b> &nbsp;·&nbsp;' if cache_db_path else ''}
    {f'Cloud-V2: <b>{os.path.basename(cloud_db_path)}</b> &nbsp;·&nbsp;' if cloud_db_path else ''}
    {f'sms.db: <b>{os.path.basename(sms_db_path)}</b> &nbsp;·&nbsp;' if sms_db_path else ''}
    {f'CallHistory: <b>{os.path.basename(calls_db_path)}</b> &nbsp;·&nbsp;' if calls_db_path else ''}
    {f'interactionC: <b>{os.path.basename(interactions_db_path)}</b> &nbsp;·&nbsp;' if interactions_db_path else ''}
    {f'Contacts: <b>{os.path.basename(addressbook_db_path)}</b> &nbsp;·&nbsp;' if addressbook_db_path else ''}
    {date_min} – {date_max}
  </div>
</div>

{integrity_html}

<div id="stats-bar">
  <div class="stat"><div class="val">{len(photos)}</div><div class="lbl">TOTAL ASSETS</div></div>
  <div class="stat"><div class="val">{n_gps_orig}</div><div class="lbl">EXIF GPS</div></div>
  <div class="stat"><div class="val">{n_inferred}</div><div class="lbl">GPS INFERRED</div></div>
  <div class="stat"><div class="val">{n_unlocated}</div><div class="lbl">UNLOCATED</div></div>
  <div class="stat"><div class="val">{len(places)}</div><div class="lbl">STAYS</div></div>
  <div class="stat"><div class="val">{len(pings)}</div><div class="lbl">LOCATION PINGS</div></div>
  <div class="stat"><div class="val">{n_overlap}</div><div class="lbl">OVERLAP WINDOW</div></div>
</div>

<div id="main">

  <!-- ═══ MAP ═══ -->
  <div class="view active" id="view-map" style="flex-direction:row">
    <div class="sidebar" id="map-sidebar">
      <div class="sidebar-head">
        LAYERS &amp; PLACES
        <span id="geocode-status" style="margin-left:auto;padding:0"></span>
      </div>
      <div style="padding:8px 12px;border-bottom:1px solid var(--border);font-size:9px;color:var(--dim);flex-shrink:0">
        <div style="margin-bottom:6px;font-weight:bold;letter-spacing:0.5px">MAP LAYER</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:8px">
          <button class="basemap-btn active" data-basemap="dark" onclick="setBasemap('dark')">Dark</button>
          <button class="basemap-btn" data-basemap="light" onclick="setBasemap('light')">Light</button>
          <button class="basemap-btn" data-basemap="street" onclick="setBasemap('street')">Street</button>
          <button class="basemap-btn" data-basemap="satellite" onclick="setBasemap('satellite')">Satellite</button>
        </div>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin-bottom:4px">
          <input type="checkbox" id="cb-track" checked onchange="toggleLayer('track')"> GPS track
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin-bottom:4px">
          <input type="checkbox" id="cb-stays" checked onchange="toggleLayer('stays')"> Stays / places
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin-bottom:4px">
          <input type="checkbox" id="cb-photos" checked onchange="toggleLayer('photos')"> Photo locations
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin-bottom:4px">
          <input type="checkbox" id="cb-inferred" checked onchange="toggleLayer('inferred')"> Show inferred GPS
        </label>
        {f'''<label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin-bottom:4px" title="Carved from SQLite freelist pages -- unverified, see the RECOVERED tab">
          <input type="checkbox" id="cb-recovered" onchange="toggleLayer('recovered')"> <span style="color:var(--yellow)">Recovered points (unverified)</span>
        </label>''' if has_recovered_points else ''}
        <div style="border-top:1px solid var(--border);margin:6px 0;padding-top:6px">
          <div style="font-size:9px;color:var(--dim);letter-spacing:1px;margin-bottom:4px">STAY MARKERS</div>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin-bottom:4px">
            <input type="radio" name="cluster-mode" value="clustered" checked onchange="setClusterMode('clustered')"> Cluster by location
          </label>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
            <input type="radio" name="cluster-mode" value="individual" onchange="setClusterMode('individual')"> Individual stays
          </label>
        </div>
      </div>
      <div class="sidebar-body">
        {_render_place_cards_map(places)}
      </div>
    </div>
    <div id="map-wrap">
      <div id="map-canvas"></div>
    </div>
  </div>

  <!-- ═══ PLACES ═══ -->
  <div class="view" id="view-places" style="flex-direction:row">
    <div class="sidebar" id="places-sidebar">
      <div class="sidebar-head">STAYS ({len(places)} detected)</div>
      <div class="sidebar-body">
        {_render_place_cards_list(places)}
      </div>
    </div>
    <div class="detail-panel" id="place-detail">
      <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select a stay to view details</div>
    </div>
  </div>

  <!-- ═══ TIMELINE ═══ -->
  <div class="view" id="view-timeline" style="flex-direction:row">
    <div class="sidebar" id="timeline-sidebar" style="width:400px">
      <div class="filter-bar" style="padding:8px 12px;border-bottom:1px solid var(--border)">
        <button class="fb-btn active" data-tltype="stay" onclick="toggleTimelineType('stay',this)">📍 STAYS</button>
        {f'''<button class="fb-btn active" data-tltype="photo" onclick="toggleTimelineType('photo',this)">📷 PHOTOS</button>''' if photos else ''}
        {f'''<button class="fb-btn active" data-tltype="message" onclick="toggleTimelineType('message',this)">💬 MESSAGES</button>''' if messages else ''}
        {f'''<button class="fb-btn active" data-tltype="call" onclick="toggleTimelineType('call',this)">📞 CALLS</button>''' if calls else ''}
        {f'''<button class="fb-btn" data-tltype="interaction" onclick="toggleTimelineType('interaction',this)">🔄 INTERACTIONS ({len(interactions)})</button>''' if interactions else ''}
      </div>
      <div class="sidebar-body" id="timeline-wrap" style="padding:12px"></div>
    </div>
    <div class="detail-panel" id="timeline-detail">
      <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select an event on the timeline to view details</div>
    </div>
  </div>

  <!-- ═══ PHOTOS ═══ -->
  <div class="view" id="view-photos" style="flex-direction:row">
    <div class="sidebar" id="photos-sidebar">
      <div class="search-bar">
        <input type="text" id="photo-search" placeholder="Search filename…" oninput="filterPhotos()">
      </div>
      <div class="filter-bar">
        <button class="fb-btn active" onclick="setPhotoFilter('all',this)">ALL</button>
        <button class="fb-btn" onclick="setPhotoFilter('gps',this)">EXIF GPS</button>
        <button class="fb-btn" onclick="setPhotoFilter('inferred',this)">INFERRED</button>
        <button class="fb-btn" onclick="setPhotoFilter('unknown',this)">UNLOCATED</button>
        <button class="fb-btn" onclick="setPhotoFilter('trash',this)">🗑 TRASH</button>
      </div>
      <div class="sidebar-head" id="photo-count-label">PHOTOS</div>
      <div class="sidebar-body" id="photo-list"></div>
    </div>
    <div class="detail-panel" id="photo-detail">
      <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select a photo to view details</div>
    </div>
  </div>

  {f'''<div class="view" id="view-appusage" style="flex-direction:row">
    <div class="sidebar" id="appusage-sidebar">
      <div class="search-bar">
        <input type="text" id="app-search" placeholder="Search app, bundle ID…" oninput="filterAppSessions()">
      </div>
      <div class="filter-bar">
        <button class="fb-btn active" onclick="setAppFilter('all',this)">ALL</button>
        <button class="fb-btn" onclick="setAppFilter('Messaging App',this)">MESSAGING</button>
        <button class="fb-btn" onclick="setAppFilter('Social Media',this)">SOCIAL</button>
        <button class="fb-btn" onclick="setAppFilter('Apple System App',this)">APPLE</button>
      </div>
      <div class="sidebar-head" id="app-count-label">APP USAGE SESSIONS</div>
      <div class="sidebar-body" id="app-list"></div>
    </div>
    <div class="detail-panel" id="app-detail">
      <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select a session to view details</div>
    </div>
  </div>''' if app_sessions else ''}

  {f'''<div class="view" id="view-messages" style="flex-direction:row">
    <div class="sidebar" id="messages-sidebar">
      <div class="search-bar">
        <input type="text" id="message-search" placeholder="Search text, sender…" oninput="filterMessages()">
      </div>
      <div class="filter-bar">
        <button class="fb-btn active" onclick="setMessageFilter('all',this)">ALL</button>
        <button class="fb-btn" onclick="setMessageFilter('iMessage',this)">IMESSAGE</button>
        <button class="fb-btn" onclick="setMessageFilter('SMS',this)">SMS</button>
        <button class="fb-btn" onclick="setMessageFilter('group',this)">GROUP</button>
        <button class="fb-btn" onclick="setMessageFilter('attachment',this)">📎 ATTACHMENT</button>
      </div>
      <div class="sidebar-head" id="message-count-label">MESSAGES</div>
      <div class="sidebar-body" id="message-list"></div>
    </div>
    <div class="detail-panel" id="message-detail">
      <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select a message to view details</div>
    </div>
  </div>''' if messages else ''}

  {f'''<div class="view" id="view-calls" style="flex-direction:row">
    <div class="sidebar" id="calls-sidebar">
      <div class="search-bar">
        <input type="text" id="call-search" placeholder="Search caller, number…" oninput="filterCalls()">
      </div>
      <div class="filter-bar">
        <button class="fb-btn active" onclick="setCallFilter('all',this)">ALL</button>
        <button class="fb-btn" onclick="setCallFilter('incoming',this)">INCOMING</button>
        <button class="fb-btn" onclick="setCallFilter('outgoing',this)">OUTGOING</button>
        <button class="fb-btn" onclick="setCallFilter('missed',this)">MISSED</button>
        <button class="fb-btn" onclick="setCallFilter('voip',this)">VOIP</button>
      </div>
      <div class="sidebar-head" id="call-count-label">CALLS</div>
      <div class="sidebar-body" id="call-list"></div>
    </div>
    <div class="detail-panel" id="call-detail">
      <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select a call to view details</div>
    </div>
  </div>''' if calls else ''}

  {f'''<div class="view" id="view-interactions" style="flex-direction:row">
    <div class="sidebar" id="interactions-sidebar">
      <div class="search-bar">
        <input type="text" id="interaction-search" placeholder="Search app, contact…" oninput="filterInteractions()">
      </div>
      <div class="filter-bar">
        <button class="fb-btn active" onclick="setInteractionFilter('all',this)">ALL</button>
        <button class="fb-btn" onclick="setInteractionFilter('incoming',this)">INCOMING</button>
        <button class="fb-btn" onclick="setInteractionFilter('outgoing',this)">OUTGOING</button>
        <button class="fb-btn" onclick="setInteractionFilter('overlap',this)">⚠ OVERLAP</button>
        <button class="fb-btn" onclick="setInteractionFilter('new',this)">NEW ONLY</button>
      </div>
      <div class="sidebar-head" id="interaction-count-label">INTERACTIONS</div>
      <div class="sidebar-body" id="interaction-list"></div>
    </div>
    <div class="detail-panel" id="interaction-detail">
      <div style="color:var(--dim);font-size:11px;margin-top:40px;text-align:center">← Select an interaction to view details</div>
    </div>
  </div>''' if interactions else ''}

  {recovered_view_html}

</div><!-- #main -->

"""

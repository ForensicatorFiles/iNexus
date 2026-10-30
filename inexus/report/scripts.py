"""Static client-side JS for the report (map, tabs, timeline, filtering,
the per-stay printable-report generator, etc). No Python interpolation
happens here — the data payload is injected separately, see
data_injection.py, and concatenated before this block by builder.py."""

STATIC_SCRIPT = """// ── State ────────────────────────────────────────────────────────────────────
let leafletMap = null;
let layers = { track: null, stays: null, photos: null, recovered: null };
let selectedPlaceId = null;
let selectedPhotoId = null;
let photoFilter = 'all';
let photoSearch = '';
let appFilter = 'all';
let appSearch = '';
let selectedAppId = null;
let messageFilter = 'all';
let messageSearch = '';
let selectedMessageId = null;
let callFilter = 'all';
let callSearch = '';
let selectedCallId = null;
let interactionFilter = 'all';
let interactionSearch = '';
let selectedInteractionId = null;
let geocodeCache = {};
let geocodePending = 0;
let currentBasemap = 'dark';   // persists across main map + per-photo mini-maps
let basemapTileLayer = null;   // the single active tile layer on the main map

// ── Basemap definitions ──────────────────────────────────────────────────────
const _cartoKey = (typeof window.INEXUS_CARTO_KEY === 'string') ? window.INEXUS_CARTO_KEY.trim() : '';
const _cartoParam = _cartoKey ? '?key=' + encodeURIComponent(_cartoKey) : '';

const BASEMAPS = {
  dark: {
    label: 'Dark',
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png' + _cartoParam,
    attribution: '© OpenStreetMap contributors © CARTO',
    maxZoom: 20
  },
  light: {
    label: 'Light',
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png' + _cartoParam,
    attribution: '© OpenStreetMap contributors © CARTO',
    maxZoom: 20
  },
  street: {
    label: 'Street',
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    maxZoom: 19
  },
  satellite: {
    label: 'Satellite',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Imagery © Esri',
    maxZoom: 19
  },
};

function addBasemapTiles(map, key) {
  const def = BASEMAPS[key] || BASEMAPS.dark;
  return L.tileLayer(def.url, {maxZoom: def.maxZoom, attribution: def.attribution}).addTo(map);
}

function setBasemap(key) {
  currentBasemap = key;
  if (leafletMap && basemapTileLayer) {
    leafletMap.removeLayer(basemapTileLayer);
    basemapTileLayer = addBasemapTiles(leafletMap, key);
    basemapTileLayer.bringToBack();
  }
  document.querySelectorAll('.basemap-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.basemap === key);
  });
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab, evt) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  // Highlight the corresponding nav-tab whether this came from a real click
  // (evt/currentTarget present) or a programmatic jump from a popup/link
  // (no event — find the tab by its onclick attribute instead).
  const clicked = evt && evt.currentTarget;
  const navTab = clicked || document.querySelector(`.nav-tab[onclick*="switchTab('${tab}')"]`);
  if (navTab) navTab.classList.add('active');
  document.getElementById('view-' + tab).classList.add('active');
  if (tab === 'map') {
    setTimeout(() => { initMap(); leafletMap.invalidateSize(); }, 50);
  }
  if (tab === 'timeline') buildTimeline();
  if (tab === 'photos')   renderPhotoList();
  if (tab === 'appusage') renderAppList();
  if (tab === 'messages') renderMessageList();
  if (tab === 'calls')    renderCallList();
  if (tab === 'interactions') renderInteractionList();
  if (tab === 'places')   geocodeAllPlaces();
}

// Resolves a human-readable name for every place up front, queued and
// throttled (see resolvePlace/geocode above) so it doesn't matter which
// tab — Map, Places, or Timeline — the person looks at first; results
// arrive progressively and broadcast to every tab via applyPlaceLabel.
let placesGeocoded = false;
function geocodeAllPlaces() {
  if (placesGeocoded) return;
  placesGeocoded = true;
  PLACES.forEach(p => resolvePlace(p));
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function fmtTs(unix) {
  if (!unix) return '—';
  return new Date(unix * 1000).toISOString().replace('T',' ').slice(0,19) + ' UTC';
}
function fmtDur(sec) {
  if (!sec || sec < 0) return '—';
  const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60);
  return h>0 ? h+'h '+m+'m' : m+'m';
}
function copyText(t) {
  navigator.clipboard.writeText(t).catch(() => {});
}
function expandMedia(src) {
  if (src.startsWith('data:')) {
    // Safely write the Base64 image into a new tab's document to bypass data URI navigation blocks
    const win = window.open('');
    if (win) {
      win.document.write('<!DOCTYPE html><html><head><title>Thumbnail Preview</title></head><body style="margin:0;background:#0d1117;display:flex;align-items:center;justify-content:center;height:100vh;"><img src="' + src + '" style="max-width:100%;max-height:100%;"></body></html>');
      win.document.close();
    } else {
      alert("Popup blocked! Please allow popups to view this thumbnail.");
    }
  } else {
    window.open(src, '_blank');
  }
}
// --- DCIM photo preview helpers -------------------------------------------
// Build a report-relative URL to the asset by joining ZDIRECTORY/ZFILENAME and
// percent-encoding each path segment (spaces, #, etc.) while keeping slashes.
function relPath(p) {
  var f = p.directory ? p.directory + '/' + p.filename : p.filename;
  if (f && p.directory !== '__v2_thumbs__') {
    var low = f.toLowerCase();
    var key = (low.indexOf('dcim/') === 0) ? low.slice(5) : low;
    var mapped = (typeof HEIC_MAP !== 'undefined' && HEIC_MAP) ? HEIC_MAP[key] : null;
    var target = mapped || f;   // converted JPEG if we have one, else the original DCIM path
    
    // If it's a standard live asset, check if it's not a V2 orphan, or use the normal path
    if (!p.is_thumbnail_orphan) {
      return target.split('/').map(encodeURIComponent).join('/');
    }
  }

  // Fallback to V2 thumbnail data URI only if normal version is absent/orphan
  if (p.thumbnail_data_uri) {
    return p.thumbnail_data_uri;
  }

  return f ? f.split('/').map(encodeURIComponent).join('/') : '';
}
// onerror handler: the file isn't beside the report, or the browser can't
// decode the format (e.g. HEIC/HEVC). If a V2 thumbnail is available, swap to it!
function ppFail(id) {
  var m = document.getElementById('pp-media-' + id) || document.getElementById('tl-media-' + id);
  var p = PHOTOS.find(x => x.id === id);

  if (m && p && p.thumbnail_data_uri && m.src !== p.thumbnail_data_uri) {
    if (m.tagName.toLowerCase() === 'video') {
      // Browsers cannot render a JPEG inside a <video> tag's src. 
      // Replace the video element entirely with a standard <img> tag.
      var img = document.createElement('img');
      img.id = m.id;
      img.src = p.thumbnail_data_uri;
      img.style.cssText = m.style.cssText;
      img.style.cursor = 'zoom-in';
      img.onclick = function() { expandMedia(img.src); };
      m.parentNode.replaceChild(img, m);
    } else {
      m.src = p.thumbnail_data_uri;
    }
    return;
  }

  if (m) m.style.display = 'none';
  var miss = document.getElementById('pp-miss-' + id);
  if (miss) miss.style.display = 'block';
}
function sourcePill(p) {
  const icons = {
    'Camera Captured':  '📷',
    'Screenshot':       '📋',
    'Messaging App':    '💬',
    'Social Media':     '🌐',
    'Email Attachment': '📧',
    'Cloud Storage':    '☁️',
    'Cable Transfer':   '🔌',
    'Shared Album':     '🤝',
    'iCloud':           '☁️',
    'Received File':    '📥',
    'Third-Party App':  '📲',
    'System Save':      '⚙️',
    'Device Library':   '📂',
    'Apple System App': '🍎',
    'AirDrop':          '📡',   // explicitly mapped AirDrop icon
    'Other App':        '👾',   // fallback for unrecognized bundles
    'Unknown':          '❓',
    'Unknown App':      '❓',
  };
  
  const colors = {
    'Camera Captured':  '#3dd68c',
    'Screenshot':       '#40c8c8',
    'Messaging App':    '#9b72d8',
    'Social Media':     '#e07b40',
    'Email Attachment': '#f0c040',
    'Cloud Storage':    '#4a90d9',
    'Cable Transfer':   '#768390',
    'Shared Album':     '#3dd68c',
    'iCloud':           '#4a90d9',
    'Received File':    '#9b72d8',
    'Third-Party App':  '#e07b40',
    'System Save':      '#768390',
    'Device Library':   '#4a90d9',
    'Apple System App': '#768390',
    'AirDrop':          '#4a90d9',   // explicitly mapped AirDrop color
    'Other App':        '#e07b40',
    'Unknown':          '#768390',
    'Unknown App':      '#768390',
  };

  const cat = p.source_category || p.src_cat || p.category || 'Unknown';
  const sub = p.source_subcategory || p.src_sub || p.subcategory || '';
  let icon = icons[cat] || '❓';
  let color = colors[cat] || '#768390';

  // Dynamic overrides based on the app name or bundle ID in the subcategory
  const subText = sub.toLowerCase();
  if (subText.includes('snapchat') || subText.includes('picaboo')) {
    icon = '👻';
    color = '#e0d840'; // Snapchat Yellow
  } else if (subText.includes('instagram') || subText.includes('burbn')) {
    icon = '📸';
    color = '#d94a8c'; // Instagram Pink/Magenta
  } else if (subText.includes('whatsapp')) {
    icon = '💬';
    color = '#4ad97a'; // WhatsApp Green
  } else if (subText.includes('tiktok')) {
    icon = '🎵';
  } else if (subText.includes('facebook')) {
    icon = '📘';
  }

  const label = sub ? cat + ' · ' + sub : cat;
  return `<span style="background:${color}22;border:1px solid ${color}55;color:${color};padding:1px 6px;border-radius:3px;font-size:9px;white-space:nowrap">${icon} ${esc(label)}</span>`;
}

function methodPill(m) {
  const cls = m==='exif-gps' ? 'm-exif' : m==='interpolated' ? 'm-interp' : m==='nearest-ping' ? 'm-nearest' : m==='stay' ? 'm-exif' : 'm-unknown';
  const lbl = m==='exif-gps' ? 'EXIF GPS' : m==='interpolated' ? 'INTERPOLATED' : m==='nearest-ping' ? 'NEAREST PING' : m==='stay' ? 'MATCHED TO STAY' : 'UNKNOWN';
  return `<span class="method-pill ${cls}">${lbl}</span>`;
}

// ── Reverse geocoding (Nominatim) ─────────────────────────────────────────────
// Nominatim's usage policy caps reverse-geocode lookups at ~1/sec. Firing
// requests from multiple places at once (eager load, timeline render, popup
// clicks) used to blow straight through that and get silently throttled —
// the symptom was that resolution "worked" only when you clicked one stay
// at a time, since that happened to space requests out. This queue
// serializes every request and de-dupes concurrent callers asking for the
// same coordinates (rounded to the same cache key) into a single network
// call.
let geocodeQueue = [];
let geocodeInFlight = {};   // key -> array of pending callbacks
let geocodeQueueRunning = false;

function geocode(lat, lng, callback) {
  const key = lat.toFixed(4) + ',' + lng.toFixed(4);
  if (geocodeCache[key]) { callback(geocodeCache[key]); return; }
  if (geocodeInFlight[key]) { geocodeInFlight[key].push(callback); return; }
  geocodeInFlight[key] = [callback];
  geocodeQueue.push(key);
  geocodePending++;
  updateGeocodeStatus();
  runGeocodeQueue();
}

function runGeocodeQueue() {
  if (geocodeQueueRunning) return;
  geocodeQueueRunning = true;
  const step = () => {
    const key = geocodeQueue.shift();
    if (!key) { geocodeQueueRunning = false; return; }
    const [lat, lng] = key.split(',').map(Number);
    const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`;
    fetch(url, {headers:{'User-Agent':'LocationCorrelator/1.0'}})
      .then(r => r.json())
      .then(d => {
        const addr = d.address || {};
        const parts = [
          addr.amenity || addr.building || addr.road,
          addr.city || addr.town || addr.village || addr.suburb,
          addr.state || addr.county,
          addr.country
        ].filter(Boolean);
        const label = parts.slice(0,3).join(', ') || d.display_name || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
        geocodeCache[key] = label;
        (geocodeInFlight[key] || []).forEach(cb => cb(label));
        delete geocodeInFlight[key];
        geocodePending--;
        updateGeocodeStatus();
      })
      .catch(() => {
        const fallback = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
        (geocodeInFlight[key] || []).forEach(cb => cb(fallback));
        delete geocodeInFlight[key];
        geocodePending--;
        updateGeocodeStatus();
      })
      .finally(() => setTimeout(step, 1100));   // stay under Nominatim's ~1 req/sec policy
  };
  step();
}

// Pushes a resolved name to every place on screen that could be showing
// it: the map's left sidebar card, the Places tab's left sidebar card, an
// open map popup, the Places tab detail panel, and the Timeline entry.
// Whichever tab the person is actually looking at, this keeps them all in
// sync instead of each call site updating only its own corner of the UI.
function applyPlaceLabel(id, lbl) {
  const targets = [
    ['label-'+id,         `<b>${lbl}</b>`],
    ['plabel-'+id,        `<b>${lbl}</b>`],
    ['gc-'+id,            lbl],
    ['tl-gc-'+id,         ' — ' + lbl],
    ['pd-geocode-'+id,    '— ' + lbl],
  ];
  targets.forEach(([elId, content]) => {
    const el = document.getElementById(elId);
    if (el) el.innerHTML = content;
  });
}

// Single entry point used by every tab/view to resolve a place's name.
// Respects an on-device name (from Cloud-V2) if already known, otherwise
// queues a reverse-geocode lookup and broadcasts the result everywhere.
function resolvePlace(p) {
  if (p.device_place_name) { applyPlaceLabel(p.id, esc(p.device_place_name)); return; }
  geocode(p.lat, p.lng, lbl => applyPlaceLabel(p.id, lbl));
}

function updateGeocodeStatus() {
  const el = document.getElementById('geocode-status');
  if (el) el.textContent = geocodePending > 0 ? `🔍 Geocoding ${geocodePending}…` : '';
}

// ── Map ───────────────────────────────────────────────────────────────────────
function initMap() {
  if (leafletMap) return;
  leafletMap = L.map('map-canvas');
  basemapTileLayer = addBasemapTiles(leafletMap, currentBasemap);
  renderMapLayers();
}

function renderMapLayers() {
  // GPS track
  if (TRACK.length > 1) {
    layers.track = L.polyline(TRACK, {color:'#3393c5', weight:2, opacity:0.6});
    if (document.getElementById('cb-track').checked) layers.track.addTo(leafletMap);
  }

  rebuildStayLayer();

  // Photo markers
  const photoMarkers = PHOTOS
    .filter(p => p.lat && p.lat !== -180 && p.lat !== 0)
    .map(p => {
      const color = p.has_gps ? '#00e676' : p.method==='interpolated' ? '#ffd60a' : '#ff6d00';
      const icon = L.circleMarker([p.lat, p.lng], {
        radius: 7, color: '#ffffff', weight: 2, fillColor: color, fillOpacity: 0.95
      });
      icon.bindPopup(`<div class="popup-inner">
        <b>${esc(p.filename)}</b><br>
        <span style="font-size:9px">${fmtTs(p.ts)}</span><br>
        ${methodPill(p.method)}
        ${p.place_id ? ` · <a href="#" onclick="goToPlace(${p.place_id});return false" style="color:#3393c5">Stay #${p.place_id} →</a>` : ''}<br>
        <a href="#" onclick="goToPhoto(${p.id});return false" style="color:#3393c5;font-size:9px">View photo detail →</a>
      </div>`);
      return {icon, has_gps: p.has_gps, method: p.method};
    });

  layers.photos = L.layerGroup(photoMarkers.map(m => m.icon));
  if (document.getElementById('cb-photos').checked) layers.photos.addTo(leafletMap);

  // Recovered points (unverified -- carved from SQLite freelist pages, see
  // the RECOVERED tab). Visually distinct from confirmed data (dashed
  // outline, yellow) and deliberately excluded from the fitBounds() coord
  // list below -- a stale or slightly-off recovered coordinate shouldn't be
  // able to skew the initial map view away from the confirmed data everyone
  // actually came here to look at.
  if (RECOVERED_POINTS.length > 0) {
    const recoveredMarkers = RECOVERED_POINTS.map(p => {
      const marker = L.circleMarker([p.lat, p.lng], {
        radius: 6, color: '#DDE667', weight: 2, dashArray: '3,2',
        fillColor: '#DDE667', fillOpacity: 0.35
      });
      marker.bindPopup(`<div class="popup-inner">
        <span style="color:#DDE667">⚠ UNVERIFIED — RECOVERED</span><br>
        <b>${esc(p.source)}</b>${p.ts_str ? ' · ' + esc(p.ts_str) : ''}<br>
        <span style="font-size:9px">page ${p.page} · rowid ${p.rowid}${p.truncated ? ' · ⚠ partial' : ''}</span><br>
        <span style="font-size:9px;color:var(--dim)">Carved from a freed SQLite page, not read from the live database. See the RECOVERED tab.</span>
      </div>`);
      return marker;
    });
    layers.recovered = L.layerGroup(recoveredMarkers);
    if (document.getElementById('cb-recovered') && document.getElementById('cb-recovered').checked) {
      layers.recovered.addTo(leafletMap);
    }
  }

  // Fit bounds
  const allCoords = [
    ...TRACK.slice(0, 500),
    ...PLACES.map(p => [p.lat, p.lng]),
    ...PHOTOS.filter(p => p.lat && p.lat !== -180 && p.lat !== 0).map(p => [p.lat, p.lng])
  ].filter(c => c && c[0] != null && c[0] !== -180 && c[0] !== 0);

  if (allCoords.length > 0) {
    leafletMap.fitBounds(allCoords, {padding:[20,20]});
  } else {
    leafletMap.setView([0, 0], 2);
  }
}

// ── Stay marker clustering ────────────────────────────────────────────────────
// Purely visual/display-side: no changes to the underlying PLACES data model.
// Groups PLACES by spatial proximity alone (ignoring time gaps), so the same
// physical address visited on 20 different days shows as one map pin with a
// count badge. The Places tab and all other tabs are unaffected.

let clusterMode = 'clustered';

function setClusterMode(mode) {
  clusterMode = mode;
  rebuildStayLayer();
}

// Haversine distance in metres between two lat/lng pairs.
function haversineM(lat1, lng1, lat2, lng2) {
  const R = 6371000, r = Math.PI/180;
  const dLat = (lat2-lat1)*r, dLng = (lng2-lng1)*r;
  const a = Math.sin(dLat/2)**2 + Math.cos(lat1*r)*Math.cos(lat2*r)*Math.sin(dLng/2)**2;
  return R * 2 * Math.asin(Math.sqrt(a));
}

// Groups PLACES into spatial clusters using the analysis radius.
function clusterPlacesForMap() {
  const radius = (REPORT_META.run_params && REPORT_META.run_params.radius_m) || 150;
  const assigned = new Array(PLACES.length).fill(-1);
  const groups = [];
  PLACES.forEach((p, i) => {
    if (assigned[i] !== -1) return;
    const group = [i];
    assigned[i] = groups.length;
    PLACES.forEach((q, j) => {
      if (i === j || assigned[j] !== -1) return;
      if (haversineM(p.lat, p.lng, q.lat, q.lng) <= radius) {
        assigned[j] = groups.length;
        group.push(j);
      }
    });
    groups.push(group);
  });
  return groups.map(indices => indices.map(i => PLACES[i]));
}

function rebuildStayLayer() {
  if (!leafletMap) return;
  if (layers.stays) {
    leafletMap.removeLayer(layers.stays);
    layers.stays = null;
  }

  const markers = [];

  if (clusterMode === 'individual') {
    PLACES.forEach(p => {
      const dur = fmtDur(p.duration);
      const circle = L.circle([p.lat, p.lng], {
        radius:80, color:'#3393c5', fillColor:'#3393c5', fillOpacity:0.15, weight:2,
        interactive:false   // let clicks pass through to photo markers underneath
      });
      const marker = L.marker([p.lat, p.lng], {
        icon: L.divIcon({
          className:'',
          html:`<div style="background:#3393c5;color:#000;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:bold;border:2px solid #0d1117">${p.id}</div>`,
          iconSize:[22,22], iconAnchor:[11,11]
        })
      });
      const popup = L.popup({maxWidth:220}).setContent(
        `<div class="popup-inner">
          <b>Stay #${p.id}</b><br>
          <span id="gc-${p.id}" style="color:#666;font-size:9px">${p.device_place_name ? esc(p.device_place_name) : 'Loading…'}</span><br>
          ${p.device_address ? `<span style="font-size:9px;color:#888">${esc(p.device_address)}</span><br>` : ''}
          <span style="font-size:9px">⏱ ${dur} &nbsp; ${p.n_photos > 0
            ? `<a href="#" onclick="goToPlace(${p.id});return false" style="color:#3393c5;font-weight:bold">📷 ${p.n_photos} photo(s) →</a>`
            : '📷 0 photos'}</span><br>
          <span style="font-size:9px">${fmtTs(p.entry)} →<br>${fmtTs(p.exit)}</span><br>
          <a href="#" onclick="goToPlace(${p.id});return false" style="color:#3393c5;font-size:9px">→ View in Places tab</a>
        </div>`
      );
      marker.bindPopup(popup);
      marker.on('popupopen', () => resolvePlace(p));
      markers.push(circle, marker);
    });

  } else {
    // Clustered: one pin per unique physical location
    const groups = clusterPlacesForMap();
    groups.forEach(group => {
      const count  = group.length;
      const lat    = group.reduce((s,p)=>s+p.lat,0)/count;
      const lng    = group.reduce((s,p)=>s+p.lng,0)/count;
      const isSingle = count === 1;
      const p0     = group[0];
      const bgColor  = isSingle ? '#3393c5' : '#e07b39';
      const pinSize  = isSingle ? 22 : Math.min(36, 22 + count*2);

      const circle = L.circle([lat, lng], {
        radius: isSingle ? 80 : 120,
        color: bgColor, fillColor: bgColor, fillOpacity:0.12, weight:2,
        interactive:false   // let clicks pass through to photo markers underneath
      });

      const marker = L.marker([lat, lng], {
        icon: L.divIcon({
          className:'',
          html: isSingle
            ? `<div style="background:${bgColor};color:#000;border-radius:50%;width:${pinSize}px;height:${pinSize}px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:bold;border:2px solid #0d1117">${p0.id}</div>`
            : `<div style="background:${bgColor};color:#fff;border-radius:50%;width:${pinSize}px;height:${pinSize}px;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:9px;font-weight:bold;border:2px solid #0d1117;line-height:1.1">
                <span>${count}</span><span style="font-size:7px">visits</span>
               </div>`,
          iconSize:[pinSize,pinSize], iconAnchor:[pinSize/2,pinSize/2]
        })
      });

      if (isSingle) {
        const dur = fmtDur(p0.duration);
        marker.bindPopup(L.popup({maxWidth:240}).setContent(
          `<div class="popup-inner">
            <b>Stay #${p0.id}</b><br>
            <span id="gc-${p0.id}" style="color:#666;font-size:9px">${p0.device_place_name ? esc(p0.device_place_name) : 'Loading…'}</span><br>
            ${p0.device_address ? `<span style="font-size:9px;color:#888">${esc(p0.device_address)}</span><br>` : ''}
            <span style="font-size:9px">⏱ ${dur} &nbsp; ${p0.n_photos > 0
              ? `<a href="#" onclick="goToPlace(${p0.id});return false" style="color:#3393c5;font-weight:bold">📷 ${p0.n_photos} photo(s) →</a>`
              : '📷 0 photos'}</span><br>
            <span style="font-size:9px">${fmtTs(p0.entry)} →<br>${fmtTs(p0.exit)}</span><br>
            <a href="#" onclick="goToPlace(${p0.id});return false" style="color:#3393c5;font-size:9px">→ View in Places tab</a>
          </div>`
        ));
        marker.on('popupopen', () => resolvePlace(p0));

      } else {
        // Multi-stay cluster popup — lists all constituent stays
        const totalDur    = group.reduce((s,p)=>s+p.duration,0);
        const totalPhotos = group.reduce((s,p)=>s+p.n_photos,0);
        const earliest    = group.reduce((a,b)=>a.entry<b.entry?a:b);
        const sorted      = [...group].sort((a,b)=>a.entry-b.entry);

        const rows = sorted.map(p =>
          `<tr style="border-bottom:1px solid #1e3a5f">
            <td style="padding:3px 6px;white-space:nowrap">
              <a href="#" onclick="goToPlace(${p.id});leafletMap.closePopup();return false" style="color:#4a90d9;font-size:9px">Stay #${p.id}</a>
            </td>
            <td style="padding:3px 6px;font-size:9px;white-space:nowrap">${fmtTs(p.entry).split(' ').slice(0,2).join(' ')}</td>
            <td style="padding:3px 6px;font-size:9px;white-space:nowrap">${fmtDur(p.duration)}</td>
            <td style="padding:3px 6px;font-size:9px;text-align:center">${p.n_photos>0?'📷':''}</td>
          </tr>`
        ).join('');

        marker.bindPopup(L.popup({maxWidth:320, maxHeight:360}).setContent(
          `<div class="popup-inner" style="max-height:340px;overflow-y:auto;min-width:260px">
            <div style="font-weight:bold;margin-bottom:2px;color:#e07b39">${count} visits to this location</div>
            <div id="gc-cluster-${p0.id}" style="color:#666;font-size:9px;margin-bottom:4px">
              ${p0.device_place_name ? esc(p0.device_place_name) : 'Loading…'}
            </div>
            <div style="font-size:9px;color:#888;margin-bottom:6px">
              Total time on site: ${fmtDur(totalDur)} &nbsp;·&nbsp; ${totalPhotos} photo(s)<br>
              First visit: ${fmtTs(earliest.entry).split(' ').slice(0,2).join(' ')}
            </div>
            <table style="width:100%;border-collapse:collapse">
              <thead><tr style="background:#0d1220">
                <th style="padding:3px 6px;text-align:left;font-size:9px;color:#7a8aa0">STAY</th>
                <th style="padding:3px 6px;text-align:left;font-size:9px;color:#7a8aa0">ARRIVED</th>
                <th style="padding:3px 6px;text-align:left;font-size:9px;color:#7a8aa0">DURATION</th>
                <th style="padding:3px 6px;font-size:9px;color:#7a8aa0">📷</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>`
        ));
        marker.on('popupopen', () => {
          const el = document.getElementById('gc-cluster-${p0.id}');
          if (el && !p0.device_place_name) {
            geocode(lat, lng, lbl => {
              if (el) el.textContent = lbl;
              group.forEach(p => applyPlaceLabel(p.id, lbl));
            });
          }
        });
      }

      markers.push(circle, marker);
    });
  }

  layers.stays = L.layerGroup(markers);
  if (document.getElementById('cb-stays').checked) layers.stays.addTo(leafletMap);
}
function toggleLayer(name) {
  if (!leafletMap) return;
  const layer = layers[name];
  if (!layer) return;
  if (leafletMap.hasLayer(layer)) leafletMap.removeLayer(layer);
  else layer.addTo(leafletMap);
}
function toggleInferred() {
  // handled by photos layer rebuild - for now just toggle
}

function focusPlace(id) {
  initMap();
  const p = PLACES.find(x => x.id===id);
  if (!p) return;
  leafletMap.setView([p.lat, p.lng], 16);
  document.querySelectorAll('.place-card').forEach(c => c.classList.remove('active'));
  const card = document.getElementById('pc-'+id);
  if (card) card.classList.add('active');
  switchTab('map');
}

// Jump straight to a specific stay's detail in the Places tab — safe to call
// from a map popup, a photo's detail panel, or anywhere else, since it
// doesn't depend on a real click event.
function goToPlace(id) {
  switchTab('places');
  setTimeout(() => {
    selectPlace(id);
    const card = document.getElementById('plc-'+id);
    if (card) card.scrollIntoView({block:'center', behavior:'smooth'});
  }, 60);
}

// Jump straight to a specific photo's detail in the Photos tab — same
// "safe from anywhere" pattern as goToPlace above. Resets any active
// filter/search first so the target photo is guaranteed to be visible
// in the list rather than hidden by a leftover filter from a previous view.
function goToPhoto(id) {
  photoFilter = 'all';
  photoSearch = '';
  const search = document.getElementById('photo-search');
  if (search) search.value = '';
  document.querySelectorAll('#photos-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('#photos-sidebar .fb-btn[onclick*="\\'all\\'"]');
  if (allBtn) allBtn.classList.add('active');

  switchTab('photos');
  setTimeout(() => {
    selectPhoto(id);
    const row = document.querySelector(`.photo-row[onclick="selectPhoto(${id})"]`);
    if (row) row.scrollIntoView({block:'center', behavior:'smooth'});
  }, 60);
}

// Jump straight to a specific app-usage session's detail in the App Usage
// tab — same "safe from anywhere, resets filters first" pattern as goToPhoto.
function goToAppSession(zpk) {
  appFilter = 'all';
  appSearch = '';
  const search = document.getElementById('app-search');
  if (search) search.value = '';
  document.querySelectorAll('#appusage-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('#appusage-sidebar .fb-btn[onclick*="\\'all\\'"]');
  if (allBtn) allBtn.classList.add('active');

  switchTab('appusage');
  setTimeout(() => {
    selectAppSession(zpk);
    const row = document.querySelector(`.photo-row[onclick="selectAppSession(${zpk})"]`);
    if (row) row.scrollIntoView({block:'center', behavior:'smooth'});
  }, 60);
}

// ── Places tab ────────────────────────────────────────────────────────────────
function selectPlace(id) {
  selectedPlaceId = id;
  document.querySelectorAll('#places-sidebar .place-card').forEach(c => c.classList.remove('active'));
  const card = document.getElementById('plc-'+id);
  if (card) card.classList.add('active');
  renderPlaceDetail(id);
}

function renderPlaceDetail(id) {
  const p = PLACES.find(x => x.id===id);
  if (!p) return;
  const photos = PHOTOS.filter(x => x.place_id===id);
  const det = document.getElementById('place-detail');

  const rowsHtml = photos.length === 0
    ? '<p style="color:var(--dim);font-size:10px">No photos assigned to this stay.</p>'
    : `<table class="photo-table">
        <tr><th>#</th><th>FILENAME</th><th>ORIGIN</th><th>TIMESTAMP</th><th>LOCATION METHOD</th><th>SIZE</th><th></th></tr>
        ${photos.map((ph,i) => `<tr class="${ph.trashed?'trashed':''} photo-link-row" onclick="goToPhoto(${ph.id})" title="Click to view this photo's detail">
          <td style="color:var(--dim)">${i+1}</td>
          <td>${esc(ph.filename)}${ph.trashed?' <span class="trash-pill">TRASH</span>':''}</td>
          <td>${sourcePill(ph)}</td>
          <td style="white-space:nowrap;font-size:9px">${fmtTs(ph.ts)}</td>
          <td>${methodPill(ph.method)}</td>
          <td style="color:var(--dim)">${ph.w&&ph.h ? ph.w+'×'+ph.h : '—'}</td>
          <td><button class="copy-btn" onclick="event.stopPropagation();copyText('${ph.lat},${ph.lng}')" title="Copy coords">⧉</button></td>
        </tr>`).join('')}
      </table>`;

  const sessions = APP_SESSIONS.filter(x => x.place_id === id).sort((a,b) => a.start - b.start);
  const appRowsHtml = sessions.length === 0
    ? ''
    : `<table class="photo-table">
        <tr><th>#</th><th>APP</th><th>CATEGORY</th><th>STARTED</th><th>DURATION</th></tr>
        ${sessions.map((s,i) => `<tr class="photo-link-row" onclick="goToAppSession(${s.zpk})" title="Click to view this session's detail">
          <td style="color:var(--dim)">${i+1}</td>
          <td>${esc(s.bundle_id)}</td>
          <td>${sourcePill(s)}</td>
          <td style="white-space:nowrap;font-size:9px">${fmtTs(s.start)}</td>
          <td style="color:var(--dim)">${fmtDur(s.duration)}</td>
        </tr>`).join('')}
      </table>`;

  const stayMessages = MESSAGES.filter(x => x.place_id === id).sort((a,b) => a.ts - b.ts);
  const msgRowsHtml = stayMessages.length === 0
    ? ''
    : `<table class="photo-table">
        <tr><th>#</th><th>FROM/TO</th><th>TEXT</th><th>CHANNEL</th><th>TIME</th></tr>
        ${stayMessages.map((m,i) => `<tr class="photo-link-row" onclick="goToMessage(${m.id})" title="Click to view this message's detail">
          <td style="color:var(--dim)">${i+1}</td>
          <td>${m.is_from_me?'→ ':'← '}${esc(m.is_from_me ? (m.chat_name||m.sender) : m.sender)}</td>
          <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(m.display_text)}</td>
          <td>${messagePill(m)}</td>
          <td style="white-space:nowrap;font-size:9px">${fmtTs(m.ts)}</td>
        </tr>`).join('')}
      </table>`;

  const stayCalls = CALLS.filter(x => x.place_id === id).sort((a,b) => a.ts - b.ts);
  const callRowsHtml = stayCalls.length === 0
    ? ''
    : `<table class="photo-table">
        <tr><th>#</th><th>FROM/TO</th><th>TYPE</th><th>STATUS</th><th>DURATION</th><th>TIME</th></tr>
        ${stayCalls.map((c,i) => `<tr class="photo-link-row" onclick="goToCall(${c.id})" title="Click to view this call's detail">
          <td style="color:var(--dim)">${i+1}</td>
          <td>${c.direction==='Outgoing'?'→ ':'← '}${esc(c.caller)}</td>
          <td>${esc(c.call_type_label)}</td>
          <td>${callStatusPill(c)}</td>
          <td style="white-space:nowrap">${c.duration>0?fmtDur(c.duration):'0:00'}</td>
          <td style="white-space:nowrap;font-size:9px">${fmtTs(c.ts)}</td>
        </tr>`).join('')}
      </table>`;

  const stayInteractions = INTERACTIONS.filter(x => x.place_id === id).sort((a,b) => a.ts - b.ts);
  const interactionRowsHtml = stayInteractions.length === 0
    ? ''
    : `<table class="photo-table">
        <tr><th>#</th><th>FROM/TO</th><th>APP</th><th>OVERLAP</th><th>TIME</th></tr>
        ${stayInteractions.map((i,n) => `<tr class="photo-link-row" onclick="goToInteraction(${i.id})" title="Click to view this interaction's detail">
          <td style="color:var(--dim)">${n+1}</td>
          <td>${i.direction==='Outgoing'?'→ ':'← '}${esc(i.counterpart)}</td>
          <td>${interactionAppPill(i)}</td>
          <td>${overlapBadge(i)}</td>
          <td style="white-space:nowrap;font-size:9px">${fmtTs(i.ts)}</td>
        </tr>`).join('')}
      </table>`;

  det.innerHTML = `
    <div class="dp-title" style="display:flex;justify-content:space-between;align-items:center">
      <span>Stay #${p.id} <span id="pd-geocode-${id}" style="font-size:11px;color:var(--dim)">…</span></span>
      <button class="copy-btn" onclick="exportStayReport(${p.id})" title="Generate a standalone HTML report for this stay" style="font-size:9px;letter-spacing:0.5px">⬇ EXPORT STAY REPORT</button>
    </div>
    <div class="dp-sub">
      <a href="https://www.google.com/maps?q=${p.lat},${p.lng}" target="_blank" class="coord-link">${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}</a>
      <button class="copy-btn" onclick="copyText('${p.lat.toFixed(6)},${p.lng.toFixed(6)}')">COPY</button>
      &nbsp;·&nbsp;
      <a href="https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lng}&zoom=16" target="_blank" class="coord-link">OSM↗</a>
    </div>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px">
      <div style="background:var(--panel);padding:8px 10px;border-radius:2px;border:1px solid var(--border)">
        <div style="font-size:8px;color:var(--dim);letter-spacing:1px">ARRIVED</div>
        <div style="font-size:10px;margin-top:3px">${fmtTs(p.entry)}</div>
      </div>
      <div style="background:var(--panel);padding:8px 10px;border-radius:2px;border:1px solid var(--border)">
        <div style="font-size:8px;color:var(--dim);letter-spacing:1px">DEPARTED</div>
        <div style="font-size:10px;margin-top:3px">${fmtTs(p.exit)}</div>
      </div>
      <div style="background:var(--panel);padding:8px 10px;border-radius:2px;border:1px solid var(--border)">
        <div style="font-size:8px;color:var(--dim);letter-spacing:1px">DURATION</div>
        <div style="font-size:14px;font-weight:bold;color:var(--accent);margin-top:3px">${fmtDur(p.duration)}</div>
      </div>
    </div>

    <div class="section-head">PHOTOS AT THIS STAY (${photos.length})</div>
    ${rowsHtml}

    ${sessions.length > 0 ? `
    <div class="section-head">APPS USED DURING THIS STAY (${sessions.length})</div>
    ${appRowsHtml}` : ''}

    ${stayMessages.length > 0 ? `
    <div class="section-head">MESSAGES DURING THIS STAY (${stayMessages.length})</div>
    ${msgRowsHtml}` : ''}

    ${stayCalls.length > 0 ? `
    <div class="section-head">CALLS DURING THIS STAY (${stayCalls.length})</div>
    ${callRowsHtml}` : ''}

    ${stayInteractions.length > 0 ? `
    <div class="section-head">APP INTERACTIONS DURING THIS STAY (${stayInteractions.length})</div>
    ${interactionRowsHtml}` : ''}
  `;

  resolvePlace(p);
}

// Builds a standalone, self-contained HTML report for a single stay —
// arrival/departure/duration, GPS + resolved name, every photo and app
// session tied to that stay, and the chain-of-custody / parameter context
// from this run's Integrity & Parameters panel — and triggers a download.
// Doesn't touch the network: uses whatever name is already resolved
// (resolvePlace already ran when this stay's detail was opened), and falls
// back to raw coordinates if a name was never resolved.

function exportStayReport(id) {
  const p = PLACES.find(x => x.id===id);
  if (!p) return;
  const photos  = PHOTOS.filter(x => x.place_id===id);
  const sessions = APP_SESSIONS.filter(x => x.place_id===id).sort((a,b) => a.start - b.start);
  const stayMessages = MESSAGES.filter(x => x.place_id===id).sort((a,b) => a.ts - b.ts);
  const stayCalls = CALLS.filter(x => x.place_id===id).sort((a,b) => a.ts - b.ts);
  const stayInteractions = INTERACTIONS.filter(x => x.place_id===id).sort((a,b) => a.ts - b.ts);
  const m = REPORT_META;

  const resolvedNameEl = document.getElementById('pd-geocode-'+id);
  const resolvedName = (p.device_place_name) ? p.device_place_name
                      : (resolvedNameEl && resolvedNameEl.textContent.trim() !== '…' && !resolvedNameEl.textContent.startsWith('…'))
                        ? resolvedNameEl.textContent.replace(/^—\\s*/, '')
                        : null;

  const photoRows = photos.length === 0
    ? '<p style="color:#666;font-size:11px">No photos assigned to this stay.</p>'
    : `<table><tr><th>#</th><th>Filename</th><th>Origin</th><th>Timestamp</th><th>Location Method</th><th>Size</th><th>Status</th></tr>
        ${photos.map((ph,i) => `<tr>
          <td>${i+1}</td><td>${esc(ph.filename)}</td>
          <td>${sourcePill(ph)}</td>
          <td>${fmtTs(ph.ts)}</td>
          <td>${esc(ph.method||'—')}</td><td>${ph.w&&ph.h?ph.w+'×'+ph.h:'—'}</td>
          <td>${ph.trashed?'TRASHED':'Active'}</td>
        </tr>`).join('')}
      </table>`;

  const appRows = sessions.length === 0
    ? '<p style="color:#666;font-size:11px">No app usage sessions recorded during this stay.</p>'
    : `<table><tr><th>#</th><th>App / Bundle ID</th><th>Category</th><th>Started</th><th>Duration</th></tr>
        ${sessions.map((s,i) => `<tr>
          <td>${i+1}</td><td>${esc(s.bundle_id)}</td><td>${esc(s.category||'—')}</td>
          <td>${fmtTs(s.start)}</td><td>${fmtDur(s.duration)}</td>
        </tr>`).join('')}
      </table>`;

  const messageRows = stayMessages.length === 0
    ? '<p style="color:#666;font-size:11px">No messages sent or received during this stay.</p>'
    : `<table><tr><th>#</th><th>From/To</th><th>Text</th><th>Channel</th><th>Time</th><th>Attachments</th></tr>
        ${stayMessages.map((msg,i) => `<tr>
          <td>${i+1}</td>
          <td>${msg.is_from_me?'→ ':'← '}${esc(msg.is_from_me ? (msg.chat_name||msg.sender) : msg.sender)}</td>
          <td style="max-width:300px;word-break:break-word">${esc(msg.display_text)}</td>
          <td>${esc(msg.service||'—')}</td>
          <td>${fmtTs(msg.ts)}</td>
          <td>${msg.has_attachment ? msg.attachment_count : '—'}</td>
        </tr>`).join('')}
      </table>`;

  const callRows = stayCalls.length === 0
    ? '<p style="color:#666;font-size:11px">No calls made or received during this stay.</p>'
    : `<table><tr><th>#</th><th>From/To</th><th>Type</th><th>Status</th><th>Duration</th><th>Time</th></tr>
        ${stayCalls.map((c,i) => `<tr>
          <td>${i+1}</td>
          <td>${c.direction==='Outgoing'?'→ ':'← '}${esc(c.caller)}</td>
          <td>${esc(c.call_type_label)}</td>
          <td>${esc(c.status)}</td>
          <td>${c.duration>0?fmtDur(c.duration):'0:00'}</td>
          <td>${fmtTs(c.ts)}</td>
        </tr>`).join('')}
      </table>`;

  const interactionRows = stayInteractions.length === 0
    ? '<p style="color:#666;font-size:11px">No cross-app interactions recorded during this stay.</p>'
    : `<table><tr><th>#</th><th>From/To</th><th>App</th><th>Category</th><th>Overlap?</th><th>Time</th></tr>
        ${stayInteractions.map((i,n) => `<tr>
          <td>${n+1}</td>
          <td>${i.direction==='Outgoing'?'→ ':'← '}${esc(i.counterpart)}</td>
          <td>${esc(i.subcategory||i.bundle_id||'—')}</td>
          <td>${esc(i.category)}</td>
          <td>${i.is_overlap?'Yes — also in Messages/Calls':'No'}</td>
          <td>${fmtTs(i.ts)}</td>
        </tr>`).join('')}
      </table>`;

  const srcRows = [
    ['Cache.sqlite',     m.cache_db_path,  m.cache_sha256],
    ['Photos.sqlite',    m.photos_db_path, m.photos_sha256],
    ['Cloud-V2.sqlite',  m.cloud_db_path,  m.cloud_sha256],
    ['knowledgeC.db',    m.kc_db_path,     m.kc_sha256],
    ['sms.db',           m.sms_db_path,    m.sms_sha256],
    ['CallHistory.storedata', m.calls_db_path, m.calls_sha256],
    ['interactionC.db',  m.interactions_db_path, m.interactions_sha256],
    ['AddressBook.sqlitedb', m.addressbook_db_path, m.addressbook_sha256],
  ].filter(r => r[1]).map(([label, path, hash]) => `<tr>
      <td>${label}</td><td style="word-break:break-all">${esc(path)}</td>
      <td style="font-family:monospace;font-size:9px;word-break:break-all">${hash || 'could not be computed'}</td>
    </tr>`).join('');

  const rp = m.run_params || {};
  
  const dateRow = (rp.start_date || rp.end_date) 
    ? `<tr><td>Date Range Filter</td><td>${rp.start_date || 'Beginning of record'} to ${rp.end_date || 'End of record'}</td></tr>` 
    : '';

  const paramRows = `
    ${dateRow}
    <tr><td>Cluster radius</td><td>${rp.radius_m} m</td></tr>
    <tr><td>Visit time-gap</td><td>${rp.time_gap_hours} h</td></tr>
    <tr><td>Interpolation window</td><td>±${rp.interp_window_secs} s</td></tr>
    <tr><td>GPS rejection distance</td><td>${rp.gps_reject_m} m</td></tr>
    <tr><td>Minimum stay duration</td><td>${rp.min_stay_minutes} min</td></tr>`;

  const generatedAt = new Date().toISOString().replace('T',' ').slice(0,19) + ' UTC';

  const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Stay #${p.id} Report — ${esc(m.tool_name)}</title>
<style>
  body{background:#0a0e1a;color:#cfd8e3;font-family:'Courier New',monospace;font-size:12px;padding:24px;max-width:900px;margin:0 auto}
  h1{color:#4a90d9;font-size:18px;border-bottom:1px solid #1e3a5f;padding-bottom:10px}
  h2{color:#4a90d9;font-size:12px;letter-spacing:1px;text-transform:uppercase;margin-top:28px;border-left:3px solid #4a90d9;padding-left:8px}
  table{border-collapse:collapse;width:100%;margin-top:8px;font-size:11px}
  th,td{border:1px solid #1e3a5f;padding:5px 8px;text-align:left}
  th{background:#0d1220;color:#7fa8d9;text-transform:uppercase;font-size:9px;letter-spacing:0.5px}
  .summary{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px}
  .card{background:#0d1220;border:1px solid #1e3a5f;padding:10px 12px}
  .card .lbl{font-size:8px;color:#7a8aa0;letter-spacing:1px}
  .card .val{font-size:13px;margin-top:4px}
  a{color:#4a90d9}
  .footer{margin-top:30px;font-size:9px;color:#5a6a80;border-top:1px solid #1e3a5f;padding-top:10px}
</style></head>
<body>
  <h1>Stay #${p.id} — Single-Stay Report</h1>
  <div style="font-size:10px;color:#7a8aa0">
    Case: ${esc(m.case_number || '—')} &nbsp;·&nbsp; Examiner: ${esc(m.examiner || '—')} &nbsp;·&nbsp;
    Generated: ${generatedAt} &nbsp;·&nbsp; Source: ${esc(m.tool_name)} v${esc(m.tool_version)}
  </div>

  <h2>Location</h2>
  <div class="summary">
    <div class="card"><div class="lbl">RESOLVED NAME</div><div class="val">${esc(resolvedName || 'Not resolved at export time')}</div></div>
    <div class="card"><div class="lbl">COORDINATES</div><div class="val"><a href="https://www.google.com/maps?q=${p.lat},${p.lng}" target="_blank">${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}</a></div></div>
    <div class="card"><div class="lbl">SOURCE(S)</div><div class="val">${(p.source_dbs||['cache']).join(' + ')}</div></div>
  </div>

  <h2>Timing</h2>
  <div class="summary">
    <div class="card"><div class="lbl">ARRIVED</div><div class="val">${fmtTs(p.entry)}</div></div>
    <div class="card"><div class="lbl">DEPARTED</div><div class="val">${fmtTs(p.exit)}</div></div>
    <div class="card"><div class="lbl">DURATION</div><div class="val">${fmtDur(p.duration)}</div></div>
  </div>

  <h2>Photos at this Stay (${photos.length})</h2>
  ${photoRows}

  <h2>Apps Used During this Stay (${sessions.length})</h2>
  ${appRows}

  <h2>Messages During this Stay (${stayMessages.length})</h2>
  ${messageRows}

  <h2>Calls During this Stay (${stayCalls.length})</h2>
  ${callRows}

  <h2>App Interactions During this Stay (${stayInteractions.length})</h2>
  ${interactionRows}

  <h2>Source Files &amp; Chain of Custody</h2>
  <table><tr><th>Source</th><th>Path</th><th>SHA-256</th></tr>${srcRows}</table>

  <h2>Analysis Parameters Used This Run</h2>
  <table><tr><th>Parameter</th><th>Value</th></tr>${paramRows}</table>
  ${m.notes ? `<h2>Case Notes</h2><p style="font-size:11px">${esc(m.notes)}</p>` : ''}

  <div class="footer">
    Generated from ${esc(m.tool_name)} v${esc(m.tool_version)} — a self-contained excerpt of Stay #${p.id} from the
    full report. No data in this file was transmitted off this device during generation.
  </div>
</body></html>`;

  const blob = new Blob([html], {type: 'text/html'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `stay_${p.id}_report.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Timeline ──────────────────────────────────────────────────────────────────
let timelineActiveTypes = new Set(['stay', 'photo', 'message', 'call']);
let currentTimelineEvents = [];
let selectedTimelineIdx = null;

function toggleTimelineType(type, btn) {
  if (timelineActiveTypes.has(type)) {
    timelineActiveTypes.delete(type);
    btn.classList.remove('active');
  } else {
    timelineActiveTypes.add(type);
    btn.classList.add('active');
  }
  buildTimeline();
}

function buildTimeline() {
  const wrap = document.getElementById('timeline-wrap');
  if (!wrap) return;

  const events = [];
  if (timelineActiveTypes.has('stay')) {
    PLACES.forEach(p => events.push({type:'stay', ts: p.entry, end: p.exit, data: p}));
  }
  if (timelineActiveTypes.has('photo')) {
    PLACES.forEach(p => p.photo_ids.forEach(pid => {
      const ph = PHOTOS.find(x=>x.id===pid);
      if(ph) events.push({type:'photo', ts: ph.ts, data: ph});
    }));
    PHOTOS.filter(p => !p.place_id).forEach(p => events.push({type:'photo', ts: p.ts, data: p}));
  }
  if (timelineActiveTypes.has('message')) {
    MESSAGES.forEach(m => events.push({type:'message', ts: m.ts, data: m}));
  }
  if (timelineActiveTypes.has('call')) {
    CALLS.forEach(c => events.push({type:'call', ts: c.ts, data: c}));
  }
  if (timelineActiveTypes.has('interaction')) {
    INTERACTIONS.forEach(i => events.push({type:'interaction', ts: i.ts, data: i}));
  }

  // Sort flat and assign strict index
  events.sort((a,b)=>(a.ts||0)-(b.ts||0));
  events.forEach((e, i) => e._tl_idx = i);
  currentTimelineEvents = events;

  // Group by UTC day
  const days = {};
  events.forEach(e => {
    if (!e.ts) { (days['Unknown']||=(days['Unknown']=[])).push(e); return; }
    const day = new Date(e.ts*1000).toISOString().slice(0,10);
    (days[day]||(days[day]=[])).push(e);
  });

  let html = '';
  Object.entries(days).sort().forEach(([day, evts]) => {
    html += `<div class="tl-day"><div class="tl-day-head">${day} <span style="color:var(--dim);font-weight:normal">(${evts.length} events)</span></div>`;
    evts.forEach((e,i) => {
      const isLast = i===evts.length-1;
      const selClass = selectedTimelineIdx === e._tl_idx ? ' selected' : '';
      const rowId = `tl-row-${e._tl_idx}`;
      const onClick = `onclick="selectTimelineEvent(${e._tl_idx})"`;

      if (e.type==='stay') {
        html += `<div class="tl-event${selClass}" id="${rowId}" ${onClick}>
          <div class="tl-line"><div class="tl-dot stay"></div>${isLast?'':'<div class="tl-connector"></div>'}</div>
          <div class="tl-body">
            <div class="tl-time">${fmtTs(e.ts)}</div>
            <div class="tl-label" style="color:var(--accent)">📍 Stay #${e.data.id} <span id="tl-gc-${e.data.id}" style="color:var(--dim);font-size:9px"> — loading…</span></div>
            <div class="tl-meta">Duration: ${fmtDur(e.data.duration)} · ${e.data.n_photos > 0 ? e.data.n_photos + ' photo(s)' : '0 photos'}</div>
          </div>
        </div>`;
        resolvePlace(e.data);
      } else if (e.type==='photo') {
        const ph = e.data;
        const locStr = ph.lat ? `${ph.lat.toFixed(4)}, ${ph.lng.toFixed(4)}` : 'no location';
        html += `<div class="tl-event${selClass}" id="${rowId}" ${onClick}>
          <div class="tl-line"><div class="tl-dot photo"></div>${isLast?'':'<div class="tl-connector"></div>'}</div>
          <div class="tl-body">
            <div class="tl-time">${fmtTs(e.ts)}</div>
            <div class="tl-label">📷 ${esc(ph.filename)} ${ph.trashed?'<span class="trash-pill">TRASH</span>':''}</div>
            <div class="tl-meta">${methodPill(ph.method)} ${ph.place_id?'· Stay #'+ph.place_id:''} · ${locStr}</div>
          </div>
        </div>`;
      } else if (e.type==='message') {
        const m = e.data;
        html += `<div class="tl-event${selClass}" id="${rowId}" ${onClick}>
          <div class="tl-line"><div class="tl-dot message"></div>${isLast?'':'<div class="tl-connector"></div>'}</div>
          <div class="tl-body">
            <div class="tl-time">${fmtTs(e.ts)}</div>
            <div class="tl-label">💬 <span style="color:#d99a4a">${m.is_from_me?'→ ':'← '}${esc(m.is_from_me ? (m.chat_name||m.sender) : m.sender)}</span></div>
            <div class="tl-meta">${messagePill(m)} ${esc((m.display_text||'').slice(0,70))} ${m.place_id!=null?'· Stay #'+m.place_id:''}</div>
          </div>
        </div>`;
      } else if (e.type==='call') {
        const c = e.data;
        html += `<div class="tl-event${selClass}" id="${rowId}" ${onClick}>
          <div class="tl-line"><div class="tl-dot call"></div>${isLast?'':'<div class="tl-connector"></div>'}</div>
          <div class="tl-body">
            <div class="tl-time">${fmtTs(e.ts)}</div>
            <div class="tl-label">📞 <span style="color:#4ad97a">${c.direction==='Outgoing'?'→ ':'← '}${esc(c.caller)}</span></div>
            <div class="tl-meta">${callStatusPill(c)} ${esc(c.call_type_label)} · ${c.duration>0?fmtDur(c.duration):'0:00'} ${c.place_id!=null?'· Stay #'+c.place_id:''}</div>
          </div>
        </div>`;
      } else if (e.type==='interaction') {
        const it = e.data;
        html += `<div class="tl-event${selClass}" id="${rowId}" ${onClick}>
          <div class="tl-line"><div class="tl-dot interaction"></div>${isLast?'':'<div class="tl-connector"></div>'}</div>
          <div class="tl-body">
            <div class="tl-time">${fmtTs(e.ts)}</div>
            <div class="tl-label">🔄 <span style="color:#9a6ad9">${it.direction==='Outgoing'?'→ ':'← '}${esc(it.counterpart)}</span> ${overlapBadge(it)}</div>
            <div class="tl-meta">${interactionAppPill(it)} ${it.place_id!=null?'· Stay #'+it.place_id:''}</div>
          </div>
        </div>`;
      }
    });
    html += '</div>';
  });

  wrap.innerHTML = html || '<div style="color:var(--dim);padding:20px">No timeline data for the selected event types.</div>';
}

function selectTimelineEvent(idx) {
  selectedTimelineIdx = idx;
  document.querySelectorAll('.tl-event').forEach(el => el.classList.remove('selected'));
  const rowEl = document.getElementById('tl-row-' + idx);
  if (rowEl) rowEl.classList.add('selected');

  const e = currentTimelineEvents[idx];
  if (!e) return;
  const det = document.getElementById('timeline-detail');
  const row = (lbl, val) => `<tr><td style="color:var(--dim);padding:4px 8px 4px 0;white-space:nowrap;font-size:9px;letter-spacing:1px">${lbl}</td><td style="padding:4px 0">${val||'—'}</td></tr>`;

  let html = '';

  if (e.type === 'stay') {
    const p = e.data;
    html = `
      <div class="dp-title">Stay #${p.id}</div>
      <div class="dp-sub" id="tl-det-gc-${idx}">Loading location…</div>
      <div class="section-head">TIMING</div>
      <table style="width:100%;font-size:10px;border-collapse:collapse">
        ${row('ARRIVED', fmtTs(p.entry))}
        ${row('DEPARTED', fmtTs(p.exit))}
        ${row('DURATION', fmtDur(p.duration))}
      </table>
      <div class="section-head">LOCATION</div>
      <table style="width:100%;font-size:10px;border-collapse:collapse">
        ${row('COORDINATES', `<a href="https://www.google.com/maps?q=${p.lat},${p.lng}" target="_blank" class="coord-link">${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}</a>`)}
      </table>
      <div style="margin-top:20px; text-align:center">
         <button class="copy-btn" style="padding:8px 16px; font-size:10px" onclick="goToPlace(${p.id})">View Full Details in Places Tab ↗</button>
      </div>
    `;
    resolvePlace(p);
    geocode(p.lat, p.lng, lbl => {
       const el = document.getElementById('tl-det-gc-'+idx);
       if (el) el.textContent = lbl;
    });

  } else if (e.type === 'photo') {
    const p = e.data;
    html = `
      <div class="dp-title">${esc(p.filename)} ${p.trashed?'<span class="trash-pill">TRASH</span>':''}</div>
      <div class="dp-sub" id="tl-det-gc-${idx}">${p.lat&&p.lat!==0?'Loading location…':'No coordinates'}</div>
      <div class="section-head">PREVIEW</div>
      <div class="photo-preview" style="margin-top:4px">
        ${(p.kind===1)
          ? `<video id="tl-media-${p.id}" src="${relPath(p)}" ${p.thumbnail_data_uri ? `poster="${p.thumbnail_data_uri}"` : ''} controls preload="metadata" onerror="ppFail(${p.id})" style="max-width:100%;max-height:340px;display:block;border:1px solid var(--border);border-radius:2px"></video>`
          : `<img id="tl-media-${p.id}" src="${relPath(p)}" loading="lazy" alt="${esc(p.filename)}" onerror="ppFail(${p.id})" onclick="expandMedia(this.src)" style="max-width:100%;max-height:340px;display:block;border:1px solid var(--border);border-radius:2px;cursor:zoom-in">`}
         <div id="tl-miss-${p.id}" style="display:none;font-size:10px;color:var(--dim);border:1px dashed var(--border);border-radius:2px;padding:10px;text-align:center;line-height:1.5">
           Preview unavailable.<br><span style="font-family:monospace;font-size:9px;color:var(--dim)">${esc(p.directory ? p.directory+'/'+p.filename : p.filename)}</span>
         </div>
      </div>
      <div class="section-head">METADATA</div>
      <table style="width:100%;font-size:10px;border-collapse:collapse">
        ${row('TIMESTAMP', fmtTs(p.ts))}
        ${row('METHOD', methodPill(p.method))}
      </table>
      <div style="margin-top:20px; text-align:center">
         <button class="copy-btn" style="padding:8px 16px; font-size:10px" onclick="goToPhoto(${p.id})">View Full Details in Photos Tab ↗</button>
      </div>
    `;
    if (p.lat && p.lat!==0) {
      geocode(p.lat, p.lng, lbl => {
        const el = document.getElementById('tl-det-gc-'+idx);
        if(el) el.textContent = lbl;
      });
    }

  } else if (e.type === 'message') {
    const m = e.data;
    html = `
      <div class="dp-title">${m.is_from_me?'To: ':'From: '}${esc(m.is_from_me ? (m.chat_name||m.sender) : m.sender)}</div>
      <div class="section-head">MESSAGE</div>
      <table style="width:100%;font-size:10px;border-collapse:collapse">
        ${row('TEXT', `<div style="white-space:pre-wrap;word-break:break-word">${esc(m.display_text)}</div>`)}
        ${row('TIME', fmtTs(m.ts))}
        ${row('CHANNEL', messagePill(m))}
      </table>
      <div style="margin-top:20px; text-align:center">
         <button class="copy-btn" style="padding:8px 16px; font-size:10px" onclick="goToMessage(${m.id})">View Full Details in Messages Tab ↗</button>
      </div>
    `;
  } else if (e.type === 'call') {
    const c = e.data;
    html = `
      <div class="dp-title">${c.direction==='Outgoing'?'To: ':'From: '}${esc(c.caller)}</div>
      <div class="section-head">CALL</div>
      <table style="width:100%;font-size:10px;border-collapse:collapse">
        ${row('TIME', fmtTs(c.ts))}
        ${row('DURATION', c.duration>0?fmtDur(c.duration):'0:00')}
        ${row('STATUS', callStatusPill(c))}
        ${row('TYPE', esc(c.call_type_label))}
      </table>
      <div style="margin-top:20px; text-align:center">
         <button class="copy-btn" style="padding:8px 16px; font-size:10px" onclick="goToCall(${c.id})">View Full Details in Calls Tab ↗</button>
      </div>
    `;
  } else if (e.type === 'interaction') {
    const i = e.data;
    html = `
      <div class="dp-title">${i.direction==='Outgoing'?'To: ':'From: '}${esc(i.counterpart)}</div>
      <div class="section-head">INTERACTION</div>
      <table style="width:100%;font-size:10px;border-collapse:collapse">
        ${row('TIME', fmtTs(i.ts))}
        ${row('APP', interactionAppPill(i))}
      </table>
      <div style="margin-top:20px; text-align:center">
         <button class="copy-btn" style="padding:8px 16px; font-size:10px" onclick="goToInteraction(${i.id})">View Full Details in Interactions Tab ↗</button>
      </div>
    `;
  }

  det.innerHTML = html;
}

// ── Photos tab ────────────────────────────────────────────────────────────────
function setPhotoFilter(f, btn) {
  photoFilter = f;
  document.querySelectorAll('.fb-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderPhotoList();
}
function filterPhotos() {
  photoSearch = document.getElementById('photo-search').value.toLowerCase();
  renderPhotoList();
}

function getFilteredPhotos() {
  return PHOTOS.filter(p => {
    const fullPath = (p.directory ? p.directory + '/' : '') + p.filename;
    if (photoSearch && !fullPath.toLowerCase().includes(photoSearch)) return false;
    if (photoFilter==='gps') return p.method==='exif-gps';
    if (photoFilter==='inferred') return p.method==='interpolated'||p.method==='nearest-ping';
    if (photoFilter==='unknown') return !p.lat||p.method==='unknown';
    if (photoFilter==='trash') return p.trashed;
    return true;
  });
}

function renderPhotoList() {
  const photos = getFilteredPhotos();
  const list = document.getElementById('photo-list');
  const label = document.getElementById('photo-count-label');
  label.textContent = `PHOTOS (${photos.length} / ${PHOTOS.length})`;
  list.innerHTML = photos.map(p => `
    <div class="photo-row${p.trashed?' trashed':''}${selectedPhotoId===p.id?' selected':''}" onclick="selectPhoto(${p.id})">
      <div class="pr-name">${esc(p.filename)} ${p.trashed?'<span class="trash-pill">TRASH</span>':''}</div>
      <div class="pr-meta">${fmtTs(p.ts)} · ${methodPill(p.method)}</div>
      <div class="pr-src">${sourcePill(p)}</div>
      ${p.ping_zpk != null ? `<div class="pr-ping">🛰 Z_PK <span style="color:var(--yellow);font-family:monospace">${p.ping_zpk}</span> · ${p.ping_hacc != null ? '~'+Math.round(p.ping_hacc)+'m' : '—'}</div>` : ''}
    </div>
  `).join('');
}

function selectPhoto(id) {
  selectedPhotoId = id;
  renderPhotoList(); // refresh selection highlight
  const p = PHOTOS.find(x=>x.id===id);
  if (!p) return;
  const det = document.getElementById('photo-detail');

  const place = p.place_id ? PLACES.find(x=>x.id===p.place_id) : null;
  const coordHtml = p.lat && p.lat!==0 && p.lat!==-180
    ? `<a href="https://www.google.com/maps?q=${p.lat},${p.lng}" target="_blank" class="coord-link">${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}</a>
       <button class="copy-btn" onclick="copyText('${p.lat},${p.lng}')">COPY</button>
       <a href="https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lng}&zoom=16" target="_blank" class="coord-link" style="margin-left:5px">OSM↗</a>`
    : '<span style="color:var(--dim)">No coordinates available</span>';

  function row(lbl, val) {
    return `<tr><td style="width:150px; color:var(--dim);padding:4px 8px 4px 0;white-space:nowrap;font-size:9px;letter-spacing:1px">${lbl}</td><td style="padding:4px 0">${val||'—'}</td></tr>`;
  }

  det.innerHTML = `
    <div class="dp-title">${esc(p.filename)} ${p.trashed?'<span class="trash-pill">TRASH</span>':''}</div>
    <div class="dp-sub" id="ph-geocode-${id}" style="min-height:14px">${p.lat&&p.lat!==0?'Loading location…':''}</div>

    ${p.filename ? `
    <div class="section-head">PREVIEW</div>
    <div class="photo-preview" style="margin-top:4px">
      ${(p.kind===1)
        ? `<video id="pp-media-${id}" src="${relPath(p)}" ${p.thumbnail_data_uri ? `poster="${p.thumbnail_data_uri}"` : ''} controls preload="metadata" onerror="ppFail(${id})" style="max-width:100%;max-height:340px;display:block;border:1px solid var(--border);border-radius:2px"></video>`
        : `<img id="pp-media-${id}" src="${relPath(p)}" loading="lazy" alt="${esc(p.filename)}" onerror="ppFail(${id})" onclick="expandMedia(this.src)" style="max-width:100%;max-height:340px;display:block;border:1px solid var(--border);border-radius:2px;cursor:zoom-in">`}
      <div id="pp-miss-${id}" style="display:none;font-size:10px;color:var(--dim);border:1px dashed var(--border);border-radius:2px;padding:10px;text-align:center;line-height:1.5">
        Preview unavailable — either the <b>DCIM</b> folder isn't in the same directory as this report, or the browser can't render this format (e.g.&nbsp;HEIC).<br>
        <span style="font-family:monospace;font-size:9px;color:var(--dim)">${esc(p.directory ? p.directory+'/'+p.filename : p.filename)}</span>
      </div>
      <div style="margin-top:3px"><a href="#" onclick="expandMedia('${relPath(p)}');return false" class="coord-link" style="font-size:9px">OPEN FILE ↗</a></div>
    </div>` : ''}

    <div class="section-head">METADATA</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('TIMESTAMP', fmtTs(p.ts))}
      ${row('FILE', esc(p.directory ? p.directory+'/'+p.filename : p.filename))}
      ${row('TYPE', p.uti || '—')}
      ${row('KIND', p.kind===1 ? 'Video' : 'Photo')}
      ${row('DIMENSIONS', p.w&&p.h ? p.w+'×'+p.h : '—')}
      ${row('DURATION', p.duration > 0 ? p.duration.toFixed(2)+'s' : '—')}
    </table>

    <div class="section-head">ORIGIN / SOURCE</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('CLASSIFICATION', sourcePill(p))}
      ${row('CATEGORY', p.source_category || p.src_cat || '—')}
      ${row('SOURCE APP', p.source_subcategory || p.src_sub || '—')}
      ${(p.source_bundle_id || p.src_bundle) ? row('BUNDLE ID', `<span style="font-family:monospace;font-size:9px;color:var(--dim)">${esc(p.source_bundle_id || p.src_bundle)}</span>`) : ''}
      ${row('ZIMPORTEDBY', p.importedby != null ? String(p.importedby) : '—')}
      ${row('CONFIDENCE', p.source_confidence || p.src_conf || '—')}
    </table>

    <div class="section-head">LOCATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('METHOD', methodPill(p.method))}
      ${row('COORDINATES', coordHtml)}
      ${row('ACCURACY', p.accuracy ? '~'+Math.round(p.accuracy)+'m' : '—')}
      ${row('STAY', place ? `<a href="#" onclick="goToPlace(${place.id});return false" style="color:var(--accent)">Stay #${place.id} ${place.device_place_name ? '— '+esc(place.device_place_name)+' ' : ''}→</a>` : 'Not within a detected stay')}
    </table>

    ${(p.ping_zpk != null) ? `
    <div class="section-head">CACHE.SQLITE ANCHOR PING</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('Z_PK', '<span style="font-family:monospace;color:var(--yellow)">' + p.ping_zpk + '</span>')}
      ${row('PING DATE/TIME', p.ping_ts ? new Date(p.ping_ts*1000).toISOString().replace('T',' ').slice(0,19)+' UTC' : '—')}
      ${row('ZHORIZONTALACCURACY', p.ping_hacc != null ? '~'+Math.round(p.ping_hacc)+'m' : '—')}
      ${row('TIME DELTA', p.ts && p.ping_ts ? (Math.abs(p.ts - p.ping_ts) < 60
          ? Math.round(Math.abs(p.ts - p.ping_ts))+'s from photo'
          : Math.round(Math.abs(p.ts - p.ping_ts)/60)+'m from photo') : '—')}
    </table>` : ''}
    ${p.lat && p.lat!==0 ? `
    <div class="section-head">MAP PREVIEW</div>
    <div id="mini-map-${id}" style="height:340px;aspect-ratio:1/1;max-width:340px;border:1px solid var(--border);border-radius:2px;margin-top:4px"></div>` : ''}
  `;

  // Geocode
  if (p.lat && p.lat!==0 && p.lat!==-180) {
    geocode(p.lat, p.lng, lbl => {
      const el = document.getElementById('ph-geocode-'+id);
      if(el) el.textContent = lbl;
    });
    // Mini-map
    setTimeout(() => {
      const mm = document.getElementById('mini-map-'+id);
      if (!mm) return;
      const m = L.map(mm, {zoomControl:false}).setView([p.lat, p.lng], 15);
      addBasemapTiles(m, currentBasemap);
      // High-contrast marker: bright magenta/pink fill with a thick white halo
      // ring stands out clearly against satellite, street, or dark map tiles.
      L.circleMarker([p.lat, p.lng], {
        radius: 9, color: '#ffffff', weight: 3,
        fillColor: '#ff2d8a', fillOpacity: 1
      }).addTo(m);
    }, 50);
  }
}

// ── App Usage (knowledgeC.db /app/usage sessions) ─────────────────────────────
function setAppFilter(f, btn) {
  appFilter = f;
  document.querySelectorAll('#appusage-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderAppList();
}
function filterAppSessions() {
  appSearch = document.getElementById('app-search').value.toLowerCase();
  renderAppList();
}

function getFilteredAppSessions() {
  return APP_SESSIONS.filter(s => {
    if (appSearch && !(s.bundle_id||'').toLowerCase().includes(appSearch)
                  && !(s.subcategory||'').toLowerCase().includes(appSearch)) return false;
    if (appFilter !== 'all' && s.category !== appFilter) return false;
    return true;
  });
}

function renderAppList() {
  const sessions = getFilteredAppSessions();
  const list = document.getElementById('app-list');
  const label = document.getElementById('app-count-label');
  if (!list || !label) return;
  label.textContent = `APP USAGE SESSIONS (${sessions.length} / ${APP_SESSIONS.length})`;
  list.innerHTML = sessions.map(s => `
    <div class="photo-row${selectedAppId===s.zpk?' selected':''}" onclick="selectAppSession(${s.zpk})">
      <div class="pr-name">${esc(s.bundle_id)}</div>
      <div class="pr-meta">${fmtTs(s.start)} · ${fmtDur(s.duration)}</div>
      <div class="pr-src">${sourcePill(s)}</div>
      ${s.place_id != null ? `<div class="pr-ping">📍 Stay #${s.place_id}</div>` : ''}
    </div>
  `).join('');
}

function selectAppSession(zpk) {
  selectedAppId = zpk;
  renderAppList();
  const s = APP_SESSIONS.find(x => x.zpk === zpk);
  if (!s) return;
  const det = document.getElementById('app-detail');

  const place = s.place_id ? PLACES.find(x => x.id === s.place_id) : null;
  const coordHtml = s.lat && s.lat !== 0 && s.lat !== -180
    ? `<a href="https://www.google.com/maps?q=${s.lat},${s.lng}" target="_blank" class="coord-link">${s.lat.toFixed(6)}, ${s.lng.toFixed(6)}</a>
       <button class="copy-btn" onclick="copyText('${s.lat},${s.lng}')">COPY</button>`
    : '<span style="color:var(--dim)">No coordinates available</span>';

  function row(lbl, val) {
    return `<tr><td style="width:150px; color:var(--dim);padding:4px 8px 4px 0;white-space:nowrap;font-size:9px;letter-spacing:1px">${lbl}</td><td style="padding:4px 0">${val||'—'}</td></tr>`;
  }

  det.innerHTML = `
    <div class="dp-title">${esc(s.bundle_id)}</div>
    <div class="dp-sub" id="app-geocode-${zpk}" style="min-height:14px">${s.lat&&s.lat!==0?'Loading location…':''}</div>

    <div class="section-head">SESSION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('STARTED', s.start_str)}
      ${row('ENDED', s.end_str)}
      ${row('DURATION', fmtDur(s.duration))}
      ${row('Z_PK', '<span style="font-family:monospace;color:var(--yellow)">'+s.zpk+'</span>')}
    </table>

    <div class="section-head">CLASSIFICATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('CATEGORY', sourcePill(s))}
      ${row('BUNDLE ID', `<span style="font-family:monospace;font-size:9px;color:var(--dim)">${esc(s.bundle_id)}</span>`)}
      ${row('CONFIDENCE', s.confidence || '—')}
    </table>

    <div class="section-head">LOCATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('METHOD', methodPill(s.location_method))}
      ${row('COORDINATES', coordHtml)}
      ${row('STAY', place ? `<a href="#" onclick="goToPlace(${place.id});return false" style="color:var(--accent)">Stay #${place.id} ${place.device_place_name ? '— '+esc(place.device_place_name)+' ' : ''}→</a>` : 'Not within a detected stay — location interpolated from nearby GPS pings')}
    </table>
  `;

  if (s.lat && s.lat !== 0 && s.lat !== -180) {
    geocode(s.lat, s.lng, lbl => {
      const el = document.getElementById('app-geocode-'+zpk);
      if(el) el.textContent = lbl;
    });
  }
}

// ── Messages ─────────────────────────────────────────────────────────────────
function setMessageFilter(f, btn) {
  messageFilter = f;
  document.querySelectorAll('#messages-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderMessageList();
}
function filterMessages() {
  messageSearch = document.getElementById('message-search').value.toLowerCase();
  renderMessageList();
}

function getFilteredMessages() {
  return MESSAGES.filter(m => {
    if (messageSearch && !(m.display_text||'').toLowerCase().includes(messageSearch)
                      && !(m.sender||'').toLowerCase().includes(messageSearch)
                      && !(m.chat_name||'').toLowerCase().includes(messageSearch)) return false;
    if (messageFilter === 'group' && !m.is_group) return false;
    else if (messageFilter === 'attachment' && !m.has_attachment) return false;
    else if (messageFilter === 'iMessage' && m.service !== 'iMessage') return false;
    else if (messageFilter === 'SMS' && m.service !== 'SMS' && m.service !== 'RCS') return false;
    return true;
  });
}

function messagePill(m) {
  const color = m.service === 'iMessage' ? '#4a90d9' : '#d99a4a';
  return `<span class="src-pill" style="border-color:${color};color:${color}">${esc(m.service||'?')}</span>`;
}

// Shows how a displayed sender/caller name was determined — never hides
// the raw artifact value, just labels where the friendly name came from.
function contactSourcePill(source) {
  const labels = {device: 'ON-DEVICE NAME', addressbook: 'VIA ADDRESSBOOK', raw: 'RAW / UNRESOLVED', me: 'THIS DEVICE'};
  const colors = {device: '#4a90d9', addressbook: '#4ad97a', raw: '#7a8aa0', me: '#7a8aa0'};
  const c = colors[source] || '#7a8aa0';
  return `<span class="src-pill" style="border-color:${c};color:${c};font-size:8px">${labels[source] || source || 'UNKNOWN'}</span>`;
}

function renderMessageList() {
  const msgs = getFilteredMessages();
  const list = document.getElementById('message-list');
  const label = document.getElementById('message-count-label');
  if (!list || !label) return;
  label.textContent = `MESSAGES (${msgs.length} / ${MESSAGES.length})`;
  list.innerHTML = msgs.map(m => `
    <div class="photo-row${selectedMessageId===m.id?' selected':''}" onclick="selectMessage(${m.id})">
      <div class="pr-name">${m.is_from_me?'→ ':'← '}${esc(m.is_from_me ? (m.chat_name||m.sender) : m.sender)}${m.is_group?' (group)':''}</div>
      <div class="pr-meta">${fmtTs(m.ts)} · ${esc((m.display_text||'').slice(0,60))}</div>
      <div class="pr-src">${messagePill(m)}${m.has_attachment?' 📎':''}${m.is_tapback?' 👍':''}</div>
      ${m.place_id != null ? `<div class="pr-ping">📍 Stay #${m.place_id}</div>` : ''}
    </div>
  `).join('');
}

function selectMessage(id) {
  selectedMessageId = id;
  renderMessageList();
  const m = MESSAGES.find(x => x.id === id);
  if (!m) return;
  const det = document.getElementById('message-detail');

  const place = m.place_id ? PLACES.find(x => x.id === m.place_id) : null;
  const coordHtml = m.lat && m.lat !== 0 && m.lat !== -180
    ? `<a href="https://www.google.com/maps?q=${m.lat},${m.lng}" target="_blank" class="coord-link">${m.lat.toFixed(6)}, ${m.lng.toFixed(6)}</a>
       <button class="copy-btn" onclick="copyText('${m.lat},${m.lng}')">COPY</button>`
    : '<span style="color:var(--dim)">No coordinates available</span>';

  function row(lbl, val) {
    return `<tr><td style="width:150px; color:var(--dim);padding:4px 8px 4px 0;white-space:nowrap;font-size:9px;letter-spacing:1px">${lbl}</td><td style="padding:4px 0">${val||'—'}</td></tr>`;
  }

  det.innerHTML = `
    <div class="dp-title">${m.is_from_me?'To: ':'From: '}${esc(m.is_from_me ? (m.chat_name||m.sender) : m.sender)}</div>
    <div class="dp-sub" id="msg-geocode-${id}" style="min-height:14px">${m.lat&&m.lat!==0?'Loading location…':''}</div>

    <div class="section-head">MESSAGE</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('TEXT', `<div style="white-space:pre-wrap;word-break:break-word">${esc(m.display_text)}</div>`)}
      ${row('SENT/RECEIVED', fmtTs(m.ts))}
      ${row('DIRECTION', m.is_from_me ? 'Sent (from this device)' : 'Received')}
      ${row('READ', m.is_read ? 'Yes' : 'No')}
    </table>

    <div class="section-head">PARTICIPANTS</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('SENDER', `${esc(m.sender)} ${contactSourcePill(m.sender_source)}` + (m.sender_source==='addressbook' && m.sender_raw && m.sender_raw!==m.sender ? `<br><span style="color:var(--dim);font-size:9px">Raw: ${esc(m.sender_raw)}</span>` : ''))}
      ${row('CONVERSATION', m.is_group ? `Group (${m.n_participants} participants)${m.chat_name?' — '+esc(m.chat_name):''}` : '1:1')}
    </table>

    <div class="section-head">CLASSIFICATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('CHANNEL', messagePill(m))}
      ${row('CATEGORY', esc(m.category) + (m.subcategory ? ' / '+esc(m.subcategory) : ''))}
      ${row('ATTACHMENTS', m.has_attachment ? `${m.attachment_count} — ${esc((m.attachment_names||[]).join(', '))}` : 'None')}
      ${row('TAPBACK', m.is_tapback ? esc(m.tapback_type) : '—')}
      ${row('SYSTEM EVENT', m.is_system ? 'Yes (group action / membership change)' : 'No')}
    </table>

    <div class="section-head">LOCATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('METHOD', methodPill(m.location_method))}
      ${row('COORDINATES', coordHtml)}
      ${row('STAY', place ? `<a href="#" onclick="goToPlace(${place.id});return false" style="color:var(--accent)">Stay #${place.id} ${place.device_place_name ? '— '+esc(place.device_place_name)+' ' : ''}→</a>` : 'Not within a detected stay — location interpolated from nearby GPS pings')}
    </table>
  `;

  if (m.lat && m.lat !== 0 && m.lat !== -180) {
    geocode(m.lat, m.lng, lbl => {
      const el = document.getElementById('msg-geocode-'+id);
      if(el) el.textContent = lbl;
    });
  }
}

// Jump straight to a specific message's detail in the Messages tab — used
// from a Stay's "messages here" list and from the per-stay export's links.
function goToMessage(id) {
  messageFilter = 'all';
  messageSearch = '';
  const search = document.getElementById('message-search');
  if (search) search.value = '';
  document.querySelectorAll('#messages-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('#messages-sidebar .fb-btn[onclick*="\\'all\\'"]');
  if (allBtn) allBtn.classList.add('active');

  switchTab('messages');
  setTimeout(() => {
    selectMessage(id);
    const row = document.querySelector(`.photo-row[onclick="selectMessage(${id})"]`);
    if (row) row.scrollIntoView({block:'center'});
  }, 50);
}

// ── Calls ────────────────────────────────────────────────────────────────────
function setCallFilter(f, btn) {
  callFilter = f;
  document.querySelectorAll('#calls-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderCallList();
}
function filterCalls() {
  callSearch = document.getElementById('call-search').value.toLowerCase();
  renderCallList();
}

function getFilteredCalls() {
  return CALLS.filter(c => {
    if (callSearch && !(c.caller||'').toLowerCase().includes(callSearch)
                   && !(c.address||'').toLowerCase().includes(callSearch)) return false;
    if (callFilter === 'incoming' && c.direction !== 'Incoming') return false;
    else if (callFilter === 'outgoing' && c.direction !== 'Outgoing') return false;
    else if (callFilter === 'missed' && c.status !== 'Missed') return false;
    else if (callFilter === 'voip' && c.call_type_label !== 'VoIP') return false;
    return true;
  });
}

function callStatusPill(c) {
  const color = c.status === 'Missed' ? '#d94a4a' : c.status === 'Not Connected' ? '#d99a4a' : '#4ad97a';
  return `<span class="src-pill" style="border-color:${color};color:${color}">${esc(c.status)}</span>`;
}

function renderCallList() {
  const calls = getFilteredCalls();
  const list = document.getElementById('call-list');
  const label = document.getElementById('call-count-label');
  if (!list || !label) return;
  label.textContent = `CALLS (${calls.length} / ${CALLS.length})`;
  list.innerHTML = calls.map(c => `
    <div class="photo-row${selectedCallId===c.id?' selected':''}" onclick="selectCall(${c.id})">
      <div class="pr-name">${c.direction==='Outgoing'?'→ ':'← '}${esc(c.caller)}</div>
      <div class="pr-meta">${fmtTs(c.ts)} · ${c.duration>0?fmtDur(c.duration):'0:00'} · ${esc(c.call_type_label)}</div>
      <div class="pr-src">${callStatusPill(c)}</div>
      ${c.place_id != null ? `<div class="pr-ping">📍 Stay #${c.place_id}</div>` : ''}
    </div>
  `).join('');
}

function selectCall(id) {
  selectedCallId = id;
  renderCallList();
  const c = CALLS.find(x => x.id === id);
  if (!c) return;
  const det = document.getElementById('call-detail');

  const place = c.place_id ? PLACES.find(x => x.id === c.place_id) : null;
  const coordHtml = c.lat && c.lat !== 0 && c.lat !== -180
    ? `<a href="https://www.google.com/maps?q=${c.lat},${c.lng}" target="_blank" class="coord-link">${c.lat.toFixed(6)}, ${c.lng.toFixed(6)}</a>
       <button class="copy-btn" onclick="copyText('${c.lat},${c.lng}')">COPY</button>`
    : '<span style="color:var(--dim)">No coordinates available</span>';

  function row(lbl, val) {
    return `<tr><td style="width:150px; color:var(--dim);padding:4px 8px 4px 0;white-space:nowrap;font-size:9px;letter-spacing:1px">${lbl}</td><td style="padding:4px 0">${val||'—'}</td></tr>`;
  }

  det.innerHTML = `
    <div class="dp-title">${c.direction==='Outgoing'?'To: ':'From: '}${esc(c.caller)}</div>
    <div class="dp-sub" id="call-geocode-${id}" style="min-height:14px">${c.lat&&c.lat!==0?'Loading location…':''}</div>

    <div class="section-head">CALL</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('TIME', fmtTs(c.ts))}
      ${row('DURATION', c.duration>0?fmtDur(c.duration):'0:00 (not connected)')}
      ${row('DIRECTION', c.direction)}
      ${row('STATUS', callStatusPill(c))}
      ${row('CALLER', `${esc(c.caller)} ${contactSourcePill(c.caller_source)}`)}
      ${row('NUMBER', esc(c.address||'—'))}
      ${row('ON-DEVICE NAME (ZNAME, raw)', esc(c.name||'—'))}
      ${row('READ', c.is_read ? 'Yes' : 'No')}
    </table>

    <div class="section-head">CLASSIFICATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('CALL TYPE', esc(c.call_type_label))}
      ${row('CATEGORY', esc(c.category) + (c.subcategory ? ' / '+esc(c.subcategory) : ''))}
      ${row('SERVICE PROVIDER', `<span style="font-family:monospace;font-size:9px;color:var(--dim)">${esc(c.service_provider||'—')}</span>`)}
      ${row('DISCONNECT CAUSE (raw)', c.disconnect_cause != null ? `<span style="font-family:monospace">${c.disconnect_cause}</span> <span style="color:var(--dim);font-size:9px">(iOS internal code — not independently verified, shown for reference only)</span>` : '—')}
    </table>

    <div class="section-head">LOCATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('METHOD', methodPill(c.location_method))}
      ${row('COORDINATES', coordHtml)}
      ${row('STAY', place ? `<a href="#" onclick="goToPlace(${place.id});return false" style="color:var(--accent)">Stay #${place.id} ${place.device_place_name ? '— '+esc(place.device_place_name)+' ' : ''}→</a>` : 'Not within a detected stay — location interpolated from nearby GPS pings')}
    </table>
  `;

  if (c.lat && c.lat !== 0 && c.lat !== -180) {
    geocode(c.lat, c.lng, lbl => {
      const el = document.getElementById('call-geocode-'+id);
      if(el) el.textContent = lbl;
    });
  }
}

// Jump straight to a specific call's detail in the Calls tab — used from a
// Stay's "calls here" list and from the per-stay export's links.
function goToCall(id) {
  callFilter = 'all';
  callSearch = '';
  const search = document.getElementById('call-search');
  if (search) search.value = '';
  document.querySelectorAll('#calls-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('#calls-sidebar .fb-btn[onclick*="\\'all\\'"]');
  if (allBtn) allBtn.classList.add('active');

  switchTab('calls');
  setTimeout(() => {
    selectCall(id);
    const row = document.querySelector(`.photo-row[onclick="selectCall(${id})"]`);
    if (row) row.scrollIntoView({block:'center'});
  }, 50);
}

// ── Interactions ─────────────────────────────────────────────────────────────
function setInteractionFilter(f, btn) {
  interactionFilter = f;
  document.querySelectorAll('#interactions-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderInteractionList();
}
function filterInteractions() {
  interactionSearch = document.getElementById('interaction-search').value.toLowerCase();
  renderInteractionList();
}

function getFilteredInteractions() {
  return INTERACTIONS.filter(i => {
    if (interactionSearch && !(i.counterpart||'').toLowerCase().includes(interactionSearch)
                           && !(i.bundle_id||'').toLowerCase().includes(interactionSearch)
                           && !(i.subcategory||'').toLowerCase().includes(interactionSearch)) return false;
    if (interactionFilter === 'incoming' && i.direction !== 'Incoming') return false;
    else if (interactionFilter === 'outgoing' && i.direction !== 'Outgoing') return false;
    else if (interactionFilter === 'overlap' && !i.is_overlap) return false;
    else if (interactionFilter === 'new' && i.is_overlap) return false;
    return true;
  });
}

function interactionAppPill(i) {
  return `<span class="src-pill" style="border-color:#4a90d9;color:#4a90d9">${esc(i.subcategory||i.bundle_id||'?')}</span>`;
}
function overlapBadge(i) {
  return i.is_overlap
    ? `<span class="src-pill" style="border-color:#d99a4a;color:#d99a4a" title="This activity is also captured — with more detail — in the Messages/Calls tab">⚠ OVERLAP</span>`
    : '';
}

function renderInteractionList() {
  const items = getFilteredInteractions();
  const list = document.getElementById('interaction-list');
  const label = document.getElementById('interaction-count-label');
  if (!list || !label) return;
  label.textContent = `INTERACTIONS (${items.length} / ${INTERACTIONS.length})`;
  list.innerHTML = items.map(i => `
    <div class="photo-row${selectedInteractionId===i.id?' selected':''}" onclick="selectInteraction(${i.id})">
      <div class="pr-name">${i.direction==='Outgoing'?'→ ':'← '}${esc(i.counterpart)}</div>
      <div class="pr-meta">${fmtTs(i.ts)} · ${esc(i.category)}</div>
      <div class="pr-src">${interactionAppPill(i)}${overlapBadge(i)}</div>
      ${i.place_id != null ? `<div class="pr-ping">📍 Stay #${i.place_id}</div>` : ''}
    </div>
  `).join('');
}

function selectInteraction(id) {
  selectedInteractionId = id;
  renderInteractionList();
  const i = INTERACTIONS.find(x => x.id === id);
  if (!i) return;
  const det = document.getElementById('interaction-detail');

  const place = i.place_id ? PLACES.find(x => x.id === i.place_id) : null;
  const coordHtml = i.lat && i.lat !== 0 && i.lat !== -180
    ? `<a href="https://www.google.com/maps?q=${i.lat},${i.lng}" target="_blank" class="coord-link">${i.lat.toFixed(6)}, ${i.lng.toFixed(6)}</a>
       <button class="copy-btn" onclick="copyText('${i.lat},${i.lng}')">COPY</button>`
    : '<span style="color:var(--dim)">No coordinates available</span>';

  function row(lbl, val) {
    return `<tr><td style="width:150px; color:var(--dim);padding:4px 8px 4px 0;white-space:nowrap;font-size:9px;letter-spacing:1px">${lbl}</td><td style="padding:4px 0">${val||'—'}</td></tr>`;
  }

  det.innerHTML = `
    <div class="dp-title" style="display:flex;justify-content:space-between;align-items:center">
      <span>${i.direction==='Outgoing'?'To: ':'From: '}${esc(i.counterpart)}</span>
      ${overlapBadge(i)}
    </div>
    <div class="dp-sub" id="interaction-geocode-${id}" style="min-height:14px">${i.lat&&i.lat!==0?'Loading location…':''}</div>

    ${i.is_overlap ? `<div style="background:#1a1408;border:1px solid #4a3a1e;color:#d99a4a;font-size:9px;padding:6px 8px;margin:6px 0">
      ⚠ This activity is native ${esc(i.bundle_id)} traffic — it's also captured, with more detail, in the
      ${i.bundle_id==='com.apple.MobileSMS'
        ? `<a href="#" onclick="switchTab('messages');return false" style="color:#d99a4a;text-decoration:underline">Messages tab</a>`
        : `<a href="#" onclick="switchTab('calls');return false" style="color:#d99a4a;text-decoration:underline">Calls tab</a>`}.
    </div>` : ''}

    <div class="section-head">INTERACTION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('TIME', fmtTs(i.ts))}
      ${row('DIRECTION', i.direction)}
      ${row('COUNTERPART', `${esc(i.counterpart)} ${contactSourcePill(i.counterpart_source==='addressbook_or_raw'?'addressbook':i.counterpart_source)}` + (i.counterpart_raw && i.counterpart_raw!==i.counterpart ? `<br><span style="color:var(--dim);font-size:9px">Raw: ${esc(i.counterpart_raw)}</span>` : ''))}
      ${row('RECIPIENT COUNT', i.recipient_count || '1')}
      ${row('GROUP/CHAT NAME', i.group_name ? esc(i.group_name) : '—')}
      ${row('IS RESPONSE', i.is_response ? 'Yes' : 'No')}
    </table>

    <div class="section-head">CLASSIFICATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('APP', interactionAppPill(i))}
      ${row('BUNDLE ID', `<span style="font-family:monospace;font-size:9px;color:var(--dim)">${esc(i.bundle_id||'—')}</span>`)}
      ${row('CATEGORY', esc(i.category) + (i.subcategory ? ' / '+esc(i.subcategory) : ''))}
    </table>

    <div class="section-head">LOCATION</div>
    <table style="width:100%;font-size:10px;border-collapse:collapse">
      ${row('METHOD', methodPill(i.location_method))}
      ${row('COORDINATES', coordHtml)}
      ${row('STAY', place ? `<a href="#" onclick="goToPlace(${place.id});return false" style="color:var(--accent)">Stay #${place.id} ${place.device_place_name ? '— '+esc(place.device_place_name)+' ' : ''}→</a>` : 'Not within a detected stay — location interpolated from nearby GPS pings')}
    </table>
  `;

  if (i.lat && i.lat !== 0 && i.lat !== -180) {
    geocode(i.lat, i.lng, lbl => {
      const el = document.getElementById('interaction-geocode-'+id);
      if(el) el.textContent = lbl;
    });
  }
}

// Jump straight to a specific interaction's detail in the Interactions tab.
function goToInteraction(id) {
  interactionFilter = 'all';
  interactionSearch = '';
  const search = document.getElementById('interaction-search');
  if (search) search.value = '';
  document.querySelectorAll('#interactions-sidebar .fb-btn').forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('#interactions-sidebar .fb-btn[onclick*="\\'all\\'"]');
  if (allBtn) allBtn.classList.add('active');

  switchTab('interactions');
  setTimeout(() => {
    selectInteraction(id);
    const row = document.querySelector(`.photo-row[onclick="selectInteraction(${id})"]`);
    if (row) row.scrollIntoView({block:'center'});
  }, 50);
}

// ── Recovered Data: click-to-sort columns ─────────────────────────────────────
// Generic — works on any table inside #view-recovered without per-column JS,
// since recovered_view.py embeds a data-type ("num"/"dt"/"bool"/"text") on
// each <th> and a machine-sortable data-sort value on each <td> (e.g. an ISO
// timestamp behind a human-readable display string).
let _recoveredSortState = {};

function sortRecoveredTable(th) {
  const table = th.closest('table');
  const tbody = table.querySelector('tbody');
  const col = parseInt(th.dataset.col, 10);
  const type = th.dataset.type || 'text';
  const state = _recoveredSortState[table.id] || { col: -1, dir: 1 };
  const dir = (state.col === col) ? -state.dir : 1;
  _recoveredSortState[table.id] = { col, dir };

  table.querySelectorAll('th .sort-arrow').forEach(s => s.textContent = '');
  th.querySelector('.sort-arrow').textContent = dir === 1 ? '▲' : '▼';

  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {
    const av = a.children[col].dataset.sort || '';
    const bv = b.children[col].dataset.sort || '';
    let cmp;
    if (type === 'num') {
      const an = parseFloat(av), bn = parseFloat(bv);
      const aValid = av !== '' && !isNaN(an), bValid = bv !== '' && !isNaN(bn);
      if (!aValid && !bValid) cmp = 0;
      else if (!aValid) return 1;
      else if (!bValid) return -1;
      else cmp = an - bn;
    } else if (type === 'dt') {
      const aValid = av !== '', bValid = bv !== '';
      if (!aValid && !bValid) cmp = 0;
      else if (!aValid) return 1;
      else if (!bValid) return -1;
      else cmp = Date.parse(av) - Date.parse(bv);
    } else {
      cmp = av.localeCompare(bv);
    }
    return cmp * dir;
  });
  rows.forEach(r => tbody.appendChild(r));
}

// ── Recovered Data: export ─────────────────────────────────────────────────────
function _csvEscape(s) {
  if (s === null || s === undefined) s = '';
  s = String(s);
  if (/[",\\r\\n]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
  return s;
}

function _downloadBlob(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// Exports every recovered-data table as one CSV file, one labeled section per
// source (each source has a different column layout, so this isn't forced
// into a single flat table — the "=== label ===" lines mark each section).
function exportRecoveredCSV() {
  // One clean CSV file per source, not one combined file: each source has a
  // different column layout, and spreadsheet apps (Excel in particular)
  // sniff the delimiter/column count from a file's FIRST line -- a shared
  // file with a non-tabular "=== label ===" divider line at the top made
  // the whole import collapse to a single unsplit text column. Separate
  // files sidestep that entirely, at the cost of one download per source.
  const tables = document.querySelectorAll('#view-recovered table');
  if (!tables.length) return;
  tables.forEach((table, idx) => {
    const headers = Array.from(table.querySelectorAll('thead th'))
      .map(th => th.childNodes[0].textContent.trim());
    const lines = [headers.map(_csvEscape).join(',')];
    table.querySelectorAll('tbody tr').forEach(tr => {
      const cells = Array.from(tr.children).map(td => td.textContent.trim());
      lines.push(cells.map(_csvEscape).join(','));
    });
    const csv = lines.join('\\r\\n');
    const slug = (table.id || ('source' + idx)).replace('recovered-table-', '');
    // Stagger slightly -- firing several a.click() downloads in the same
    // tick in a loop causes some browsers to silently drop all but the first.
    setTimeout(() => _downloadBlob(csv, 'recovered_' + slug + '.csv', 'text/csv'), idx * 200);
  });
}

// Exports the Recovered Data tab as its own standalone, self-contained HTML
// file — same dark styling as the parent report (copied live from this
// page's own <style> block, so there's no separate copy to keep in sync),
// viewable and shareable independent of the rest of the report.
function exportRecoveredHTML() {
  const styleTag = document.querySelector('style').outerHTML;
  const viewHtml = document.getElementById('view-recovered').outerHTML;
  const caseNum = (typeof REPORT_META !== 'undefined' && REPORT_META.case_number) || '';
  const title = 'Recovered Data' + (caseNum ? ' - ' + caseNum : '');
  const parts = [];
  parts.push('<!DOCTYPE html>');
  parts.push('<html lang="en"><head><meta charset="UTF-8">');
  parts.push('<title>' + title.replace(/</g, '&lt;') + '</title>');
  parts.push(styleTag);
  parts.push('<style>body{background:var(--bg);color:var(--text);font-family:var(--font);padding:20px}.view{display:flex !important}</style>');
  parts.push('</head><body>');
  parts.push('<h2 style="color:var(--accent)">🗑 RECOVERED DATA</h2>');
  parts.push('<div style="color:var(--dim);font-size:10px;margin-bottom:14px">Exported ' +
    new Date().toISOString() + ' from an iNexus report' +
    (caseNum ? ' (case ' + caseNum + ')' : '') +
    '. See the original report&#39;s Integrity &amp; Parameters panel for full ' +
    'chain-of-custody context — this export does not include it.</div>');
  parts.push(viewHtml);
  parts.push('</body></html>');
  _downloadBlob(parts.join('\\n'), 'recovered_data_export.html', 'text/html');
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
  initMap();
  geocodeAllPlaces();   // throttled/deduped — see geocode()/resolvePlace() above
});
"""

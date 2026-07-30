"""Renders the map-pin sidebar cards and the stays list-view cards
shown in the report's left sidebar."""

from ..utils import apple_ts, esc_html, fmt_dt, fmt_dur

def dt_to_js(dt):
    if dt is None:
        return "null"
    return f"{dt.timestamp() * 1000:.0f}"  # JS milliseconds



def _render_place_cards_map(places):
    parts = []
    for p in places:
        lat = "%.5f" % p['lat']
        lng = "%.5f" % p['lng']
        pid = p['id']
        ts  = fmt_dt(apple_ts(p['entry']))
        dur = fmt_dur(p['duration'])
        n   = len(p['photos'])
        device_name = p.get("device_place_name")
        label_html = (f'<b>{esc_html(device_name)}</b>' if device_name
                       else f'<span style="color:var(--dim);font-size:9px">{ts} UTC</span>')
        device_badge = ('<span class="device-src-badge" title="Resolved from device location history">📍 ON-DEVICE</span>'
                         if device_name else '')
        source_dbs = p.get("source_dbs", ["cache"])
        corroborated_badge = (
            '<span class="corroborated-badge" title="Independently recorded in both Cache.sqlite and Cloud-V2.sqlite">✓✓ CORROBORATED</span>'
            if len(source_dbs) > 1 else '')
        parts.append(
            f'''<div class="place-card" id="pc-{pid}" onclick="focusPlace({pid})">
          <div class="place-num">STAY #{pid} {device_badge} {corroborated_badge}</div>
          <div class="place-label" id="label-{pid}">
            {label_html}
          </div>
          <div class="place-coords">
            <a href="https://www.google.com/maps?q={lat},{lng}" target="_blank" class="coord-link">{lat}, {lng}</a>
          </div>
          <div class="place-meta">
            ⏱ <span>{dur}</span>
            📷 <span class="ph-count">{n}</span>
          </div>
        </div>'''
        )
    return '\n'.join(parts)


def _render_place_cards_list(places):
    parts = []
    for p in places:
        lat = "%.5f" % p['lat']
        lng = "%.5f" % p['lng']
        pid = p['id']
        ts  = fmt_dt(apple_ts(p['entry']))
        dur = fmt_dur(p['duration'])
        n   = len(p['photos'])
        device_name = p.get("device_place_name")
        label_html = (f'<b>{esc_html(device_name)}</b>' if device_name
                       else f'<span style="color:var(--dim);font-size:9px">{ts} UTC</span>')
        device_badge = ('<span class="device-src-badge" title="Resolved from device location history">📍 ON-DEVICE</span>'
                         if device_name else '')
        source_dbs = p.get("source_dbs", ["cache"])
        corroborated_badge = (
            '<span class="corroborated-badge" title="Independently recorded in both Cache.sqlite and Cloud-V2.sqlite">✓✓ CORROBORATED</span>'
            if len(source_dbs) > 1 else '')
        parts.append(
            f'''<div class="place-card" id="plc-{pid}" onclick="selectPlace({pid})">
          <div class="place-num">STAY #{pid} {device_badge} {corroborated_badge}</div>
          <div class="place-label" id="plabel-{pid}">
            {label_html}
          </div>
          <div class="place-coords">{lat}, {lng}</div>
          <div class="place-meta">
            ⏱ <span>{dur}</span>
            📷 <span class="ph-count">{n}</span>
          </div>
        </div>'''
        )
    return '\n'.join(parts)



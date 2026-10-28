"""Static CSS for the report shell. No Python interpolation happens
here — this is applied verbatim into <head>."""

MAIN_STYLES = """<style>
:root{
  --bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--border:#30363d;
  --text:#e6edf3;--dim:#768390;--accent:#3393c5;--green:#3dd68c;
  --yellow:#DDE667;--red:#e05c5c;--orange:#f0883e;
  --font:'SF Mono','Consolas','Liberation Mono',monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:12px;height:100vh;display:flex;flex-direction:column;overflow:hidden}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}

/* NAV */
#nav{background:var(--panel);border-bottom:1px solid var(--border);padding:0 14px;display:flex;align-items:center;gap:0;flex-shrink:0;height:38px}
#nav h1{font-size:11px;color:var(--dim);letter-spacing:2px;margin-right:20px;white-space:nowrap}
.nav-tab{padding:0 14px;height:38px;display:flex;align-items:center;cursor:pointer;font-size:10px;letter-spacing:1px;color:var(--dim);border-bottom:2px solid transparent;transition:all .15s}
.nav-tab:hover{color:var(--text)}
.nav-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
#nav-right{margin-left:auto;font-size:9px;color:var(--dim);white-space:nowrap}

/* LAYOUT */
#main{flex:1;display:flex;overflow:hidden}
.view{display:none;flex:1;overflow:hidden}
.view.active{display:flex}

/* SHARED SIDEBAR */
.sidebar{width:320px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.sidebar-head{padding:8px 12px;border-bottom:1px solid var(--border);font-size:9px;color:var(--dim);letter-spacing:1px;display:flex;align-items:center;gap:8px;flex-shrink:0}
.sidebar-body{flex:1;overflow-y:auto}
.sidebar-body::-webkit-scrollbar{width:4px}
.sidebar-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* BASEMAP SWITCHER */
.basemap-btn{
  background:var(--panel2); border:1px solid var(--border); color:var(--dim);
  font-size:9px; letter-spacing:0.5px; padding:5px 4px; border-radius:3px;
  cursor:pointer; font-family:inherit; transition:all .15s;
}
.basemap-btn:hover{border-color:var(--accent); color:var(--text)}
.basemap-btn.active{background:var(--accent); border-color:var(--accent); color:#0d1117; font-weight:bold}

/* STATS BAR */
#stats-bar{background:var(--panel2);border-bottom:1px solid var(--border);padding:6px 14px;display:flex;gap:20px;flex-shrink:0;flex-wrap:wrap}
.stat{display:flex;flex-direction:column;align-items:center}
.stat .val{font-size:16px;font-weight:bold;color:var(--accent)}
.stat .lbl{font-size:8px;color:var(--dim);letter-spacing:1px;margin-top:1px}

/* PLACE CARDS */
.place-card{padding:10px 12px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .1s}
.place-card:hover{background:var(--panel2)}
.place-card.active{background:rgba(51,147,197,0.1);border-left:3px solid var(--accent)}
.place-num{font-size:9px;color:var(--dim);letter-spacing:1px}
.device-src-badge{
  font-size:8px; background:rgba(61,214,140,0.12); color:var(--green);
  border:1px solid rgba(61,214,140,0.3); padding:1px 5px; border-radius:3px;
  letter-spacing:0.3px; margin-left:6px; white-space:nowrap;
}
.corroborated-badge{
  font-size:8px; background:rgba(51,147,197,0.15); color:var(--accent);
  border:1px solid rgba(51,147,197,0.4); padding:1px 5px; border-radius:3px;
  letter-spacing:0.3px; margin-left:6px; white-space:nowrap; font-weight:bold;
}
.place-label{font-size:11px;color:var(--text);margin:2px 0;font-weight:bold}
.place-coords{font-size:9px;color:var(--dim);font-family:monospace}
.place-meta{font-size:9px;color:var(--dim);margin-top:4px;display:flex;gap:8px;flex-wrap:wrap}
.place-meta span{color:var(--text)}
.ph-count{background:var(--accent);color:#000;border-radius:10px;padding:1px 6px;font-size:8px;font-weight:bold}

/* DETAIL PANEL */
.detail-panel{flex:1;overflow-y:auto;background:var(--bg);padding:16px}
.detail-panel::-webkit-scrollbar{width:4px}
.detail-panel::-webkit-scrollbar-thumb{background:var(--border)}
.dp-title{font-size:13px;font-weight:bold;margin-bottom:4px;color:var(--accent)}
.dp-sub{font-size:9px;color:var(--dim);margin-bottom:14px}

.section-head{font-size:8px;letter-spacing:2px;color:var(--dim);margin:14px 0 6px;border-bottom:1px solid var(--border);padding-bottom:4px}

/* PHOTO TABLE */
.photo-table{width:100%;border-collapse:collapse;font-size:10px}
.photo-table th{font-size:8px;letter-spacing:1px;color:var(--dim);padding:4px 6px;border-bottom:1px solid var(--border);text-align:left;white-space:nowrap}
.photo-table td{padding:5px 6px;border-bottom:1px solid rgba(48,54,61,0.5);vertical-align:top}
.photo-table tr:hover td{background:var(--panel2)}
.photo-table tr.trashed td{opacity:0.55}
.photo-table tr.photo-link-row{cursor:pointer}
.photo-table tr.photo-link-row:hover td{background:rgba(51,147,197,0.1)}
.method-pill{display:inline-block;font-size:7px;padding:1px 5px;border-radius:10px;letter-spacing:0.5px;white-space:nowrap}
.m-exif{background:rgba(61,214,140,0.15);color:var(--green);border:1px solid rgba(61,214,140,0.3)}
.m-interp{background:rgba(221,230,103,0.12);color:var(--yellow);border:1px solid rgba(221,230,103,0.3)}
.m-nearest{background:rgba(240,136,62,0.12);color:var(--orange);border:1px solid rgba(240,136,62,0.3)}
.m-unknown{background:rgba(118,131,144,0.12);color:var(--dim);border:1px solid var(--border)}
.trash-pill{display:inline-block;font-size:7px;padding:1px 5px;border-radius:10px;background:rgba(224,92,92,0.15);color:var(--red);border:1px solid rgba(224,92,92,0.3)}

/* MAP */
#map-canvas{flex:1;min-height:0}
#map-wrap{flex:1;display:flex;flex-direction:column}

/* TIMELINE */
#timeline-wrap{flex:1;overflow-y:auto;padding:16px}
#timeline-wrap::-webkit-scrollbar{width:4px}
#timeline-wrap::-webkit-scrollbar-thumb{background:var(--border)}
.tl-day{margin-bottom:24px}
.tl-day-head{font-size:9px;letter-spacing:2px;color:var(--dim);padding:4px 0;border-bottom:1px solid var(--border);margin-bottom:10px}
.tl-event{display:flex;gap:10px;margin-bottom:4px;align-items:flex-start;cursor:pointer;padding:6px 8px;border-radius:4px;transition:background 0.1s}
.tl-event:hover{background:var(--panel2)}
.tl-event.selected{background:rgba(51,147,197,0.1);border-left:3px solid var(--accent)}
.tl-line{display:flex;flex-direction:column;align-items:center;width:16px;flex-shrink:0;height:100%}
.tl-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;margin-top:2px}
.tl-dot.stay{background:var(--accent)}
.tl-dot.move{background:var(--dim)}
.tl-dot.photo{background:var(--yellow)}
.tl-dot.message{background:#d99a4a}
.tl-dot.call{background:#4ad97a}
.tl-dot.interaction{background:#9a6ad9}
.tl-connector{width:2px;flex:1;background:var(--border);min-height:8px}
.tl-body{flex:1}
.tl-time{font-size:9px;color:var(--dim)}
.tl-label{font-size:10px;color:var(--text);margin:1px 0}
.tl-meta{font-size:9px;color:var(--dim)}

/* PHOTO LIST VIEW */
#photos-sidebar .place-card{cursor:default}
.photo-row{padding:8px 12px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .1s}
.photo-row:hover{background:var(--panel2)}
.photo-row.selected{background:rgba(51,147,197,0.1);border-left:3px solid var(--accent)}
.photo-row.trashed{opacity:0.6;border-left:3px solid rgba(224,92,92,0.3)}
.pr-name{font-size:10px;color:var(--text)}
.pr-meta{font-size:9px;color:var(--dim);margin-top:2px}
.pr-ping{font-size:9px;color:var(--dim);margin-top:1px;opacity:0.8}
.pr-src{margin-top:2px}

/* FILTER BAR */
.filter-bar{padding:6px 12px;border-bottom:1px solid var(--border);display:flex;gap:4px;flex-wrap:wrap;flex-shrink:0}
.fb-btn{background:var(--panel2);border:1px solid var(--border);color:var(--dim);padding:2px 8px;font-size:9px;cursor:pointer;border-radius:2px;font-family:var(--font)}
.fb-btn:hover{color:var(--text);border-color:var(--dim)}
.fb-btn.active{background:rgba(51,147,197,0.12);color:var(--accent);border-color:var(--accent)}

/* SEARCH */
.search-bar{padding:6px 12px;border-bottom:1px solid var(--border);flex-shrink:0}
.search-bar input{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:4px 8px;font-size:10px;font-family:var(--font);border-radius:2px;outline:none}
.search-bar input:focus{border-color:var(--accent)}

/* GEOCODE STATUS */
#geocode-status{font-size:9px;color:var(--dim);padding:4px 12px;border-bottom:1px solid var(--border);flex-shrink:0;min-height:18px}

/* COORD LINK */
.coord-link{color:var(--accent);font-size:9px;font-family:monospace}
.copy-btn{background:none;border:1px solid var(--border);color:var(--dim);padding:1px 5px;font-size:8px;cursor:pointer;font-family:var(--font);border-radius:2px;margin-left:4px}
.copy-btn:hover{color:var(--text)}

/* UNPLACED SECTION */
.unplaced-banner{background:rgba(221,230,103,0.06);border:1px solid rgba(221,230,103,0.2);color:var(--yellow);padding:6px 10px;font-size:9px;margin-bottom:12px;border-radius:2px}

/* MINI MAP popup */
.popup-inner{min-width:160px;font-family:var(--font);font-size:10px;color:#222}
.popup-inner b{font-size:11px}

/* INTEGRITY & PARAMETERS PANEL */
#integrity-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:flex-start;justify-content:center;z-index:2000;overflow-y:auto;padding:40px 16px}
#integrity-overlay.open{display:flex}
#integrity-panel{background:var(--panel);border:1px solid var(--accent);border-radius:4px;max-width:760px;width:100%;padding:20px 24px;font-size:11px;line-height:1.6}
#integrity-panel h2{font-size:13px;color:var(--accent);letter-spacing:1px;margin-bottom:4px}
#integrity-panel .sub{color:var(--dim);font-size:9px;margin-bottom:16px}
#integrity-panel h3{font-size:10px;color:var(--accent2);letter-spacing:1px;text-transform:uppercase;margin:16px 0 6px;border-bottom:1px solid var(--border);padding-bottom:3px}
#integrity-panel table{width:100%;border-collapse:collapse;margin-bottom:4px}
#integrity-panel td{padding:3px 6px;font-size:10px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top}
#integrity-panel td.lbl{color:var(--dim);width:200px;white-space:nowrap}
#integrity-panel td.val{color:var(--text);font-family:monospace;word-break:break-all}
.hash-ok{color:#7ee787}
.hash-missing{color:var(--yellow)}
.param-overridden{color:var(--yellow)}
.param-default{color:var(--text)}
#integrity-close{position:absolute;top:14px;right:18px;background:none;border:1px solid var(--border);color:var(--dim);padding:3px 10px;font-size:10px;cursor:pointer;border-radius:2px;font-family:var(--font)}
#integrity-close:hover{color:var(--text);border-color:var(--accent)}
#integrity-panel{position:relative}
.case-note{color:var(--dim);font-size:9px;margin-top:14px;border-top:1px solid var(--border);padding-top:10px}
</style>
"""

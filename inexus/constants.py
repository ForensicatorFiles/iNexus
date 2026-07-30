"""
Tool identity and tunable analysis defaults.

Bump TOOL_VERSION whenever functionality changes (new data sources, new
report features, behavior changes) so reports/printouts/CLI banners stay
traceable to the exact build that produced them. Cosmetic-only edits don't
need a bump. Full version history: see CHANGELOG.md.
"""

TOOL_NAME    = "iNexus"
TOOL_VERSION = "1.0.0"

# ── Version history (see CHANGELOG.md for full detail) ─────────────────────────
# 1.0.0  Rebranded from "iOS Location Correlator" to iNexus, version reset to
#        mark this as the first public release under the new name. No
#        functional change from iOS Location Correlator v1.3.0 — same
#        package, same behavior, same output — verified by diffing generated
#        report output byte-for-byte before and after the rename (only the
#        tool-name string itself differs). See CHANGELOG.md for the full
#        feature history carried over from the prior name, including
#        freelist-based deleted-row recovery (-recover-deleted), transparent
#        WAL/SHM reconciliation, and the sortable/exportable/mappable
#        Recovered Data views.

# ── Constants (defaults — all overridable via CLI flags, see cli.parse_args()) ──
APPLE_EPOCH = 978307200        # seconds from Unix epoch to Apple epoch (2001-01-01)
DEFAULT_CLUSTER_RADIUS_M      = 150     # metres: visits within this radius → same "place"
DEFAULT_MIN_STAY_MINUTES      = 3       # minimum stay duration to report as a place
DEFAULT_INTERP_WINDOW_SECS    = 120     # ±2 min window to search for nearest GPS ping
DEFAULT_CLUSTER_TIME_GAP_HRS  = 4       # hours: max gap to merge same-location visits
DEFAULT_PLACE_GPS_REJECT_M    = 500     # metres: reject place match if photo GPS this far off

TRANSPORT_LABELS = {1: "Walking", 2: "Running", 3: "Automotive", 4: "Cycling",
                    5: "Bus", 6: "Train", 7: "Flight", 8: "Boat", 0: "Unknown"}

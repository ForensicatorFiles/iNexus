"""Load and classify call records from CallHistory.storedata, with
caller name resolution against AddressBook.sqlitedb when supplied."""

import sqlite3

from ..db import _open_sqlite_or_die
from ..utils import normalize_phone, unix_ts
from ..classification import categorize_bundle_id

# ZSERVICE_PROVIDER values that need a hand mapping rather than falling
# through to categorize_bundle_id()'s third-party-app default: these are
# Apple's own calling stack, not apps from knowledgeC's app-usage world,
# and don't match _APPLE_SYSTEM_BUNDLES' casing/bundle-ID conventions.
_CALL_SERVICE_OVERRIDES = {
    "com.apple.Telephony": ("Cellular", "Phone Call", "high"),
    "com.apple.FaceTime":  ("Apple System App", "FaceTime", "high"),
}

def classify_call(service_provider):
    """
    Classify a CallHistory.storedata record using the same bundle-ID
    category taxonomy as classify_message()/classify_app_session() — so a
    WhatsApp or Signal call gets the same "Messaging App"/"Social Media"
    badge it would as an app-usage session or a message's rich-content
    balloon. ZSERVICE_PROVIDER carries a real bundle ID for third-party VoIP
    apps (e.g. 'UKFA9XBX6K.net.whatsapp.WhatsApp'); native cellular and
    FaceTime calls use fixed Apple service-provider strings handled by
    _CALL_SERVICE_OVERRIDES instead, since they don't fit the bundle-ID
    conventions categorize_bundle_id() expects.

    Returns (category, subcategory, confidence).
    """
    if service_provider in _CALL_SERVICE_OVERRIDES:
        return _CALL_SERVICE_OVERRIDES[service_provider]
    if service_provider:
        return categorize_bundle_id(service_provider, None)
    return "Unknown", "Unknown", "low"


def load_calls(path, address_book=None):
    """
    Loads call records from an iOS CallHistory.storedata (Phone/FaceTime
    call log, including third-party VoIP apps that register with CallKit).

    Schema/semantics notes specific to this database:
      - ZDATE is a CoreData timestamp in whole SECONDS since the Apple
        epoch — unlike sms.db's message.date, which is nanoseconds. Mixing
        these two date conventions up is the single easiest mistake when
        adding a new iOS artifact parser, so this is called out explicitly
        rather than assumed. See unix_ts() vs unix_ts_ns().
      - ZANSWERED is NOT a reliable "was this call connected" signal for
        OUTGOING calls: in sample data, many ZORIGINATED=1 rows with
        ZANSWERED=0 nonetheless have a multi-minute ZDURATION, meaning the
        call clearly connected. ZANSWERED only behaves as expected for
        INCOMING calls. So call status here is derived from ZDURATION for
        outgoing calls and from ZANSWERED for incoming calls — see
        _call_status() below — rather than trusting ZANSWERED uniformly.
      - ZDISCONNECTED_CAUSE values are NOT given a confident human label
        here: the same cause code (6) appears on both missed incoming
        calls and normally-ended answered incoming calls in sample data,
        so any fixed code→label mapping would be guessing. The raw integer
        is surfaced in the report instead of an invented interpretation.
      - ZADDRESS/ZNAME already carry the raw number and any on-device
        cached contact name directly on the call record. ZNAME (when
        present) takes priority over an AddressBook.sqlitedb lookup, since
        it's what iOS itself resolved the number to at call time — closer
        to ground truth for that specific call than a present-day Contacts
        snapshot, which could have been edited since. AddressBook is only
        used to fill in a name when ZNAME is empty.
      - ZCALLTYPE: 0 = third-party VoIP (the app is named via
        ZSERVICE_PROVIDER), 1 = native cellular, 8 = FaceTime — confirmed
        against ZSERVICE_PROVIDER in sample data rather than assumed from
        undocumented Apple internals.

    Returns a list of call dicts. Returns an empty list (not an error) if
    the file opens but has no call rows.
    """
    address_book = address_book or {}
    conn, cur = _open_sqlite_or_die(path)

    try:
        cur.execute("SELECT 1 FROM ZCALLRECORD LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        raise RuntimeError(
            f"{path} doesn't look like an iOS CallHistory.storedata — no "
            f"'ZCALLRECORD' table found. Confirm this is the Phone call log, "
            f"not e.g. a backup manifest."
        )

    _CALL_TYPE_LABELS = {0: "VoIP", 1: "Cellular", 8: "FaceTime"}

    def _call_status(answered, originated, duration):
        if originated:
            return "Connected" if (duration or 0) > 0 else "Not Connected"
        return "Answered" if answered else "Missed"

    cur.execute("""
        SELECT Z_PK, ZDATE, ZDURATION, ZADDRESS, ZNAME, ZANSWERED, ZCALLTYPE,
               ZORIGINATED, ZDISCONNECTED_CAUSE, ZSERVICE_PROVIDER,
               ZREAD, ZUNIQUE_ID, ZISO_COUNTRY_CODE
        FROM ZCALLRECORD
        ORDER BY ZDATE
    """)

    calls = []
    for r in cur.fetchall():
        d = dict(r)
        ts = unix_ts(d["ZDATE"])
        if ts is None:
            continue   # malformed/zero timestamp — skip rather than mis-sort it to epoch

        category, subcategory, confidence = classify_call(d["ZSERVICE_PROVIDER"])
        originated = bool(d["ZORIGINATED"])
        answered   = bool(d["ZANSWERED"])
        duration   = d["ZDURATION"] or 0.0
        status     = _call_status(answered, originated, duration)

        if d["ZNAME"]:
            caller, caller_source = d["ZNAME"], "device"
        else:
            resolved = address_book.get(normalize_phone(d["ZADDRESS"])) if d["ZADDRESS"] else None
            caller, caller_source = (resolved, "addressbook") if resolved else (d["ZADDRESS"] or "Unknown", "raw")

        calls.append({
            "id":               d["Z_PK"],
            "ts":               ts,
            "duration":         duration,
            "address":          d["ZADDRESS"],
            "name":             d["ZNAME"],
            "caller":           caller,
            "caller_source":    caller_source,
            "originated":       originated,
            "direction":        "Outgoing" if originated else "Incoming",
            "answered":         answered,
            "status":           status,
            "call_type":        d["ZCALLTYPE"],
            "call_type_label":  _CALL_TYPE_LABELS.get(d["ZCALLTYPE"], "Unknown"),
            "service_provider": d["ZSERVICE_PROVIDER"],
            "category":         category,
            "subcategory":      subcategory,
            "confidence":       confidence,
            "is_read":          bool(d["ZREAD"]),
            "disconnect_cause": d["ZDISCONNECTED_CAUSE"],
            "unique_id":        d["ZUNIQUE_ID"],
            "iso_country_code": d["ZISO_COUNTRY_CODE"],
            # Filled in by correlate_app_sessions() (reused — see load comment in main())
            "start": ts, "end": ts + duration,
            "lat": None, "lng": None, "location_method": None,
            "location_accuracy": None, "place_id": None,
        })

    conn.close()
    return calls


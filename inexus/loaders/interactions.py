"""Load cross-app interaction records (e.g. shared-content / social
app interactions) from interactionC.db, flagging overlap with
sms.db/CallHistory.storedata where applicable."""

import sqlite3
from collections import defaultdict

from ..db import _open_sqlite_or_die
from ..utils import normalize_phone, unix_ts
from ..classification import categorize_bundle_id

# Bundle IDs whose activity is already captured — with considerably more
# detail — by sms.db (Messages) and CallHistory.storedata (Phone/FaceTime).
# interactionC.db rows for these aren't excluded (per design decision: flag
# rather than drop), but are marked is_overlap=True so the UI can visually
# distinguish "this is genuinely new information" from "you've already seen
# this exact activity in the Messages/Calls tab, just from CoreDuet's
# cross-app interaction log instead."
_OVERLAP_BUNDLE_IDS = {"com.apple.MobileSMS", "com.apple.facetime", "com.apple.InCallService"}

def load_interactions(path, address_book=None):
    """
    Loads cross-app interaction records from an iOS interactionC.db
    (CoreDuet's "Interactions" database — the donation log Siri uses to
    drive "frequently contacted" / app-suggestion predictions).

    Why this is worth loading alongside sms.db/CallHistory.storedata rather
    than being redundant with them: those two only cover Apple's native
    Messages and Phone/FaceTime apps. interactionC.db captures communication
    activity from EVERY app that donates interactions to Siri — in sample
    data this includes Mail, Snapchat, Skype, Telegram, Viber, LINE, Zoom,
    Microsoft Teams, WhatsApp, Signal, and imo — none of which sms.db or
    CallHistory.storedata know anything about. The bundle IDs that DO
    overlap with those two databases (native SMS/FaceTime/InCallService) are
    still loaded here, just flagged via is_overlap so the UI can distinguish
    "new information" from "you've already seen this."

    Schema/semantics notes:
      - ZSTARTDATE/ZENDDATE/ZCREATIONDATE are whole-SECONDS CoreData
        timestamps, same convention as Cache.sqlite/CallHistory.storedata —
        NOT nanoseconds like sms.db's message.date. See unix_ts().
      - ZDIRECTION: 0 = Incoming (ZSENDER points to a ZCONTACTS row — someone
        else originated it), 1 = Outgoing (ZSENDER is NULL — the device
        owner originated it; recipients are in Z_2INTERACTIONRECIPIENT
        instead). Confirmed against sample data rather than assumed.
      - ZCONTACTS.ZIDENTIFIER carries the same kind of raw phone/email value
        sms.db/CallHistory.storedata do, so the same address_book resolution
        (see load_addressbook()) applies directly — phone numbers matched
        after normalize_phone(), emails matched case-insensitively. As with
        the other loaders, the raw identifier is always preserved alongside
        any resolved name.
      - For outgoing (group-capable) interactions, "counterpart" summarizes
        all recipients from the junction table — a single name if there's
        exactly one, "Name +N more" if there are several. For incoming,
        it's simply the resolved sender.

    Returns a list of interaction dicts. Returns an empty list (not an
    error) if the file opens but has no interaction rows.
    """
    address_book = address_book or {}
    conn, cur = _open_sqlite_or_die(path)

    try:
        cur.execute("SELECT 1 FROM ZINTERACTIONS LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        raise RuntimeError(
            f"{path} doesn't look like an iOS interactionC.db — no "
            f"'ZINTERACTIONS' table found. Confirm this is CoreDuet's "
            f"Interactions database, not e.g. a backup manifest."
        )

    def _resolve(identifier):
        """Look up a raw phone/email against address_book; returns (name_or_None, source)."""
        if not identifier:
            return None, "raw"
        key = identifier.strip().lower() if "@" in identifier else normalize_phone(identifier)
        resolved = address_book.get(key)
        return (resolved, "addressbook") if resolved else (identifier, "raw")

    contacts = {}
    for row in cur.execute("SELECT Z_PK, ZDISPLAYNAME, ZIDENTIFIER FROM ZCONTACTS"):
        contacts[row["Z_PK"]] = {"display_name": row["ZDISPLAYNAME"], "identifier": row["ZIDENTIFIER"]}

    # Recipients per interaction (outgoing, possibly group) — see docstring
    # for why the junction columns are joined in this (initially
    # counter-intuitive) direction.
    recipients_by_interaction = defaultdict(list)
    cur.execute("""
        SELECT j.Z_3INTERACTIONRECIPIENT AS interaction_id, c.ZDISPLAYNAME, c.ZIDENTIFIER
        FROM Z_2INTERACTIONRECIPIENT j
        JOIN ZCONTACTS c ON c.Z_PK = j.Z_2RECIPIENTS
    """)
    for row in cur.fetchall():
        recipients_by_interaction[row["interaction_id"]].append(
            {"display_name": row["ZDISPLAYNAME"], "identifier": row["ZIDENTIFIER"]})

    cur.execute("""
        SELECT Z_PK, ZSTARTDATE, ZENDDATE, ZCREATIONDATE, ZBUNDLEID, ZTARGETBUNDLEID,
               ZDIRECTION, ZSENDER, ZGROUPNAME, ZDOMAINIDENTIFIER, ZACCOUNT,
               ZRECIPIENTCOUNT, ZISRESPONSE, ZUUID
        FROM ZINTERACTIONS
        ORDER BY ZSTARTDATE
    """)

    interactions = []
    for r in cur.fetchall():
        d = dict(r)
        ts = unix_ts(d["ZSTARTDATE"]) or unix_ts(d["ZCREATIONDATE"])
        if ts is None:
            continue   # malformed/zero timestamp — skip rather than mis-sort it to epoch
        end_ts = unix_ts(d["ZENDDATE"]) or ts

        category, subcategory, confidence = categorize_bundle_id(d["ZBUNDLEID"], None)
        direction = "Incoming" if d["ZDIRECTION"] == 0 else "Outgoing"
        is_overlap = d["ZBUNDLEID"] in _OVERLAP_BUNDLE_IDS

        recipients = recipients_by_interaction.get(d["Z_PK"], [])

        if direction == "Incoming":
            sender_info = contacts.get(d["ZSENDER"], {})
            raw_id = sender_info.get("identifier")
            device_name = sender_info.get("display_name")
            if device_name:
                counterpart, counterpart_source = device_name, "device"
            else:
                resolved, source = _resolve(raw_id)
                counterpart, counterpart_source = (resolved or "Unknown", source)
            counterpart_raw = raw_id
        else:
            if not recipients:
                counterpart, counterpart_source, counterpart_raw = "Me (no recipient on record)", "device", None
            else:
                names = []
                for rc in recipients:
                    if rc["display_name"]:
                        names.append(rc["display_name"])
                    else:
                        resolved, _src = _resolve(rc["identifier"])
                        names.append(resolved or rc["identifier"] or "Unknown")
                counterpart = names[0] if len(names) == 1 else f"{names[0]} +{len(names)-1} more"
                counterpart_source = "device" if recipients[0]["display_name"] else "addressbook_or_raw"
                counterpart_raw = ", ".join(rc["identifier"] or "?" for rc in recipients)

        interactions.append({
            "id":                 d["Z_PK"],
            "ts":                 ts,
            "end_ts":             end_ts,
            "bundle_id":          d["ZBUNDLEID"],
            "target_bundle_id":   d["ZTARGETBUNDLEID"],
            "category":           category,
            "subcategory":        subcategory,
            "confidence":         confidence,
            "direction":          direction,
            "is_overlap":         is_overlap,
            "counterpart":        counterpart,
            "counterpart_raw":    counterpart_raw,
            "counterpart_source": counterpart_source,
            "recipient_count":    len(recipients) or (d["ZRECIPIENTCOUNT"] or 0),
            "group_name":         d["ZGROUPNAME"],
            "domain_identifier":  d["ZDOMAINIDENTIFIER"],
            "account":            d["ZACCOUNT"],
            "is_response":        bool(d["ZISRESPONSE"]),
            "uuid":               d["ZUUID"],
            # Filled in by correlate_app_sessions() (reused — see load comment in main())
            "start": ts, "end": end_ts,
            "lat": None, "lng": None, "location_method": None,
            "location_accuracy": None, "place_id": None,
        })

    conn.close()
    return interactions



"""Load and classify SMS/iMessage conversations from sms.db, with sender
name resolution against AddressBook.sqlitedb when supplied."""

import sqlite3
from collections import defaultdict

from ..db import _open_sqlite_or_die
from ..utils import normalize_phone, unix_ts_ns
from ..classification import categorize_bundle_id

_TAPBACK_TYPES = {
    2000: "Loved", 2001: "Liked", 2002: "Disliked",
    2003: "Laughed at", 2004: "Emphasized", 2005: "Questioned",
    3000: "Removed a heart from", 3001: "Removed a like from",
    3002: "Removed a dislike from", 3003: "Removed a laugh from",
    3004: "Removed an emphasis from", 3005: "Removed a question mark from",
}

def classify_message(balloon_bundle_id, service):
    """
    Classify an sms.db message using the same bundle-ID category taxonomy as
    classify_app_session()/classify_asset_source() — so a rich-content
    message (a Spotify link preview, an Apple Pay request, a Game Pigeon
    turn) gets the same "Social Media" / "Messaging App" badge it would as
    an app-usage session or a photo's import source. Plain-text SMS/iMessage
    messages have no bundle ID at all, so those fall back to a channel-based
    category instead.

    Returns (category, subcategory, confidence).
    """
    if balloon_bundle_id:
        return categorize_bundle_id(balloon_bundle_id, None)
    if service == "iMessage":
        return "iMessage", "Text", "high"
    if service in ("SMS", "RCS"):
        return service, "Text", "high"
    return "Unknown", service or "Unknown", "low"


def load_sms(path, address_book=None):
    """
    Loads messages from an iOS sms.db (Messages app).

    Schema notes (sms.db's iOS 11+ layout, the only one this loader
    targets):
      - message.date/date_read/date_delivered are CoreData timestamps in
        NANOSECONDS since the Apple epoch — NOT the whole-seconds format
        used by Photos.sqlite/Cache.sqlite/knowledgeC.db. See unix_ts_ns().
      - handle.id holds the raw sender/recipient phone number or email.
        If address_book (from load_addressbook()) is supplied, it's used
        to resolve that raw value to a display name — but the raw handle
        is always kept too (message["handle"]), so nothing is hidden by
        the resolution and a reviewer can always see exactly what was
        actually recorded in sms.db versus what AddressBook.sqlitedb
        asserts about it.
      - A message with text IS NULL can still be meaningful: it may be an
        attachment-only message (cache_has_attachments=1), a tapback/
        reaction (associated_message_type in _TAPBACK_TYPES, referencing an
        earlier message via associated_message_guid), or a system/group-
        action event (item_type=4, e.g. someone added/removed/renamed the
        conversation). Each gets a synthesized display_text rather than
        showing up as a blank row.
      - Group vs. 1:1 is determined by participant count in
        chat_handle_join, not chat.style alone (some single-participant
        chats also carry style=45).

    Returns a list of message dicts. Returns an empty list (not an error) if
    the file opens but has no message rows — an empty Messages db is a real,
    reportable finding, not a load failure.
    """
    address_book = address_book or {}
    conn, cur = _open_sqlite_or_die(path)

    try:
        cur.execute("SELECT 1 FROM message LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        raise RuntimeError(
            f"{path} doesn't look like an iOS sms.db — no 'message' table found. "
            f"Confirm this is the Messages database, not e.g. a backup manifest."
        )

    # Sender/recipient handle per message (raw number/email — no AddressBook join)
    handles = {}
    for row in cur.execute("SELECT ROWID, id FROM handle"):
        handles[row["ROWID"]] = row["id"]

    # Chat membership: participant count + display/identifier name per chat,
    # keyed by message ROWID via chat_message_join.
    chat_participants = defaultdict(set)
    for row in cur.execute("SELECT chat_id, handle_id FROM chat_handle_join"):
        chat_participants[row["chat_id"]].add(row["handle_id"])

    chat_info = {}
    for row in cur.execute("SELECT ROWID, display_name, chat_identifier FROM chat"):
        chat_info[row["ROWID"]] = {
            "display_name":     row["display_name"] or None,
            "chat_identifier":  row["chat_identifier"],
            "n_participants":   len(chat_participants.get(row["ROWID"], ())),
        }

    msg_to_chat = {}
    for row in cur.execute("SELECT message_id, chat_id FROM chat_message_join"):
        msg_to_chat[row["message_id"]] = row["chat_id"]

    # Attachment filenames per message (for the attachment-only/no-text case)
    msg_attachments = defaultdict(list)
    cur.execute("""
        SELECT maj.message_id, a.transfer_name, a.mime_type
        FROM message_attachment_join maj
        JOIN attachment a ON a.ROWID = maj.attachment_id
    """)
    for row in cur.fetchall():
        msg_attachments[row["message_id"]].append({
            "filename":  row["transfer_name"],
            "mime_type": row["mime_type"],
        })

    cur.execute("""
        SELECT ROWID, guid, text, handle_id, is_from_me, service, date,
               date_read, is_read, item_type, group_action_type,
               group_title, associated_message_guid, associated_message_type,
               balloon_bundle_id, cache_has_attachments, is_audio_message
        FROM message
        ORDER BY date
    """)

    messages = []
    for r in cur.fetchall():
        d = dict(r)
        ts = unix_ts_ns(d["date"])
        if ts is None:
            continue   # malformed/zero timestamp — skip rather than mis-sort it to epoch

        chat_id   = msg_to_chat.get(d["ROWID"])
        cinfo     = chat_info.get(chat_id, {})
        is_group  = cinfo.get("n_participants", 0) > 1
        chat_name = cinfo.get("display_name") or cinfo.get("chat_identifier") or None

        attachments = msg_attachments.get(d["ROWID"], [])
        tapback_type = _TAPBACK_TYPES.get(d["associated_message_type"])
        is_system    = d["item_type"] == 4

        text = d["text"]
        if text:
            display_text = text
        elif tapback_type:
            display_text = f"[{tapback_type} a message]"
        elif is_system:
            display_text = f"[System: group action #{d['group_action_type']}]" if d["group_action_type"] is not None else "[System message]"
        elif attachments:
            names = ", ".join(a["filename"] or "attachment" for a in attachments[:3])
            display_text = f"[Attachment: {names}]"
        else:
            display_text = "[No text content]"

        category, subcategory, confidence = classify_message(d["balloon_bundle_id"], d["service"])

        handle_id = d["handle_id"]
        handle_raw = handles.get(handle_id) if handle_id else None
        if d["is_from_me"]:
            sender, sender_source = "Me", "device"
        elif handle_raw:
            resolved = address_book.get(normalize_phone(handle_raw)) or address_book.get(handle_raw.strip().lower())
            sender, sender_source = (resolved, "addressbook") if resolved else (handle_raw, "raw")
        else:
            sender, sender_source = f"Unknown ({handle_id})" if handle_id else "Unknown", "raw"

        messages.append({
            "id":                 d["ROWID"],
            "guid":               d["guid"],
            "ts":                 ts,
            "text":               text,
            "display_text":       display_text,
            "sender":             sender,
            "sender_raw":         handle_raw,
            "sender_source":      sender_source,
            "is_from_me":         bool(d["is_from_me"]),
            "service":            d["service"],
            "chat_id":            chat_id,
            "chat_name":          chat_name,
            "is_group":           is_group,
            "n_participants":     cinfo.get("n_participants", 0),
            "has_attachment":     bool(attachments) or bool(d["cache_has_attachments"]),
            "attachment_count":   len(attachments),
            "attachment_names":   [a["filename"] for a in attachments if a["filename"]],
            "is_audio":           bool(d["is_audio_message"]),
            "is_tapback":         tapback_type is not None,
            "tapback_type":       tapback_type,
            "associated_guid":    d["associated_message_guid"],
            "is_system":          is_system,
            "balloon_bundle_id":  d["balloon_bundle_id"],
            "category":           category,
            "subcategory":        subcategory,
            "confidence":         confidence,
            "is_read":            bool(d["is_read"]),
            "date_read":          unix_ts_ns(d["date_read"]),
            # Filled in by correlate_app_sessions() (reused — see load comment in main())
            "start": ts, "end": ts,
            "lat": None, "lng": None, "location_method": None,
            "location_accuracy": None, "place_id": None,
        })

    conn.close()
    return messages


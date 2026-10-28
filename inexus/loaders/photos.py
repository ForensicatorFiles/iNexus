"""Load and classify photo/video assets from Photos.sqlite."""
import math
import os
import glob
import base64

from ..db import _open_sqlite_or_die
from ..utils import apple_ts, unix_ts
from ..classification import categorize_bundle_id

def classify_asset_source(asset):
    """
    Determine how an asset arrived on the device.

    Returns a dict with:
      category    – high-level origin (Camera Captured, Screenshot, Messaging App, …)
      subcategory – detail label (Signal, AirDrop, iMessage / SMS, …)
      bundle_id   – raw bundle identifier, if any
      display_name– app display name, if any
      imported_by – raw ZIMPORTEDBY integer
      confidence  – 'high' | 'medium' | 'low'
    """
    importedby     = asset.get('importedby')     or 0
    bundle         = asset.get('imported_bundle') or ''
    display        = asset.get('imported_by')     or ''
    kindsubtype    = asset.get('kind_subtype')    or 0
    bundlescope    = asset.get('bundle_scope')    or 0
    savedassettype = asset.get('saved_asset_type')or 0
    is_mine        = asset.get('is_mine')
    dup_id         = asset.get('source_dup_id')

    category    = 'Unknown'
    subcategory = ''
    confidence  = 'high'

    # HDR Photos (ZKINDSUBTYPE = 2)
    if kindsubtype == 2:
        category    = 'Camera Captured'
        subcategory = 'HDR Photo'

    # Live Photos (ZKINDSUBTYPE = 10)
    elif kindsubtype == 10:
        if importedby == 8 and bundle == 'com.apple.springboard':
            category    = 'Screenshot'
            subcategory = 'Live Screenshot'
        else:
            category    = 'Camera Captured'
            subcategory = 'Live Photo'

    # Shared/syndicated albums
    elif bundlescope == 2 or savedassettype == 4:
        category    = 'Shared Album'
        subcategory = 'iCloud Shared' if is_mine else 'Received Share'

    # Third-party app import
    elif importedby == 3:
        category, subcategory, cat_confidence = categorize_bundle_id(bundle, display)
        if category == 'Unknown App':
            category    = 'Third-Party App'
            subcategory = 'Unknown App'
            confidence  = 'medium'
        else:
            confidence = cat_confidence

    # System-level saves (importedby=8)
    elif importedby == 8:
        if bundle == 'com.apple.springboard':
            category    = 'Screenshot'
            subcategory = 'SpringBoard'
        elif bundle == 'com.apple.MobileSMS':
            category    = 'Messaging App'
            subcategory = 'iMessage / SMS'
        elif bundle == 'com.apple.sharingd':
            category    = 'Received File'
            subcategory = 'AirDrop'
        elif bundle == 'com.apple.mobilemail':
            category    = 'Email Attachment'
            subcategory = 'Apple Mail'
        else:
            category    = 'System Save'
            subcategory = display or bundle or 'iOS System'

    elif importedby == 1:
        category    = 'Camera Captured'
        subcategory = 'Device Camera'

    elif importedby == 2:
        category    = 'Device Library'
        subcategory = 'Local Save / Sync'

    elif importedby == 5:
        category    = 'iCloud'
        subcategory = 'Cloud Download'

    elif importedby == 6:
        category    = 'Cable Transfer'
        subcategory = 'iTunes / Finder Sync'

    elif importedby == 9:
        category    = 'Camera Captured'
        subcategory = 'FaceTime Capture'

    if dup_id:
        subcategory = (subcategory + ' (Duplicate)').strip()

    return {
        'category':     category,
        'subcategory':  subcategory,
        'bundle_id':    bundle or None,
        'display_name': display or None,
        'imported_by':  importedby,
        'confidence':   confidence,
    }


def load_photos(path, thumbnails_dir=None):
    conn, cur = _open_sqlite_or_die(path)

    # Check available columns
    cur.execute("PRAGMA table_info(ZASSET)")
    cols = {r["name"] for r in cur.fetchall()}

    moment_join = ""
    moment_cols = "NULL as mlat, NULL as mlng"
    if "ZMOMENT" in cols:
        try:
            cur.execute("SELECT ZAPPROXIMATELATITUDE FROM ZMOMENT LIMIT 1")
            moment_join = "LEFT JOIN ZMOMENT zm ON a.ZMOMENT=zm.Z_PK"
            moment_cols = "zm.ZAPPROXIMATELATITUDE as mlat, zm.ZAPPROXIMATELONGITUDE as mlng"
        except Exception:
            pass

    exif_join = ""
    exif_cols = "NULL as exifts"
    try:
        cur.execute("SELECT ZDATETIMEORIGINAL FROM ZEXTENDEDATTRIBUTES LIMIT 1")
        exif_join = "LEFT JOIN ZEXTENDEDATTRIBUTES xe ON a.ZADDITIONALATTRIBUTES=xe.Z_PK"
        exif_cols = "xe.ZDATETIMEORIGINAL as exifts"
    except Exception:
        pass

    # Probe for source classification columns — all conditional to handle
    # schema differences across iOS versions.
    # IMPORTANT: the probe must query the REAL table name (e.g.
    # ZADDITIONALASSETATTRIBUTES), not the short alias used later in the
    # JOIN (aa) — a bare alias has no meaning outside that one query and
    # SELECT ... FROM aa always raises "no such table: aa", which silently
    # fell back to NULL for every classification column.
    _real_table = {"a": "ZASSET", "aa": "ZADDITIONALASSETATTRIBUTES"}

    def _col(tbl, col, alias):
        try:
            cur.execute(f"SELECT {col} FROM {_real_table.get(tbl, tbl)} LIMIT 1")
            return f"{tbl}.{col} as {alias}"
        except Exception:
            return f"NULL as {alias}"

    src_cols = ", ".join([
        _col("a",  "ZKINDSUBTYPE",                      "kindsubtype"),
        _col("a",  "ZBUNDLESCOPE",                      "bundlescope"),
        _col("a",  "ZSAVEDASSETTYPE",                   "savedassettype"),
        _col("a",  "ZPLAYBACKSTYLE",                    "playbackstyle"),
        _col("a",  "ZCLOUDISMYASSET",                   "is_mine"),
        _col("a",  "ZIMPORTSESSION",                    "impsession"),
        _col("aa", "ZIMPORTEDBY",                       "importedby"),
        _col("aa", "ZIMPORTEDBYBUNDLEIDENTIFIER",       "imported_bundle"),
        _col("aa", "ZIMPORTEDBYDISPLAYNAME",            "imported_by"),
        _col("aa", "ZDATECREATEDSOURCE",                "date_created_source"),
        _col("aa", "ZSOURCEASSETFORDUPLICATIONIDENTIFIER","source_dup_id"),
    ])

    cur.execute(f"""
        SELECT
            a.Z_PK          as id,
            a.ZFILENAME     as fn,
            a.ZDIRECTORY    as dir,
            a.ZDATECREATED  as dc,
            a.ZADDEDDATE    as da,
            a.ZLATITUDE     as lat,
            a.ZLONGITUDE    as lng,
            a.ZKIND         as kind,
            a.ZUNIFORMTYPEIDENTIFIER as uti,
            a.ZTRASHEDSTATE as trashed,
            a.ZWIDTH        as w,
            a.ZHEIGHT       as h,
            a.ZDURATION     as dur,
            {moment_cols},
            {exif_cols},
            {src_cols}
        FROM ZASSET a
        LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
        {moment_join}
        {exif_join}
        ORDER BY a.ZDATECREATED
    """)

    photos = []
    for r in cur.fetchall():
        d = dict(r)
        lat = d.get("lat")
        lng = d.get("lng")
        has_gps = lat is not None and lat not in (0, -180) and not math.isnan(lat)
        if not has_gps:
            mlat = d.get("mlat")
            if mlat is not None and mlat not in (0, -180, None):
                lat, lng, has_gps = mlat, d.get("mlng"), True

        dt = apple_ts(d["dc"])

        # Build a lightweight asset dict for the classifier (mirrors ZASSET field names)
        asset_for_classification = {
            "importedby":      d.get("importedby"),
            "imported_bundle": d.get("imported_bundle") or "",
            "imported_by":     d.get("imported_by") or "",
            "kind_subtype":    d.get("kindsubtype") or 0,
            "bundle_scope":    d.get("bundlescope") or 0,
            "saved_asset_type":d.get("savedassettype") or 0,
            "is_mine":         d.get("is_mine"),
            "source_dup_id":   d.get("source_dup_id"),
        }
        source_info = classify_asset_source(asset_for_classification)

        photos.append({
            "id":                  d["id"],
            "filename":            d["fn"] or d.get("dir", ""),
            "directory":           d.get("dir",""),
            "ts":                  dt,
            "unix_ts":             unix_ts(d["dc"]),
            "lat":                 lat,
            "lng":                 lng,
            "has_gps":             has_gps,
            "kind":                d.get("kind", 0),
            "uti":                 d.get("uti", ""),
            "trashed":             bool(d.get("trashed", 0)),
            "w":                   d.get("w"),
            "h":                   d.get("h"),
            "duration":            d.get("dur", 0) or 0,
            # Raw source fields
            "importedby":          d.get("importedby"),
            "imported_bundle":     d.get("imported_bundle"),
            "imported_by":         d.get("imported_by"),
            "kind_subtype":        d.get("kindsubtype") or 0,
            "bundle_scope":        d.get("bundlescope") or 0,
            "saved_asset_type":    d.get("savedassettype") or 0,
            "date_created_source": d.get("date_created_source"),
            # Classified origin
            "source_category":     source_info["category"],
            "source_subcategory":  source_info["subcategory"],
            "source_bundle_id":    source_info["bundle_id"],
            "source_display_name": source_info["display_name"],
            "source_confidence":   source_info["confidence"],
        })

    # 1. Map existing SQLite photos by their true stem to allow merging
    existing_by_stem = {}
    for p in photos:
        if p.get("filename"):
            base = os.path.basename(p["filename"])
            stem = os.path.splitext(base)[0].lower()
            if stem not in existing_by_stem:
                existing_by_stem[stem] = []
            existing_by_stem[stem].append(p)

    if thumbnails_dir and os.path.isdir(thumbnails_dir):
        import glob, base64
        search_pattern = os.path.join(thumbnails_dir, "**", "*.jpg")
        for thumb_path in glob.iglob(search_pattern, recursive=True):
            parts = os.path.normpath(thumb_path).split(os.sep)
            if len(parts) >= 3:
                parent_folder = parts[-2]
                
                if parent_folder.upper().endswith("APPLE"):
                    continue

                # Strip any extensions off the parent folder (e.g. IMG_6631.HEIC -> img_6631)
                stem_guess = os.path.splitext(parent_folder)[0].lower()
                
                thumb_data_uri = None
                try:
                    with open(thumb_path, "rb") as tf:
                        encoded = base64.b64encode(tf.read()).decode("utf-8")
                        thumb_data_uri = f"data:image/jpeg;base64,{encoded}"
                except Exception:
                    continue

                if stem_guess in existing_by_stem:
                    # MERGE: The photo exists in SQLite (has GPS!). Attach the V2 thumbnail as a fallback.
                    for existing_photo in existing_by_stem[stem_guess]:
                        if not existing_photo.get("thumbnail_data_uri"):
                            existing_photo["thumbnail_data_uri"] = thumb_data_uri
                else:
                    # ORPHAN: Truly missing from SQLite. Add as a standalone thumbnail.
                    stat = os.stat(thumb_path)
                    mtime = stat.st_mtime
                    photos.append({
                        "id":           900000 + len(photos),
                        "filename":     parent_folder + ".jpg",
                        "directory":    "__v2_thumbs__",
                        "ts":           apple_ts(mtime - 978307200),
                        "unix_ts":      mtime,
                        "lat":          None,
                        "lng":          None,
                        "has_gps":      False,
                        "kind":         0,
                        "uti":          "public.jpeg",
                        "trashed":      False,
                        "w":            None,
                        "h":            None,
                        "duration":     0,
                        "importedby":   0,
                        "source_category": "Thumbnail Cache",
                        "source_subcategory": "Unindexed (V2)",
                        "source_bundle_id": None,
                        "source_display_name": "PhotoData Thumbnails",
                        "source_confidence": "high",
                        "location_method": "unknown",
                        "thumbnail_data_uri": thumb_data_uri,
                        "is_thumbnail_orphan": True,
                    })

    photos.sort(key=lambda x: (x.get("filename") or "").lower())
    conn.close()
    return photos



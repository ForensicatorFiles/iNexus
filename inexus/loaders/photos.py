"""Load and classify photo/video assets from Photos.sqlite."""
import math
import os
import glob
import base64

from ..db import _open_sqlite_or_die
from ..utils import apple_ts, unix_ts
from ..classification import categorize_bundle_id

def classify_asset_source(asset):
    kindsubtype = asset.get('kind_subtype')
    bundlescope = asset.get('bundle_scope')
    savedassettype = asset.get('saved_asset_type')
    importedby = asset.get('importedby')
    bundle = asset.get('imported_bundle')
    bundle_display = asset.get('imported_by')
    original_filename = asset.get('original_filename')
    is_mine = asset.get('is_mine')
    original_filename = asset.get('original_filename')

    category    = 'Unknown'
    subcategory = ''
    confidence  = 'high'

    # 1. HIGHEST PRIORITY: Explicit Import Mechanisms
    if importedby == 1:
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

    # 2. APP IMPORTS & AIRDROP (Flags 8, 13)
    elif importedby in (8, 13):
        if bundle == 'com.apple.springboard':
            category    = 'Screenshot'
            subcategory = 'Hardware Capture'
        elif bundle == 'com.apple.sharingd':
            category    = 'AirDrop'
            # Inject the original filename if it exists
            if original_filename:
                subcategory = f'Received (sharingd) [{original_filename}]'
            else:
                subcategory = 'Received (sharingd)'
        elif bundle == 'com.apple.mobilesms':
            category    = 'Messages'
            subcategory = 'Saved from iMessage/SMS'
        else:
            category    = 'Third-Party App'
            subcategory = bundle_display or bundle or f'App Import (Flag {importedby})'

    # 3. SHARED ALBUMS & SYNDICATION
    elif bundlescope == 2 or savedassettype == 4:
        category    = 'Shared Album'
        subcategory = 'iCloud Shared' if is_mine else 'Received Share'

    # 4. NATIVE CAMERA METADATA (Fallback for Native Captures)
    elif kindsubtype == 2:
        category    = 'Camera Captured'
        subcategory = 'HDR Photo'

    elif kindsubtype == 10:
        category    = 'Camera Captured'
        subcategory = 'Live Photo'

    # 5. DEFAULT: Standard Native Camera
    elif not importedby and not bundle:
        category    = 'Camera Captured'
        subcategory = 'Standard Photo'

    # Fallback for anything completely unrecognized
    else:
        if bundle:
            category = 'Other App'
            subcategory = bundle_display or bundle
        else:
            confidence = 'low'
            
    return {
        "category": category,
        "subcategory": subcategory,
        "bundle_id": bundle,
        "display_name": bundle_display,
        "confidence": confidence
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
        # _col("aa", "ZORIGINALFILENAME",                 "original_filename"),
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
            aa.ZORIGINALFILENAME AS original_filename,
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
            "original_filename": d.get("original_filename"),
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
            "original_filename":   d.get("original_filename"),
            # Classified origin
            "source_category":     source_info["category"],
            "source_subcategory":  source_info["subcategory"],
            "source_bundle_id":    source_info["bundle_id"],
            "source_display_name": source_info["display_name"],
            "source_confidence":   source_info["confidence"],
        })

    # 1. Map existing SQLite photos by multiple keys for bulletproof matching
    existing_by_stem = {}       # e.g., 'img_1504'
    existing_by_fn = {}         # e.g., 'img_1504.heic'
    existing_by_dir_fn = {}     # e.g., '151apple/img_1504.heic'

    for p in photos:
        if p.get("filename"):
            fn = p["filename"].lower()
            stem = os.path.splitext(fn)[0]
            directory = (p.get("directory") or "").strip().lower()
            
            existing_by_stem.setdefault(stem, []).append(p)
            existing_by_fn.setdefault(fn, []).append(p)
            if directory:
                existing_by_dir_fn.setdefault(f"{directory}/{fn}", []).append(p)
                existing_by_dir_fn.setdefault(f"{directory}/{stem}", []).append(p)

    if thumbnails_dir and os.path.isdir(thumbnails_dir):
        import glob, base64
        search_pattern = os.path.join(thumbnails_dir, "**", "*.jpg")
        for thumb_path in glob.iglob(search_pattern, recursive=True):
            parts = os.path.normpath(thumb_path).split(os.sep)
            if len(parts) < 2:
                continue
                
            # iOS 16+ V2 paths use the full filename as the parent folder
            parent_folder = parts[-2].lower() # e.g., "img_1504.heic" or "img_1504"
            apple_dir = parts[-3].lower() if len(parts) >= 3 else "" # e.g., "151apple"
            stem_guess = os.path.splitext(parent_folder)[0]
            
            matched_photos = []
            
            # Waterfall matching: highest precision to lowest precision
            if f"{apple_dir}/{parent_folder}" in existing_by_dir_fn:
                matched_photos = existing_by_dir_fn[f"{apple_dir}/{parent_folder}"]
            elif f"{apple_dir}/{stem_guess}" in existing_by_dir_fn:
                matched_photos = existing_by_dir_fn[f"{apple_dir}/{stem_guess}"]
            elif parent_folder in existing_by_fn:
                matched_photos = existing_by_fn[parent_folder]
            elif stem_guess in existing_by_stem:
                matched_photos = existing_by_stem[stem_guess]

            if matched_photos:
                # MERGE: Read the thumbnail and attach it to the EXACT matching SQLite record(s)
                thumb_data_uri = None
                try:
                    with open(thumb_path, "rb") as tf:
                        encoded = base64.b64encode(tf.read()).decode("utf-8")
                        thumb_data_uri = f"data:image/jpeg;base64,{encoded}"
                except Exception:
                    continue
                    
                if thumb_data_uri:
                    for existing_photo in matched_photos:
                        if not existing_photo.get("thumbnail_data_uri"):
                            existing_photo["thumbnail_data_uri"] = thumb_data_uri
            else:
                # ORPHAN: Truly missing from SQLite, add as standalone V2 artifact
                stat = os.stat(thumb_path)
                mtime = stat.st_mtime
                
                try:
                    with open(thumb_path, "rb") as tf:
                        encoded = base64.b64encode(tf.read()).decode("utf-8")
                        thumb_data_uri = f"data:image/jpeg;base64,{encoded}"
                except Exception:
                    thumb_data_uri = None
                
                photos.append({
                    "id":           900000 + len(photos),
                    "filename":     parent_folder + ('.jpg' if not parent_folder.endswith('.jpg') else ''),
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



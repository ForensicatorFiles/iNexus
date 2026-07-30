"""HEIC→JPEG batch conversion for the -convert-heic CLI flag, and the
logic for detecting/reusing an already-converted JPEG tree beside a
report on a subsequent run."""
import os

from .utils import _unique_dir

def convert_dcim_heic(out_dir, dcim_path, quality=85, target_dir=None):
    """
    Walk `dcim_path` for HEIC/HEIF files and write JPEG copies into a sibling
    tree, preserving sub-folder layout. The original DCIM tree is never modified.

    target_dir : if None (default), a fresh, collision-safe folder ("<DCIM>_jpg",
                 then _1, _2, …) is created. If given (name relative to out_dir, or
                 an absolute path), that folder is reused: files already present are
                 mapped and counted as 'skipped' (NOT re-encoded), and only missing
                 files are converted. This is how a previous run's output is topped
                 up with newly-added photos instead of being rebuilt from scratch.

    Returns (convbase_name, heic_map, stats) where:
      convbase_name : the output-folder name, RELATIVE to out_dir, so the report can
                      build report-relative <img> URLs to the JPEGs.
      heic_map      : { "<subpath-under-dcim>.heic" (lowercased) :
                        "<convbase_name>/<subpath>.jpg" } for EVERY HEIC that has a
                        JPEG (freshly converted or already present), so the report
                        can map a photo's ZDIRECTORY/ZFILENAME to its JPEG.
      stats         : dict with counts (found / converted / failed / skipped).
    On any setup failure (missing dcim, missing pillow-heif) returns
    (None, {}, stats) with an explanatory 'error' in stats — the caller logs it
    and proceeds to build the report without previews rather than aborting.
    """
    stats = {"found": 0, "converted": 0, "failed": 0, "skipped": 0, "error": None}

    if not dcim_path or not os.path.isdir(dcim_path):
        stats["error"] = f"DCIM folder not found: {dcim_path}"
        return None, {}, stats

    try:
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        stats["error"] = ("pillow-heif is not installed — run "
                          "`pip install pillow-heif` to enable HEIC conversion.")
        return None, {}, stats

    # Output tree lives beside the report (out_dir), named after the DCIM folder.
    if target_dir:
        convbase_abs = target_dir if os.path.isabs(target_dir) \
                       else os.path.join(out_dir, target_dir)
        os.makedirs(convbase_abs, exist_ok=True)
    else:
        dcim_name = os.path.basename(os.path.normpath(dcim_path)) or "DCIM"
        convbase_abs = _unique_dir(os.path.join(out_dir, dcim_name + "_jpg"))
    convbase_name = os.path.basename(convbase_abs)

    heic_exts = (".heic", ".heif")
    heic_map = {}

    for root, _dirs, files in os.walk(dcim_path):
        for fname in files:
            if not fname.lower().endswith(heic_exts):
                continue
            stats["found"] += 1
            src = os.path.join(root, fname)
            # path of this file relative to the DCIM root, e.g. "100APPLE/IMG.HEIC"
            sub = os.path.relpath(src, dcim_path)
            sub_jpg = os.path.splitext(sub)[0] + ".jpg"
            dst = os.path.join(convbase_abs, sub_jpg)
            key = sub.replace(os.sep, "/").lower()
            val = convbase_name + "/" + sub_jpg.replace(os.sep, "/")

            if os.path.exists(dst):           # already converted on a prior run → reuse
                heic_map[key] = val
                stats["skipped"] += 1
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with Image.open(src) as im:
                    im.convert("RGB").save(dst, "JPEG", quality=quality)
                heic_map[key] = val
                stats["converted"] += 1
            except Exception as exc:           # noqa: BLE001 — one bad file shouldn't stop the batch
                stats["failed"] += 1
                print(f"      ⚠ failed: {sub} ({exc})")

    return convbase_name, heic_map, stats


def find_existing_jpeg_tree(out_dir, dcim_path):
    """
    Look for a JPEG tree from a PREVIOUS -convert-heic run so we don't re-encode
    images that are already done. Searches `out_dir` for sibling folders named like
    the DCIM folder with a _jpg/_jpeg suffix (including iterator variants such as
    DCIM_jpg_1), and checks each against the actual HEIC files under `dcim_path`.

    Returns (convbase_name, heic_map, info):
      convbase_name : the matched folder (relative to out_dir), or None if no usable
                      existing tree was found.
      heic_map      : mapping for every HEIC that already has a JPEG in that folder.
      info          : { total_heic, matched, missing, candidate } — `missing` is how
                      many HEIC files have no JPEG yet (0 ⇒ complete, safe to fully
                      reuse; >0 ⇒ partial, convert the remainder into `candidate`).
    A candidate is only returned if it matches at least one HEIC (i.e. it actually
    mirrors the DCIM structure); a same-named folder that shares no files is ignored.
    """
    info = {"total_heic": 0, "matched": 0, "missing": 0, "candidate": None}

    if not dcim_path or not os.path.isdir(dcim_path) or not os.path.isdir(out_dir):
        return None, {}, info

    heic_exts = (".heic", ".heif")
    # Enumerate HEIC files under DCIM (authoritative — this is the structure to match)
    heic_subs = []
    for root, _dirs, files in os.walk(dcim_path):
        for fname in files:
            if fname.lower().endswith(heic_exts):
                heic_subs.append(os.path.relpath(os.path.join(root, fname), dcim_path))
    info["total_heic"] = len(heic_subs)
    if not heic_subs:
        return None, {}, info

    dcim_name = os.path.basename(os.path.normpath(dcim_path)) or "DCIM"

    # Build the candidate list: exact _jpg / _jpeg first, then iterator variants,
    # so a clean previous run is preferred over a stray partial one.
    suffixes = (dcim_name + "_jpg", dcim_name + "_jpeg")
    candidates = [s for s in suffixes if os.path.isdir(os.path.join(out_dir, s))]
    try:
        for entry in sorted(os.listdir(out_dir)):
            full = os.path.join(out_dir, entry)
            if not os.path.isdir(full) or entry in candidates:
                continue
            if any(entry.startswith(s + "_") for s in suffixes):  # DCIM_jpg_1, etc.
                candidates.append(entry)
    except OSError:
        pass

    # Pick the candidate that covers the most HEIC files.
    best_name, best_map, best_matched = None, {}, -1
    for cand in candidates:
        cand_abs = os.path.join(out_dir, cand)
        cmap, matched = {}, 0
        for sub in heic_subs:
            sub_jpg = os.path.splitext(sub)[0] + ".jpg"
            if os.path.exists(os.path.join(cand_abs, sub_jpg)):
                cmap[sub.replace(os.sep, "/").lower()] = cand + "/" + sub_jpg.replace(os.sep, "/")
                matched += 1
        if matched > best_matched:
            best_name, best_map, best_matched = cand, cmap, matched

    if not best_name or best_matched <= 0:
        return None, {}, info

    info["candidate"] = best_name
    info["matched"]   = best_matched
    info["missing"]   = info["total_heic"] - best_matched
    return best_name, best_map, info



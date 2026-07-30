"""
Safely picks up a database's -wal/-shm siblings, if present, without ever
writing to the original evidence files.

Why this needs care: SQLite in WAL mode can trigger a checkpoint (writing
WAL frames back into the main .sqlite file) simply from opening a normal
read-write connection — exactly the kind of silent modification that's
unacceptable against original evidence, chain-of-custody-wise. The fix
used here is to copy the database file plus any sibling -wal/-shm files
into a fresh temp directory (preserving their exact filenames, since
that's how SQLite associates a WAL with its database) and open the COPY.
Any checkpoint that happens only touches that throwaway copy; the
original three files are never opened for writing, ever.

If no sibling WAL/SHM files exist, this is a no-op — the original path is
returned unchanged and nothing is copied, so the common case (a bare
Cache.sqlite from an extraction tool that already checkpointed everything)
has zero overhead.
"""
import os
import shutil
import tempfile

# Extraction tools vary in how they name a WAL/SHM pair — cover the
# standard SQLite convention plus the underscore variant some tools use.
_WAL_SUFFIXES = ["-wal", "_wal", ".wal"]
_SHM_SUFFIXES = ["-shm", "_shm", ".shm"]


def _find_sibling(path, suffixes):
    for suf in suffixes:
        candidate = path + suf
        if os.path.isfile(candidate):
            return candidate
    return None


def find_wal_shm(path):
    """Returns (wal_path_or_None, shm_path_or_None) for the given db path."""
    return _find_sibling(path, _WAL_SUFFIXES), _find_sibling(path, _SHM_SUFFIXES)


class PreparedDb:
    """
    .path is what to actually open (via sqlite3.connect or the raw-bytes
    engine). .original_wal / .original_shm are the source sibling paths
    (for hashing/disclosure), or None if there weren't any. .cleanup()
    removes the temp directory, if one was created — call it when done.
    """
    __slots__ = ("path", "original_wal", "original_shm", "_tmpdir")

    def __init__(self, path, original_wal, original_shm, tmpdir):
        self.path = path
        self.original_wal = original_wal
        self.original_shm = original_shm
        self._tmpdir = tmpdir

    def cleanup(self):
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)


def prepare_readable_copy(path):
    """
    If `path` has sibling WAL/SHM files, copies all three into a fresh temp
    directory under their original filenames (so SQLite still finds the
    WAL by name) and returns a PreparedDb pointing at the copy. If there
    are no siblings, returns a PreparedDb pointing at the original path
    unchanged, with no temp directory created.

    Never opens or modifies the original files in any way — this only
    ever calls shutil.copy2() (read from original, write to a new temp
    location), never a write-mode file handle on `path` itself.
    """
    wal_path, shm_path = find_wal_shm(path)
    if wal_path is None and shm_path is None:
        return PreparedDb(path, None, None, None)

    tmpdir = tempfile.mkdtemp(prefix="ilc_wal_")
    db_name = os.path.basename(path)
    copy_path = os.path.join(tmpdir, db_name)
    shutil.copy2(path, copy_path)
    if wal_path is not None:
        shutil.copy2(wal_path, copy_path + "-wal")
    if shm_path is not None:
        shutil.copy2(shm_path, copy_path + "-shm")

    prepared = PreparedDb(copy_path, wal_path, shm_path, tmpdir)
    _active.append(prepared)
    return prepared


# ── Run-scoped cleanup registry ────────────────────────────────────────────────
# Each PreparedDb that actually created a temp directory registers itself here;
# cli.py's main() calls cleanup_all() once at the end of the run (in a
# try/finally) so temp copies never linger on disk after the tool exits.
_active = []


def cleanup_all():
    for prepared in _active:
        prepared.cleanup()
    _active.clear()

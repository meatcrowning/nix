"""Atomic tag writeback: never rewrite a library file in place.

Both write paths in this app (TagWriter's FMPS rating/favourite/playcount and
lyrics.write_embedded's USLT/LYRICS/©lyr) used to end in a bare
`mutagen.save()`, which rewrites the file where it lies. For a container whose
tag block has run out of padding — an MP3 gaining a TXXX frame, a FLAC gaining
6 KB of LRC — that means shifting the audio data itself. A crash, an OOM kill
or a yanked USB cable in the middle of that leaves a truncated or interleaved
file, and this library lives on exFAT with no snapshots and no rollback: the
damaged file is simply gone.

So every write goes: copy -> mutate the COPY -> fsync -> os.replace().
`os.replace()` is a rename, and rename-over-existing is atomic on exFAT the
same way it is on ext4 (verified on this SSD, see tools/atomic-write-test.py):
a reader sees either the whole old file or the whole new one, never a mixture,
and an interruption at any point leaves the ORIGINAL untouched.

What that costs, and why it is affordable now: a temp copy needs room for the
whole file. The docstring this replaces chose in-place writes to dodge that on
a "95%-full SSD" — but /run/media/lam/SSD is 932G with 662G free (2026-07-28),
so the largest file in the library is noise. The check is still made per write,
against the target's OWN filesystem, and a write that would not fit fails
cleanly and journaled rather than filling the disk.

Rules this module encodes, each of which has a way to go wrong:

* **The temp file is in the TARGET'S OWN DIRECTORY.** Anywhere else and
  `os.replace()` is a cross-device copy at best and `EXDEV` at worst — /tmp is
  a different filesystem and would silently turn atomicity into a long copy.
* **The temp name keeps the original extension.** `mutagen.File()` scores
  formats partly by filename, so a `.tmp` copy of a `.dsf` can be sniffed as
  something else or not at all.
* **The temp name is exFAT-legal**: `.player-tag-XXXXXXXX.ext`, from
  `tempfile.mkstemp`, whose random component is `[A-Za-z0-9_]`. None of
  exFAT's reserved characters (`" * / : < > ? \\ |`) can appear, and the name
  is ~22 chars against a 255-char limit, so an album folder named
  `666 (The Apocalypse Of John.13-18)` is irrelevant — only the basename is
  ours.
* **mtime is PRESERVED** (`os.utime` from the original's stat). The scan keys
  its cache on (mtime, size) and dbsync ships the DB to book on the strength of
  mtime passing through SMB byte-exact; both write paths already update the DB
  row in-process, so there is nothing a rescan needs to rediscover. Size still
  changes, so a scan that genuinely must re-read one still does.
* **A crash leaves no litter.** The temp file is unlinked on every failure
  path, and `sweep_orphans()` clears anything older than an hour from the one
  directory we are about to write to (bounded: one listing of one album
  folder, not a walk of 543 of them).
"""
import errno
import os
import shutil
import tempfile
import time

import mutagen

# Room the copy needs beyond the file itself: tag growth plus slack.
GROWTH_SLACK = 8 * 1024 * 1024
# Never take the target filesystem below this, whatever the file's size.
FREE_FLOOR = 512 * 1024 * 1024
TMP_PREFIX = ".player-tag-"
ORPHAN_AGE = 3600


class NoSpace(OSError):
    """Not enough room on the target filesystem for a safe copy-then-replace."""


def sweep_orphans(dirname, max_age=ORPHAN_AGE):
    """Delete stale temp files this module left in `dirname`. Best effort."""
    now = time.time()
    try:
        names = os.listdir(dirname)
    except OSError:
        return
    for name in names:
        if not name.startswith(TMP_PREFIX):
            continue
        p = os.path.join(dirname, name)
        try:
            if now - os.stat(p).st_mtime > max_age:
                os.unlink(p)
        except OSError:
            pass


def _fsync_dir(dirname):
    """Durability for the rename itself. exFAT's fuse/kernel driver may refuse
    an fd on a directory or an fsync of one; that is not an error we can act
    on, and the rename is already atomic without it."""
    try:
        fd = os.open(dirname, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_save(path, mutate, preserve_mtime=True):
    """Apply `mutate(audio)` to `path`'s tags without ever writing `path`
    itself. `mutate` is handed the mutagen object for a private COPY and must
    not call save(); this does. Raises on any failure, and on every failure the
    original file is exactly as it was.
    """
    path = os.fspath(path)
    dirname = os.path.dirname(path) or "."
    st = os.stat(path)                      # ENOENT here = caller's problem
    if not os.path.isfile(path):
        raise IsADirectoryError(path)

    need = st.st_size + GROWTH_SLACK
    free = shutil.disk_usage(dirname).free
    if free < need or free - need < FREE_FLOOR:
        raise NoSpace(errno.ENOSPC,
                      "need %d bytes free (+%d floor), have %d"
                      % (need, FREE_FLOOR, free), path)

    sweep_orphans(dirname)

    ext = os.path.splitext(path)[1]         # mutagen sniffs on it; keep it
    fd, tmp = tempfile.mkstemp(dir=dirname, prefix=TMP_PREFIX, suffix=ext)
    os.close(fd)
    try:
        shutil.copyfile(path, tmp)          # data only; perms are meaningless
        try:                                # on exFAT and copystat may EPERM
            shutil.copystat(path, tmp)
        except OSError:
            pass

        audio = mutagen.File(tmp)
        if audio is None:
            raise RuntimeError("mutagen could not open")
        mutate(audio)
        audio.save()

        if preserve_mtime:
            try:
                os.utime(tmp, (st.st_atime, st.st_mtime))
            except OSError:
                pass

        with open(tmp, "rb") as f:          # the copy must be ON the disk
            os.fsync(f.fileno())            # before the rename publishes it

        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    _fsync_dir(dirname)

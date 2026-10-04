"""Atomic file writes.

Write to a temp file in the SAME directory, flush + fsync, then os.replace()
it onto the target. os.replace is atomic on a single filesystem (POSIX and
Windows), so a reader — the server serving /data, an EA reading a gate file —
or a crash/restart mid-write never sees a half-written file: it sees either the
whole old file or the whole new one. This guards the flat signal JSON
(opportunities_*.json) and the Markov gate files against corruption on a sudden
restart, power blip, or micro-drop.
"""
import os
import json
import tempfile


def write_text(path, text, encoding="utf-8"):
    path = os.fspath(path)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())          # durably on disk before the swap
        os.replace(tmp, path)             # atomic swap onto the target
    except BaseException:
        try:
            os.unlink(tmp)                # never leave a stray temp on failure
        except OSError:
            pass
        raise
    # best-effort: persist the rename in the directory entry too (POSIX only)
    try:
        dfd = os.open(d, os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except (AttributeError, OSError):
        pass


def write_json(path, obj, indent=2):
    write_text(path, json.dumps(obj, indent=indent))

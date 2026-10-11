"""Snapshot a folder tree (path -> size, mtime) or compare two snapshots.

    python snapshot_tree.py take <root> <out.json> [--exclude <subdir> ...]
    python snapshot_tree.py diff <before.json> <after.json>
"""
import json
import os
import sys


def take(root, excludes):
    ex = [os.path.normcase(os.path.normpath(os.path.join(root, e))) for e in excludes]
    snap = {}
    for b, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if os.path.normcase(os.path.normpath(os.path.join(b, d))) not in ex]
        for f in fs:
            p = os.path.join(b, f)
            st = os.stat(p)
            snap[os.path.relpath(p, root)] = [st.st_size, st.st_mtime_ns]
    return snap


if __name__ == "__main__":
    if sys.argv[1] == "take":
        ex = sys.argv[sys.argv.index("--exclude") + 1:] if "--exclude" in sys.argv else []
        s = take(sys.argv[2], ex)
        json.dump(s, open(sys.argv[3], "w"))
        print(len(s), "files", sum(v[0] for v in s.values()) / 1e9, "GB")
    else:
        a, b = json.load(open(sys.argv[2])), json.load(open(sys.argv[3]))
        ch = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        print(json.dumps({"files_before": len(a), "files_after": len(b), "changed_added_removed": ch}, indent=1))

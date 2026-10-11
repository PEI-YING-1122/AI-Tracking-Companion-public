"""Regression baseline: capture / compare every result JSON of the regression suites.

    python tests/baseline_metrics.py capture <out_baseline.json> [--demo <work/shot dir>]
    python tests/baseline_metrics.py compare <baseline.json> <candidate.json>

All numeric and string leaves of test_runs/results/*.json (+ the baseline shot's
verify / manifest) are flattened to "file:path.to.leaf" -> value.  Volatile leaves
(timings, timestamps, versions, build ids, absolute work paths) are excluded.
Numbers must match to 1e-9 relative (the pipeline is deterministic); strings exactly.
"""
import glob
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOLATILE = re.compile(r"(seconds|elapsed|created|companion_version|build_id|nuke_log|stdout|stderr|msg|"
                      r"maya_msg|stmap_msg|_time|timestamp|work_dir|work_bytes|config$|manifest_error|"
                      r"\.relocation\.target|project_directory_eval|relocation\.drive|\.error$)", re.I)


def flatten(obj, prefix, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}.{k}", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flatten(v, f"{prefix}[{i}]", out)
    elif isinstance(obj, (int, float, str, bool)) or obj is None:
        if not VOLATILE.search(prefix):
            out[prefix] = obj


def capture(out_path, extra_dirs):
    data = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "test_runs", "results", "*.json"))):
        flatten(json.load(open(p)), os.path.basename(p), data)
    for d in extra_dirs:
        for p in sorted(glob.glob(os.path.join(d, "*_verify.json"))) + sorted(glob.glob(os.path.join(d, "*_companion_manifest.json"))):
            name = os.path.basename(p)
            j = json.load(open(p))
            if name.endswith("_companion_manifest.json"):  # sizes / file list only
                j = {"files": [{k: f[k] for k in ("key", "bytes")} for f in j.get("files", [])],
                     "export_bytes_added": j.get("export_bytes_added")}
            flatten(j, name, data)
    json.dump(data, open(out_path, "w"), indent=0, sort_keys=True)
    print(f"captured {len(data)} values -> {out_path}")


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def _volatile_sizes(d):
    """Manifest byte counts that legitimately change between identical builds:
    the FBX embeds a CreationTimeStamp (millisecond digits vary) and metadata embeds
    companion_version / build ids.  Their sum (export_bytes_added) follows.  Every
    other file size (STMaps, ABC, NPZ, loader, .nk) is still compared byte for byte."""
    vol = set()
    for k, v in d.items():
        m = re.match(r"^(.*_companion_manifest\.json)\.files\[(\d+)\]\.key$", k)
        if m and v in ("maya_cam_fbx", "metadata"):
            vol.add(f"{m.group(1)}.files[{m.group(2)}].bytes")
            vol.add(f"{m.group(1)}.export_bytes_added")
    return vol


def compare(a_path, b_path):
    a, b = json.load(open(a_path)), json.load(open(b_path))
    vol = _volatile_sizes(a) | _volatile_sizes(b)
    a = {k: v for k, v in a.items() if k not in vol}
    b = {k: v for k, v in b.items() if k not in vol}
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    diff = sorted(k for k in set(a) & set(b) if not same(a[k], b[k]))
    res = {"baseline_values": len(a), "candidate_values": len(b), "compared": len(set(a) & set(b)),
           "different": len(diff), "missing_in_candidate": len(only_a), "new_in_candidate": len(only_b),
           "identical": not diff and not only_a,
           "diff_samples": [{"key": k, "baseline": a[k], "candidate": b[k]} for k in diff[:40]],
           "missing_samples": only_a[:20], "new_samples": only_b[:20]}
    print(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    if sys.argv[1] == "capture":
        extras = sys.argv[sys.argv.index("--extra") + 1:] if "--extra" in sys.argv else []
        capture(sys.argv[2], extras)
    else:
        r = compare(sys.argv[2], sys.argv[3])
        if len(sys.argv) > 4:
            json.dump(r, open(sys.argv[4], "w"), indent=1, default=str)
        sys.exit(0 if r["identical"] else 1)

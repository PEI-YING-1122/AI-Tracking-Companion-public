"""Regression baseline: capture / compare every result JSON of the regression suites.

    python tests/baseline_metrics.py capture <out_baseline.json> [--extra <baseline shot work dir>]
    python tests/baseline_metrics.py compare <baseline.json> <candidate.json> [<result.json>] [--intended <changes.json>]

All numeric and string leaves of <test data>/results/*.json (+ the baseline shot's
verify / manifest) are flattened to "file:path.to.leaf" -> value.  Volatile leaves
(timings, timestamps, versions, build ids, absolute work paths) are excluded.
Numbers must match to 1e-9 relative (the pipeline is deterministic); strings exactly.
--intended: a reviewed list of key patterns that a release changed ON PURPOSE (each with its
reason).  Differences / missing keys on those keys are reported separately as "intended";
every other difference still fails the compare.
"""
import glob
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_paths as tp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import migrate_test_data  # noqa: E402
# result files ABOUT the regression (summaries, comparisons): not regression values themselves
META = re.compile(r"^(baseline_compare.*|run_all_summary.*|compare_.*|test_v021_fixes.*|test_v021_test2.*)\.json$")
VOLATILE = re.compile(r"(seconds|elapsed|created|companion_version|build_id|nuke_log|stdout|stderr|msg|"
                      r"maya_msg|stmap_msg|_time|timestamp|work_dir|work_bytes|work_mb|config$|manifest_error|"
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
    for p in sorted(glob.glob(os.path.join(tp.results(), "*.json"))):
        if META.match(os.path.basename(p)):
            continue
        flatten(json.load(open(p, encoding="utf-8")), os.path.basename(p), data)
    for d in extra_dirs:
        for p in sorted(glob.glob(os.path.join(d, "*_verify.json"))) + sorted(glob.glob(os.path.join(d, "*_companion_manifest.json"))):
            name = os.path.basename(p)
            j = json.load(open(p, encoding="utf-8"))
            if name.endswith("_companion_manifest.json"):  # sizes / file list only
                j = {"files": [{k: f[k] for k in ("key", "bytes")} for f in j.get("files", [])],
                     "export_bytes_added": j.get("export_bytes_added")}
            flatten(j, name, data)
    json.dump(data, open(out_path, "w", encoding="utf-8"), indent=0, sort_keys=True)
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


def _relocations():
    """test data moved out of the repository (GUI implementation STEP 01): old -> new prefixes,
    then the test data root itself becomes <TEST_DATA> so paths compare across machines."""
    root = tp.root().replace("\\", "/")
    pairs = sorted(((s.replace("\\", "/"), d.replace("\\", "/")) for s, d in migrate_test_data.plan(root, only_existing=False, repo=tp.capture_repo())),
                   key=lambda x: -len(x[0]))
    return pairs, root


def _relocate(v, rel):
    pairs, root = rel
    if re.match(r"^[A-Za-z]:[\\/]", v):
        v = v.replace("\\", "/")
    for s, d in pairs:
        if v.lower().startswith(s.lower()) and (len(v) == len(s) or v[len(s)] in "/\\"):
            v = d + v[len(s):]
            break
    if v.lower().startswith(root.lower()):
        v = "<TEST_DATA>" + v[len(root):]
    return v


def _alias(v, al):
    """real names of the production baseline shot -> the neutral names stored in tests/baselines"""
    for real, neutral in al:
        v = v.replace(real, neutral)
    return v


def _normalise(d):
    """Make two runs comparable without loosening content checks:
    * manifest files are matched by their key, not by list position (order changed in the
      transactional builder) -> '<manifest>.files.<key>.bytes'
    * validation reads files from the build stage / a remapped copy since the transactional
      builder: compare the FILE NAME of those path leaves (the folder is a build artefact)."""
    al = tp.aliases()
    d = {_alias(k, al): v for k, v in d.items()}
    out, idx_key = {}, {}
    rel = _relocations()
    for k, v in d.items():
        m = re.match(r"^(.*_companion_manifest\.json)\.files\[(\d+)\]\.key$", k)
        if m:
            idx_key[(m.group(1), m.group(2))] = v
    for k, v in d.items():
        m = re.match(r"^(.*_companion_manifest\.json)\.files\[(\d+)\]\.(\w+)$", k)
        if m and (m.group(1), m.group(2)) in idx_key:
            if m.group(3) == "key":
                continue
            k = f"{m.group(1)}.files.{idx_key[(m.group(1), m.group(2))]}.{m.group(3)}"
        if isinstance(v, str):
            v = _alias(_relocate(v, rel), al)
        if isinstance(v, str) and re.search(r"(\.reads\.[A-Z_]+\.file|loader_info\.metadata)$", k):
            v = os.path.basename(v.replace("\\", "/")).replace(".validate.", ".")
        out[k] = v
    return out


def compare(a_path, b_path, intended_path=None):
    a, b = json.load(open(a_path, encoding="utf-8")), json.load(open(b_path, encoding="utf-8"))
    is_meta = lambda k: bool(META.match(k.split(".json", 1)[0] + ".json"))  # noqa: E731
    a = {k: v for k, v in a.items() if not is_meta(k) and not VOLATILE.search(k)}
    b = {k: v for k, v in b.items() if not is_meta(k) and not VOLATILE.search(k)}
    va, vb = _volatile_sizes(a), _volatile_sizes(b)  # per side: list positions differ between runs
    a = _normalise({k: v for k, v in a.items() if k not in va})
    b = _normalise({k: v for k, v in b.items() if k not in vb})
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    diff = sorted(k for k in set(a) & set(b) if not same(a[k], b[k]))
    rules = json.load(open(intended_path, encoding="utf-8"))["changes"] if intended_path else []
    pats = [(re.compile(r["pattern"]), r["reason"]) for r in rules]

    def why(k):
        return next((r for p, r in pats if p.search(k)), None)
    intended = [{"key": k, "baseline": a[k], "candidate": b.get(k, "<missing>"), "reason": why(k)}
                for k in diff + only_a if why(k)]
    diff = [k for k in diff if not why(k)]
    only_a = [k for k in only_a if not why(k)]
    res = {"baseline_values": len(a), "candidate_values": len(b), "compared": len(set(a) & set(b)),
           "different": len(diff), "missing_in_candidate": len(only_a), "new_in_candidate": len(only_b),
           "intended_changes": len(intended), "identical_except_intended": not diff and not only_a,
           "identical": not diff and not only_a and not intended,
           "diff_samples": [{"key": k, "baseline": a[k], "candidate": b[k]} for k in diff[:40]],
           "missing_samples": only_a[:20], "new_samples": only_b[:20], "intended": intended}
    print(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    if sys.argv[1] == "capture":
        extras = sys.argv[sys.argv.index("--extra") + 1:] if "--extra" in sys.argv else []
        capture(sys.argv[2], extras)
    else:
        args = sys.argv[2:]
        intended = None
        if "--intended" in args:
            i = args.index("--intended")
            intended = args[i + 1]
            del args[i:i + 2]
        r = compare(args[0], args[1], intended)
        if len(args) > 2:
            json.dump(r, open(args[2], "w", encoding="utf-8"), indent=1, default=str)
        sys.exit(0 if r["identical_except_intended"] else 1)

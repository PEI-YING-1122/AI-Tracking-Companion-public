"""Production-workflow regression: path resolver guards + one companion_run per shot config.

    python tests/run_workflow.py [--configs cfg1.json cfg2.json ...]

Each config is run with --overwrite; a config may declare
"_expect": {"rc": 2} to assert a refusal (e.g. a failed AI Tracking solve).
The AI Tracking install is snapshotted before/after (must stay untouched).
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
import site_config  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_paths as tp  # noqa: E402

PY = sys.executable
DEFAULT_CONFIGS = [  # resolved at run time under the test data root
    ("workflow", "mock_project_A/pipeline/configs/WF_0010.shot.json"),
    ("workflow", "mock_project_B/configs/RB_0020.json"),
    ("workflow", "mock_project_C/io/configs/CC_0030.json"),
    ("baseline", "demo_sh0010/demo_sh0010.json"),
]


def snapshot(top):
    return {os.path.relpath(os.path.join(b, f), top): (os.stat(os.path.join(b, f)).st_size, os.stat(os.path.join(b, f)).st_mtime_ns)
            for b, _, fs in os.walk(top) for f in fs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+", default=[getattr(tp, k)(p) for k, p in DEFAULT_CONFIGS])
    a = ap.parse_args()
    upstream = os.path.dirname(site_config.get("upstream_repo"))
    logs = os.path.join(ROOT, "logs", "workflow")
    os.makedirs(logs, exist_ok=True)
    res_dir = tp.results()
    os.makedirs(res_dir, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    before = snapshot(upstream)
    out = {"runs": {}}

    r = subprocess.run([PY, "tests/test_path_resolver.py", a.configs[0], tp.workflow("work", "work_resolver"),
                        os.path.join(res_dir, "test_path_resolver.json")], cwd=ROOT, env=env, capture_output=True, text=True)
    out["path_resolver"] = {"rc": r.returncode, "all_ok": r.stdout.strip().endswith("ALL OK")}
    print(f"[{'OK' if out['path_resolver']['all_ok'] else 'FAIL'}] path resolver guards")

    for cfg in a.configs:
        expect = json.load(open(cfg)).get("_expect", {}).get("rc", 0)
        name = os.path.splitext(os.path.basename(cfg))[0]
        t = time.time()
        with open(os.path.join(logs, f"{name}.log"), "w", encoding="utf-8", errors="replace") as f:
            rc = subprocess.run([PY, "companion_run.py", cfg, "--overwrite"], cwd=ROOT, env=env,
                                stdout=f, stderr=subprocess.STDOUT).returncode
        entry = {"rc": rc, "expected_rc": expect, "ok": rc == expect, "seconds": round(time.time() - t)}
        try:
            import path_resolver
            R = path_resolver.resolve(cfg, overwrite=True)
            man = R["planned"]["manifest"]
            if os.path.exists(man) and rc == 0:
                m = json.load(open(man))
                entry.update(shot=m["shot"], delivery_mb=round(m["delivery_bytes"] / 1e6, 1),
                             work_mb=round(m["work_bytes"] / 1e6, 2), verify=m["verify"])
        except Exception as e:  # noqa: BLE001 -- report only
            entry["manifest_error"] = str(e)[:200]
        out["runs"][name] = entry
        print(f"[{'OK' if entry['ok'] else 'FAIL'}] {name} rc={rc} (expected {expect}) {entry['seconds']}s")

    after = snapshot(upstream)
    out["upstream_changed"] = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    out["upstream_files"] = len(before)
    out["all_ok"] = out["path_resolver"]["all_ok"] and all(v["ok"] for v in out["runs"].values()) and not out["upstream_changed"]
    json.dump(out, open(os.path.join(res_dir, "run_workflow_summary.json"), "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("all_ok", "upstream_files", "upstream_changed")}))
    sys.exit(0 if out["all_ok"] else 1)


if __name__ == "__main__":
    main()

"""Full regression: every suite + comparison with the frozen v0.1.0 baseline.

    python tests/run_all.py [--skip-poc]

Order: PoC -> workflow -> transactional builder -> project mode -> partial build -> GUI (headless)
-> v0.2.1 deployment fixes -> baseline compare (v0.1.0, with the reviewed v0.2.1 intended changes).  --skip-gui leaves the GUI suite out (no PySide6 / no time).
Writes <test data>/results/run_all_summary.json; exit 0 only if everything passes and
the v0.1.0 baseline values are all identical apart from the reviewed intended changes in
tests/baselines/v0.2.1_intended_changes.json (new values = added coverage, allowed).
The v0.1.0 baseline holds values measured on the production baseline shot, so it is private test
data: <test data>/baselines_private/v0.1.0.json (see tests/test_paths.py).  Missing -> the compare
is reported as NOT RUN and the exit code is 3 (never a silent pass).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOGS = os.path.join(ROOT, "logs", "run_all")
sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_paths as tp  # noqa: E402

RES = tp.results()


def step(name, args):
    os.makedirs(LOGS, exist_ok=True)
    t = time.time()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with open(os.path.join(LOGS, f"{name}.log"), "w", encoding="utf-8", errors="replace") as f:
        rc = subprocess.run([PY, *args], cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT).returncode
    print(f"[{'OK' if rc == 0 else 'FAIL'}] {name}  rc={rc}  {time.time() - t:.0f}s", flush=True)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-poc", action="store_true")
    ap.add_argument("--skip-gui", action="store_true")
    a = ap.parse_args()
    missing = tp.missing_fixture_links()
    if missing:
        sys.exit(f"fixture origin links missing (run scripts/link_fixture_origins.py): {missing}")
    rcs = {}
    if not a.skip_poc:
        for d in ("work_02a", "work_02c", "work_01_offset", "fixtures", "work_03", "packages"):
            shutil.rmtree(tp.poc(d), ignore_errors=True)
        rcs["poc"] = step("poc", ["tests/run_poc.py"])
    rcs["workflow"] = step("workflow", ["tests/run_workflow.py"])
    rcs["transaction"] = step("transaction", ["tests/test_transaction.py", tp.workflow("mock_project_C/io/configs/CC_0030.json"),
                                              tp.workflow("mock_project_B/configs/RB_0020.json"), os.path.join(RES, "test_transaction.json")])
    rcs["project_mode"] = step("project_mode", ["tests/test_project_mode.py", os.path.join(RES, "test_project_mode.json")])
    rcs["partial_build"] = step("partial_build", ["tests/test_partial_build.py", tp.workflow("mock_project_C/io/configs/CC_0030.json"),
                                                  os.path.join(RES, "test_partial_build.json")])
    if not a.skip_gui:
        rcs["gui"] = step("gui", ["tests/test_gui.py", os.path.join(RES, "test_gui.json")])
    rcs["v021_fixes"] = step("v021_fixes", ["tests/test_v021_fixes.py", os.path.join(RES, "test_v021_fixes.json")])
    rcs["v021_test2"] = step("v021_test2", ["tests/test_v021_test2.py", os.path.join(RES, "test_v021_test2.json")])
    cand = os.path.join(ROOT, "tests", "baselines", "candidate.json")
    cmp_path = os.path.join(RES, "baseline_compare.json")
    for stale in (cand, cmp_path):  # never compare a previous run's capture
        if os.path.exists(stale):
            os.remove(stale)
    not_run = {}
    base = tp.private_baselines("v0.1.0.json")
    if os.path.exists(base):
        rcs["capture"] = step("capture", ["tests/baseline_metrics.py", "capture", cand,
                                          "--extra", tp.baseline_shot()["work"]])
        rcs["baseline_v0.1.0"] = step("baseline_compare", ["tests/baseline_metrics.py", "compare",
                                                           base, cand, cmp_path,
                                                           "--intended", "tests/baselines/v0.2.1_intended_changes.json"])
    else:
        not_run["baseline_v0.1.0"] = f"private baseline missing: {base}"
        print(f"[NOT RUN] baseline_compare  ({not_run['baseline_v0.1.0']})", flush=True)
    cmp_ = json.load(open(cmp_path, encoding="utf-8")) if os.path.exists(cmp_path) else {
        k: None for k in ("baseline_values", "compared", "different", "missing_in_candidate", "new_in_candidate",
                          "intended_changes", "identical_except_intended", "identical")}
    summary = {"return_codes": rcs, "not_run": not_run, "all_ok": all(v == 0 for v in rcs.values()) and not not_run,
               "baseline": {k: cmp_.get(k) for k in ("baseline_values", "compared", "different", "missing_in_candidate",
                                                     "new_in_candidate", "intended_changes", "identical_except_intended",
                                                     "identical")}}
    json.dump(summary, open(os.path.join(RES, "run_all_summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))
    sys.exit(0 if summary["all_ok"] else 3 if all(v == 0 for v in rcs.values()) else 1)


if __name__ == "__main__":
    main()

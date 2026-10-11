"""Re-run every TEST 01 / 02 / 03 step from scratch on the demo scene.

    python tests/run_poc.py

Assumes the AI Tracking demo output already exists under <test data>/poc/walking-forest
(produced once by run_autotracker.py with the output path set to the companion).
Also snapshots the configured upstream installation before and after the test.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_paths as tp  # noqa: E402  (test data lives outside the repository)

import site_config  # noqa: E402

HYTHON = site_config.get("hython")
UPSTREAM = os.path.dirname(site_config.get("upstream_repo"))  # whole AI Tracking install, READ ONLY
SCENE = "12588331_720_1280_24fps"
RUN = tp.poc("walking-forest")
SCENE_DIR = os.path.join(RUN, SCENE)
HIP = os.path.join(SCENE_DIR, f"{SCENE}.hip")
VIDEO = os.path.join(site_config.get("upstream_repo"), "demo-test", "walking-forest", f"{SCENE}.mp4")
DELIV = tp.poc("deliveries", SCENE)
RES = tp.results()
LOGS = os.path.join(ROOT, "logs", "run_poc")


def snapshot(top):
    """path -> (size, mtime_ns) for every file; sha256 for small text files."""
    snap = {}
    for base, dirs, files in os.walk(top):
        for f in files:
            p = os.path.join(base, f)
            st = os.stat(p)
            snap[os.path.relpath(p, top)] = (st.st_size, st.st_mtime_ns)
    return snap


def step(name, cmd, ok_codes=(0,)):
    t = time.time()
    log = os.path.join(LOGS, f"{name}.log")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=ROOT).returncode
    print(f"[{'OK' if rc in ok_codes else 'FAIL'}] {name}  rc={rc}  {time.time() - t:.0f}s  ({log})")
    return rc


def main():
    os.makedirs(LOGS, exist_ok=True)
    os.makedirs(RES, exist_ok=True)
    print(f"snapshot {UPSTREAM} ...")
    before = snapshot(UPSTREAM)
    hip_before = hashlib.sha256(open(HIP, "rb").read()).hexdigest()
    for d in (DELIV,):
        if os.path.exists(d):
            shutil.rmtree(d)
    meta = os.path.join(DELIV, "companion_meta.json")
    rcs = {}
    rcs["meta"] = step("00_meta", [PY, "common/companion_meta.py", "--scene-dir", SCENE_DIR, "--source", VIDEO, "--out", meta])
    rcs["export"] = step("01_maya_export", [PY, "maya_export/run_maya_export.py", "--meta", meta, "--hip", HIP,
                                            "--out-dir", os.path.join(DELIV, "maya"), "--maya-qc",
                                            "--modes", "corrected", "original"])  # original kept for regression
    rcs["t01_validate"] = step("01_validate", [PY, "tests/test_01_validate.py", "--meta", meta, "--export-dir",
                                               os.path.join(DELIV, "maya"), "--out", os.path.join(RES, "test_01_validate.json")])
    rcs["t01b_synth"] = step("01b_winy_synthetic", [HYTHON, "tests/test_01b_hou_winy_synthetic.py",
                                                     os.path.join(RES, "test_01b_synthetic.json")])
    rcs["t01_offset"] = step("01_frame_offset", [PY, "tests/test_01_frame_offset.py", meta, HIP,
                                                 tp.poc("work_01_offset"),
                                                 os.path.join(RES, "test_01_frame_offset.json")])
    rcs["stmap"] = step("02_stmap_generator", [PY, "stmap/stmap_generator.py", "--meta", meta, "--out-dir", os.path.join(DELIV, "stmap")])
    smeta = os.path.join(DELIV, "stmap", f"{SCENE}_stmap_meta.json")
    rcs["r1_maya_prod_export"] = step("01p_maya_production_export", [
        PY, "maya_export/run_maya_export.py", "--meta", meta, "--hip", HIP, "--out-dir", os.path.join(DELIV, "maya_production"),
        "--maya-qc", "--modes", "corrected", "original", "--production-canvas", smeta])
    rcs["r1_maya_prod_validate"] = step("01p_maya_production_validate", [
        PY, "tests/test_r1_maya_production.py", meta, os.path.join(DELIV, "maya_production"), os.path.join(DELIV, "stmap"),
        os.path.join(RES, "r1_maya_production.json")])
    w2a = tp.poc("work_02a")
    rcs["t02a"] = step("02a_proxy", [PY, "tests/test_02a_proxy.py", "--meta", meta, "--work", w2a, "--out", os.path.join(RES, "test_02a.json")])
    rcs["t02a_extra"] = step("02a_nuke_extra", [PY, "tests/test_02a_nuke_extra.py", meta, w2a, os.path.join(RES, "test_02a_nuke_extra.json")])
    rcs["t02b"] = step("02b_fullres_camera", [PY, "tests/test_02b_fullres_camera.py", meta, os.path.join(DELIV, "maya"),
                                              os.path.join(DELIV, "stmap"), os.path.join(RES, "test_02b_fullres_camera.json")])
    rcs["t02c"] = step("02c_roundtrip", [PY, "tests/test_02c_roundtrip.py", "--meta", meta, "--stmap-dir", os.path.join(DELIV, "stmap"),
                                         "--work", tp.poc("work_02c"), "--out", os.path.join(RES, "test_02c.json")])
    rcs["t_meta"] = step("03_meta_unsupported", [PY, "tests/test_meta_and_unsupported.py", "--demo-scene", SCENE_DIR,
                                                 "--work", tp.poc("fixtures"),
                                                 "--out", os.path.join(RES, "test_meta_and_unsupported.json")])
    rcs["t03_nuke_package"] = step("04_nuke_package", [PY, "tests/test_03_nuke_package.py", "--meta", meta,
                                                         "--maya-dir", os.path.join(DELIV, "maya_production"),
                                                         "--out", os.path.join(RES, "test_03.json")])
    rcs["t03b_canvas"] = step("04b_canvas_coverage", [PY, "tests/test_03b_canvas_coverage.py", meta,
                                                       tp.poc("packages", SCENE),
                                                       os.path.join(RES, "test_03b_canvas_coverage.json")])
    after = snapshot(UPSTREAM)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    hip_after = hashlib.sha256(open(HIP, "rb").read()).hexdigest()
    summary = {"return_codes": rcs, "upstream_files": len(before), "upstream_changed": changed,
               "hip_sha256_before": hip_before, "hip_sha256_after": hip_after, "hip_unchanged": hip_before == hip_after}
    json.dump(summary, open(os.path.join(RES, "run_poc_summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

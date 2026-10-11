"""Houdini -> Maya delivery driver (plain Python, no GUI).

    python run_maya_export.py --meta companion_meta.json --hip scene.hip --out-dir DIR
                              [--modes original corrected] [--maya-qc]

For each winy mode: hython loads the HIP, modifies the camera in memory,
exports FBX + Alembic, exits without saving.  The HIP sha256 and mtime are
checked before and after the whole run.  Unsupported scenes are refused
before any output is produced.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maya_units import maya_time_unit  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "common"))
import site_config  # noqa: E402

HYTHON = site_config.get("hython")
MAYAPY = site_config.get("mayapy")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_env():
    env = os.environ.copy()
    for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(k, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run(cmd, log_path):
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=clean_env())
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--hip", required=True)
    ap.add_argument("--out-dir", required=True)
    # corrected winy is the production default; add "original" only for QC comparison
    ap.add_argument("--modes", nargs="+", default=["corrected"], choices=["corrected", "original"])
    ap.add_argument("--maya-qc", action="store_true", help="import results in headless Maya and dump")
    ap.add_argument("--production-canvas", metavar="STMAP_META",
                    help="export the production full-res camera (converged canvas) instead of tracking space")
    ap.add_argument("--hython", default=HYTHON)
    ap.add_argument("--mayapy", default=MAYAPY)
    a = ap.parse_args()

    meta = json.load(open(a.meta))
    if not meta["support"]["supported"]:
        print("UNSUPPORTED -- no delivery produced:\n  " + "\n  ".join(meta["support"]["reasons"]))
        sys.exit(2)
    hip = os.path.abspath(a.hip)
    before = (sha256(hip), os.path.getmtime(hip), os.path.getsize(hip))
    os.makedirs(a.out_dir, exist_ok=True)
    summary = {"hip": hip, "hip_sha256_before": before[0], "runs": {}}

    for i, mode in enumerate(a.modes):
        cmd = [a.hython, os.path.join(HERE, "hython_export.py"), "--hip", hip, "--meta", os.path.abspath(a.meta),
               "--out-dir", os.path.abspath(a.out_dir), "--winy-mode", mode]
        if i == 0:
            cmd.append("--with-points")
        if a.production_canvas:
            cmd += ["--production-canvas", os.path.abspath(a.production_canvas)]
        rc = run(cmd, os.path.join(a.out_dir, f"hython_{mode}.log"))
        summary["runs"][mode] = {"hython_rc": rc}
        if rc != 0:
            print(f"[FAIL] hython {mode} rc={rc}; see hython_{mode}.log")
            continue
        if a.maya_qc:
            ref = json.load(open(os.path.join(a.out_dir, f"houdini_reference_{mode}.json")))
            f1, f2 = (int(round(x)) for x in ref["export_key_range"])
            cmd = [a.mayapy, os.path.join(HERE, "maya_dump.py"), "--fbx", ref["outputs"]["fbx"],
                   "--cam-abc", ref["outputs"]["cam_abc"], "--frames", str(f1), str(f2),
                   "--canvas", str(int(ref["resx"])), str(int(ref["resy"])),
                   "--out", os.path.join(a.out_dir, f"maya_dump_{mode}.json"),
                   "--scene-time", maya_time_unit(ref["abc_fps"]),
                   "--fbx-sidecar", ref["outputs"]["sidecar"]]
            pts = ref["outputs"]["points_abc"]
            if os.path.exists(pts):
                cmd += ["--points-abc", pts]
            summary["runs"][mode]["mayapy_rc"] = run(cmd, os.path.join(a.out_dir, f"mayapy_{mode}.log"))

    after = (sha256(hip), os.path.getmtime(hip), os.path.getsize(hip))
    summary["hip_sha256_after"] = after[0]
    summary["hip_unchanged"] = before == after
    with open(os.path.join(a.out_dir, "export_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))
    ok = summary["hip_unchanged"] and all(r.get("hython_rc") == 0 and r.get("mayapy_rc", 0) == 0
                                          for r in summary["runs"].values())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

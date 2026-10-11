"""TEST 01 frame offset: simulate a sequence numbered from 1001 on the demo HIP.

    python test_01_frame_offset.py META HIP WORK OUT.json

Copies META with frame_offset_tracking_to_source=1000, exports via hython
(memory only), then checks Houdini key range, FBX KeyTime and Alembic sampling.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "maya_export"))
from run_maya_export import HYTHON, clean_env, sha256  # noqa: E402

KTIME_PER_S = 46186158000
ABCINFO = os.path.join(os.path.dirname(HYTHON), "abcinfo.exe")


def main():
    meta_p, hip, work, out = sys.argv[1:5]
    os.makedirs(work, exist_ok=True)
    meta = json.load(open(meta_p))
    meta["tracking"]["frame_offset_tracking_to_source"] = 1000
    mp = os.path.join(work, "meta_offset1000.json")
    json.dump(meta, open(mp, "w"), indent=1)
    h0 = sha256(hip)
    r = subprocess.run([HYTHON, os.path.join(ROOT, "maya_export", "hython_export.py"), "--hip", hip, "--meta", mp,
                        "--out-dir", work, "--winy-mode", "corrected"], capture_output=True, text=True, env=clean_env())
    ref = json.load(open(os.path.join(work, "houdini_reference_corrected.json")))
    fbx = open(ref["outputs"]["fbx"]).read()
    arr = re.search(r"KeyTime: \*\d+ \{\s*a: ([0-9,\s]+)", fbx).group(1)
    kt = [int(x) for x in arr.split(",") if x.strip()]
    abc = subprocess.run([ABCINFO, ref["outputs"]["cam_abc"]], capture_output=True, text=True).stdout
    res = {"hython_rc": r.returncode, "hip_unchanged": sha256(hip) == h0,
           "export_key_range": ref["export_key_range"], "key_count": len(ref["key_frames"]),
           "fbx_first_key_frame_at_24": kt[0] / KTIME_PER_S * 24, "fbx_last_key_frame_at_24": kt[-1] / KTIME_PER_S * 24,
           "abcinfo": [l.strip() for l in abc.splitlines() if "TimeSample" in l],
           "sidecar_range": [json.load(open(ref["outputs"]["sidecar"]))[k] for k in ("frame_start", "frame_end")]}
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

"""TEST 02A extra: Nuke filter choice and black-outside setup (center normalisation)."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "stmap")); sys.path.insert(0, HERE)
import stmap_core as sc, cv2, numpy as np
from test_02a_proxy import NUKE, NUKE_RENDER, stats, border_masks
meta = json.load(open(sys.argv[1])); work = sys.argv[2]; out = sys.argv[3]
cam = sc.Camera(json.load(open(meta["transforms_json"])))
nw, nh, ncx, ncy = sc.canvas(cam); mx, my = sc.undistort_map(cam, nw, nh, ncx, ncy)
valid = (mx >= 0) & (mx <= cam.w - 1) & (my >= 0) & (my <= cam.h - 1)
interior, edge = border_masks(valid)
st = os.path.join(work, "proxy_undistort_center.exr"); ramp = os.path.join(work, "proxy_src_ramp.exr")
res = {}
for filt, mode in [("Cubic", "black"), ("Keys", ""), ("Simon", ""), ("Rifman", ""), ("Mitchell", ""), ("Lanczos4", ""), ("Notch", "")]:
    o = os.path.join(work, f"nuke_ramp_center_{filt}{'_'+mode if mode else ''}.exr")
    r = subprocess.run([NUKE, "-t", NUKE_RENDER, st, ramp, o, filt] + ([mode] if mode else []), capture_output=True, text=True)
    img = cv2.imread(o, cv2.IMREAD_UNCHANGED)
    if img is None:
        res[f"{filt}{mode}"] = {"error": r.stdout[-500:] + r.stderr[-500:]}; continue
    d = np.hypot(img[..., 2] - mx, img[..., 1] - my)
    res[f"{filt}{'/'+mode if mode else ''}"] = {"interior": stats(d, interior), "edge": stats(d, edge),
        "outside_rgb_max": float(np.abs(img[~valid][:, :3]).max()), "outside_alpha_max": float(img[~valid][:, 3].max()) if img.shape[2] > 3 else None}
json.dump(res, open(out, "w"), indent=1)
for k, v in res.items():
    print(k, v.get("error") or ({a: round(b, 4) for a, b in v["interior"].items()}, "edge max %.4f" % v["edge"]["max"], "outside rgb max", v["outside_rgb_max"]))

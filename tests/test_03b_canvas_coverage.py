"""TEST 03B / Revision 01 -- does the full-res canvas contain every plate pixel?

    python tests/test_03b_canvas_coverage.py META PACKAGE_DIR OUT.json

For every (canvas rule x redistort solver) combination:
  * geometric: plate pixels whose redistort sample position falls outside the canvas
  * image: OpenCV remap of a white canvas through that redistort map
    (BORDER_CONSTANT, same as Crop black-outside) -> exact-zero pixels
The production combination is (converged canvas, converged solver).
(legacy canvas, converged solver) is the TEST 03 failure -- kept as the
sensitivity control for the metric.  Also counts exact-zero invalid pixels in
the real Nuke delivery render (test_03 linear pass) when present.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "stmap"))
import stmap_core as sc  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402


def corner_dist(mask):
    yy, xx = np.nonzero(mask)
    H, W = mask.shape
    return float(np.max(np.hypot(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy)))) if len(xx) else None


def main():
    meta_p, pkg, out = sys.argv[1:4]
    meta = json.load(open(meta_p))
    lj = json.load(open(glob.glob(os.path.join(pkg, "metadata", "*_lens.json"))[0]))
    W, H = lj["source"]["resolution"]
    cam = sc.Camera(json.load(open(meta["transforms_json"]))).scaled(W, H)
    canv = {"production_converged": sc.canvas(cam, solver="converged"),
            "legacy_upstream_rule": sc.canvas(cam, solver="legacy")}
    pkg_canvas = lj["production_canvas"]["resolution"] + lj["production_canvas"]["principal_point"]
    res = {"plate": [W, H], "canvases": {k: list(v) for k, v in canv.items()},
           "package_canvas": pkg_canvas,
           "package_canvas_is_converged": np.allclose(pkg_canvas, canv["production_converged"])}
    for cname, (fw, fh, fcx, fcy) in canv.items():
        white = np.ones((fh, fw), np.float32)
        for solver in sc.REDISTORT_SOLVERS:
            qx, qy = sc.redistort_map(cam, fcx, fcy, solver)
            outside = (qx < -0.5) | (qx > fw - 0.5) | (qy < -0.5) | (qy > fh - 0.5)
            over = np.maximum.reduce([-0.5 - qx, qx - (fw - 0.5), -0.5 - qy, qy - (fh - 0.5), np.zeros_like(qx)])
            img = cv2.remap(white, qx, qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            zero = img == 0.0
            res[f"{cname}/{solver}"] = {"plate_pixels_outside_canvas": int(outside.sum()),
                                        "max_distance_outside_px": float(over.max()),
                                        "exact_zero_pixels_after_remap": int(zero.sum()),
                                        "max_dist_from_corner_px": corner_dist(zero)}
    # real Nuke delivery render (linear pass of test_03), exact zeros only
    vdir = os.path.join(os.path.dirname(os.path.dirname(pkg)), "work_03", "orig_linear")
    nuke = {}
    for f in (1, 168, 337):
        pr = os.path.join(vdir, f"APPLY_REDISTORT.{f:04d}.exr")
        pl = os.path.join(vdir, f"READ_ORIGINAL_PLATE.{f:04d}.exr")
        if os.path.exists(pr):
            r = np.abs(cv2.imread(pr, cv2.IMREAD_UNCHANGED)[..., :3]).max(axis=2)
            p = np.abs(cv2.imread(pl, cv2.IMREAD_UNCHANGED)[..., :3]).max(axis=2)
            blk = (r == 0.0) & (p > 0.0)
            nuke[str(f)] = {"exact_zero_invalid_pixels": int(blk.sum()), "max_dist_from_corner_px": corner_dist(blk)}
    res["nuke_delivery_render"] = nuke
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

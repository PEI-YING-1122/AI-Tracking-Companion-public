"""Revision 01 -- production Maya camera on the converged full-res canvas.

    python tests/test_r1_maya_production.py META MAYA_PROD_DIR STMAP_DIR OUT.json

Truth: transforms_undistorted.json c2w + production K
    [[fx_full, 0, cx_canvas], [0, fy_full, cy_canvas]]   (converged canvas)
Compared with what headless Maya actually evaluates for the Camera Alembic
(primary) and FBX + sidecar (fallback), corrected and original winy.
Also checks the resolution gate and that the hython sidecar equals the
STMap generator's full_maya_camera.json.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
from test_01_validate import truth_pixels, maya_pixels, maya_pixels_explicit, errstats, fnum, in_frame  # noqa: E402


def main():
    meta_p, mdir, sdir, out = sys.argv[1:5]
    meta = json.load(open(meta_p))
    shot = meta["scene_name"]
    uj = json.load(open(meta["transforms_undistorted_json"]))
    sm = json.load(open(os.path.join(sdir, f"{shot}_stmap_meta.json")))
    fc = sm["full"]["camera"]
    W, H, ccx, ccy = sm["full"]["canvas"]
    Kp = np.array([[fc["fl_x"], 0, ccx], [0, fc["fl_y"], ccy], [0, 0, 1]], dtype=np.float64)
    c2w = {fnum(f["file_path"]): f["transform_matrix"] for f in uj["frames"]}
    res = {"production_canvas": [W, H, ccx, ccy], "modes": {}}
    gen_side = json.load(open(os.path.join(sdir, f"{shot}_full_maya_camera.json")))
    for mode in ("corrected", "original"):
        ref = json.load(open(os.path.join(mdir, f"houdini_reference_{mode}.json")))
        dump = json.load(open(os.path.join(mdir, f"maya_dump_{mode}.json")))
        side = json.load(open(os.path.join(mdir, f"{shot}_cam_{mode}.maya_camera.json")))
        Xh = np.asarray(ref["points_sample"])
        r = {"houdini": {k: ref[k] for k in ("space", "resx", "resy", "aperture", "focal", "winx", "winy")}}
        for kind in ("abc", "fbx"):
            d = dump[kind]
            L = d["lens"]
            mf = {int(round(fr["frame"])): fr["world"] for fr in d["frames"]}
            dx, da = [], []
            for fr in ref["frames"]:
                f = int(round(fr["frame"]))
                t, z = truth_pixels(c2w[f - ref["frame_offset"]], Kp, Xh)
                ok = in_frame(t, z, W, H)
                dx.append((maya_pixels_explicit(mf[f], L, W, H, Xh) - t)[ok])
                da.append((maya_pixels(mf[f], d["projection_matrix"], W, H, Xh) - t)[ok])
            r[kind] = {"maya_vs_truth": errstats(np.vstack(dx)),
                       "maya_api_projmatrix_vs_truth": errstats(np.vstack(da)),
                       "lens": {k: L[k] for k in ("focalLength", "horizontalFilmAperture", "verticalFilmAperture",
                                                  "horizontalFilmOffset", "verticalFilmOffset", "filmFit")},
                       "gate_aspect_film": L["horizontalFilmAperture"] / L["verticalFilmAperture"],
                       "gate_aspect_canvas": W / H,
                       "maya_aspectRatio": d["aspectRatio"],
                       "key_range": d.get("key_range")}
        r["sidecar_resolution"] = side["resolution"]
        if mode == "corrected":
            r["sidecar_vs_stmap_generator_max_abs"] = max(
                abs(side[k] - gen_side[k]) for k in ("focalLength_mm", "horizontalFilmAperture_in", "verticalFilmAperture_in",
                                                     "horizontalFilmOffset_in", "verticalFilmOffset_in"))
            r["sidecar_resolution_equals_generator"] = side["resolution"] == gen_side["resolution"]
        res["modes"][mode] = r
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res, indent=1)[:5000])


if __name__ == "__main__":
    main()

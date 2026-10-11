"""TEST 02B -- full-res Maya camera vs full-res undistorted canvas.

    python test_02b_fullres_camera.py META MAYA_DIR STMAP_DIR OUT.json

Projects the Houdini point samples with the Maya film-back formula (validated in
TEST 01 against Maya's own projection matrix) using
  (a) the full-res sidecar from stmap_generator, and
  (b) the proxy sidecar naively reused on the full-res canvas,
against the full-res pinhole truth on the production canvas:
    K_prod = [[fx_full, 0, cx_canvas], [0, fy_full, cy_canvas]]
(Revision 01: the production canvas is the converged canvas, so its principal
point is NOT the proxy canvas pp x scale; the old "proxy truth x scale" truth was
only valid for the legacy canvas.)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
from test_01_validate import truth_pixels, maya_pixels_explicit, errstats, fnum, in_frame  # noqa: E402


def lens(sc):
    return {"focalLength": sc["focalLength_mm"], "horizontalFilmAperture": sc["horizontalFilmAperture_in"],
            "verticalFilmAperture": sc["verticalFilmAperture_in"],
            "horizontalFilmOffset": sc["horizontalFilmOffset_in"], "verticalFilmOffset": sc["verticalFilmOffset_in"]}


def main():
    meta_p, maya_dir, stmap_dir, out = sys.argv[1:5]
    meta = json.load(open(meta_p))
    scene = meta["scene_name"]
    uj = json.load(open(meta["transforms_undistorted_json"]))
    sm = json.load(open(os.path.join(stmap_dir, f"{scene}_stmap_meta.json")))
    sx, sy = sm["full"]["scale"]
    fw, fh = sm["full"]["canvas"][:2]
    fc = sm["full"]["camera"]
    Kp = np.array([[fc["fl_x"], 0, sm["full"]["canvas"][2]], [0, fc["fl_y"], sm["full"]["canvas"][3]], [0, 0, 1]])
    c2w = {fnum(f["file_path"]): f["transform_matrix"] for f in uj["frames"]}
    ref = json.load(open(os.path.join(maya_dir, "houdini_reference_corrected.json")))
    Xh = np.asarray(ref["points_sample"])
    full_sc = json.load(open(os.path.join(stmap_dir, f"{scene}_full_maya_camera.json")))
    proxy_sc = json.load(open(os.path.join(maya_dir, f"{scene}_cam_corrected.maya_camera.json")))
    res = {"full_canvas": [fw, fh], "proxy_canvas_x_scale": [uj["w"] * sx, uj["h"] * sy],
           "full_sidecar": {k: full_sc[k] for k in ("resolution", "verticalFilmAperture_in", "verticalFilmOffset_in")},
           "proxy_sidecar": {k: proxy_sc[k] for k in ("resolution", "verticalFilmAperture_in", "verticalFilmOffset_in")}}
    for name, sc in (("full_sidecar_vs_truth", full_sc), ("proxy_sidecar_on_full_canvas_vs_truth", proxy_sc)):
        d = []
        for fr in ref["frames"]:
            f = int(round(fr["frame"])) - ref["frame_offset"]
            t, z = truth_pixels(c2w[f], Kp, Xh)
            ok = in_frame(t, z, fw, fh)
            d.append((maya_pixels_explicit(fr["world"], lens(sc), fw, fh, Xh) - t)[ok])
        res[name] = errstats(np.vstack(d))
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

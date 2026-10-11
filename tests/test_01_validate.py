"""TEST 01 -- compare Houdini reference, Maya import, and pinhole ground truth.

    python test_01_validate.py --meta META --export-dir DIR --out result.json

Ground truth (independent of Houdini/Maya): transforms_undistorted.json
c2w + K_new pinhole, in COLMAP edge-origin pixel coords of the undistorted canvas.
Observation check: COLMAP points2D undistorted with the upstream K/D (P=K_new).
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "stmap"))
import stmap_core as sc  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402

FLIP = np.diag([1.0, -1.0, -1.0])  # COLMAP world <-> Houdini world (its own inverse)


def fnum(path):
    return int(re.findall(r"\d+", os.path.basename(path))[-1])


def truth_pixels(c2w, Kn, Xh):
    """Houdini-world points -> undistorted canvas pixels via upstream JSON camera."""
    Xc = Xh @ FLIP.T
    w2c = np.linalg.inv(np.asarray(c2w))
    p = Xc @ w2c[:3, :3].T + w2c[:3, 3]           # GL camera space (look -Z, Y up)
    z = -p[:, 2]
    u = Kn[0, 0] * p[:, 0] / z + Kn[0, 2]
    v = Kn[1, 1] * -p[:, 1] / z + Kn[1, 2]
    return np.stack([u, v], 1), z


def in_frame(t, z, W, H):
    """points in front of the camera whose true projection lands on the canvas"""
    return (z > 0.05) & (t[:, 0] >= 0) & (t[:, 0] <= W) & (t[:, 1] >= 0) & (t[:, 1] <= H)


def houdini_pixels(world_rowvec, lens, Xh):
    M = np.asarray(world_rowvec)                    # Houdini row-vector cam->world
    inv = np.linalg.inv(M)
    p = np.hstack([Xh, np.ones((len(Xh), 1))]) @ inv
    z = -p[:, 2]
    k = lens["focal"] / lens["aperture"]
    ndx = 0.5 + k * p[:, 0] / z - lens["winx"]
    ndy = 0.5 + k * (lens["resx"] / lens["resy"]) * p[:, 1] / z - lens["winy"]
    return np.stack([ndx * lens["resx"], (1 - ndy) * lens["resy"]], 1)


def maya_pixels(world_rowvec, P, W, H, Xh):
    inv = np.linalg.inv(np.asarray(world_rowvec))
    p = np.hstack([Xh, np.ones((len(Xh), 1))]) @ inv
    clip = p @ np.asarray(P)
    ndc = clip[:, :2] / clip[:, 3:4]
    return np.stack([(ndc[:, 0] + 1) / 2 * W, (1 - ndc[:, 1]) / 2 * H], 1)


def maya_pixels_explicit(world_rowvec, lens, W, H, Xh):
    """Maya film-back maths written out (horizontal fit, aperture aspect == image aspect)."""
    inv = np.linalg.inv(np.asarray(world_rowvec))
    p = np.hstack([Xh, np.ones((len(Xh), 1))]) @ inv
    z = -p[:, 2]
    f_in = lens["focalLength"] / 25.4
    xf = f_in * p[:, 0] / z
    yf = f_in * p[:, 1] / z
    ndx = (xf - lens["horizontalFilmOffset"]) / lens["horizontalFilmAperture"] + 0.5
    ndy = (yf - lens["verticalFilmOffset"]) / lens["verticalFilmAperture"] + 0.5
    return np.stack([ndx * W, (1 - ndy) * H], 1)


def errstats(d):
    d = np.asarray(d)
    n = np.hypot(d[:, 0], d[:, 1])
    return {"max_px": float(n.max()), "mean_px": float(n.mean()), "rmse_px": float(np.sqrt((n ** 2).mean())),
            "mean_du": float(d[:, 0].mean()), "mean_dv": float(d[:, 1].mean())}


def read_colmap_text(sparse):
    pts = {}
    with open(os.path.join(sparse, "points3D.txt")) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            e = line.split()
            pts[int(e[0])] = np.array(list(map(float, e[1:4])))
    obs = {}
    with open(os.path.join(sparse, "images.txt")) as f:
        lines = [l.rstrip("\n") for l in f if not l.startswith("#")]
    for i in range(0, len(lines) - 1, 2):
        head = lines[i].split()
        if not head:
            continue
        name = head[9]
        e = lines[i + 1].split()
        xy = np.array(e, dtype=np.float64).reshape(-1, 3) if e else np.zeros((0, 3))
        xy = xy[xy[:, 2] >= 0]
        obs[fnum(name)] = xy
    return pts, obs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    meta = json.load(open(a.meta))
    uj = json.load(open(meta["transforms_undistorted_json"]))
    tj = json.load(open(meta["transforms_json"]))
    Kn = np.array([[uj["fl_x"], 0, uj["cx"]], [0, uj["fl_y"], uj["cy"]], [0, 0, 1]], dtype=np.float64)
    W, H = int(uj["w"]), int(uj["h"])
    c2w = {fnum(fr["file_path"]): fr["transform_matrix"] for fr in uj["frames"]}
    res = {"canvas": [W, H], "cx": uj["cx"], "cy": uj["cy"], "cy_minus_h2": uj["cy"] - H / 2,
           "cx_minus_w2": uj["cx"] - W / 2, "modes": {}}

    pts3d, obs = read_colmap_text(os.path.join(meta["scene_dir"], "sparse"))
    cam = sc.Camera(tj)

    for mode in ("original", "corrected"):
        ref = json.load(open(os.path.join(a.export_dir, f"houdini_reference_{mode}.json")))
        dump = json.load(open(os.path.join(a.export_dir, f"maya_dump_{mode}.json")))
        Xh = np.asarray(ref["points_sample"])
        off = ref["frame_offset"]
        r = {"winy": ref["winy"], "winx": ref["winx"], "focal": ref["focal"], "aperture": ref["aperture"],
             "resx": ref["resx"], "resy": ref["resy"], "hip_key_range": ref["hip_key_range"],
             "export_key_range": ref["export_key_range"], "fbx_fps": ref["fbx_fps"], "abc_fps": ref["abc_fps"],
             "hip_fps": ref["hip_fps"]}
        lens_h = {k: ref[k] for k in ("focal", "aperture", "resx", "resy", "winx", "winy")}
        hframes = {fr["frame"]: fr["world"] for fr in ref["frames"]}

        # Houdini camera vs ground truth (every keyed frame)
        dh = []
        for f, M in hframes.items():
            t, z = truth_pixels(c2w[int(f) - off], Kn, Xh)
            ok = in_frame(t, z, W, H)
            dh.append((houdini_pixels(M, lens_h, Xh) - t)[ok])
        r["houdini_vs_truth"] = errstats(np.vstack(dh))

        # Euler continuity of the Houdini keys (FBX carries these Euler values)
        rots = np.array([fr["r"] for fr in ref["frames"]])
        dr = np.abs(np.diff(rots, axis=0))
        r["euler"] = {"max_step_deg": dr.max(0).tolist(), "steps_over_90deg": int((dr > 90).sum())}

        for kind in ("fbx_raw", "fbx", "abc"):
            d = dump.get(kind)
            if d is None:
                r[f"maya_{kind}"] = {"error": "camera not found", "cams": dump.get(f"{kind.split('_')[0]}_cameras")}
                continue
            mf = {int(round(fr["frame"])): fr["world"] for fr in d["frames"]}
            mat_err, dm, dmx, dme, dmh = 0.0, [], [], [], []
            for f, M in hframes.items():
                f = int(round(f))
                if f not in mf:
                    continue
                mat_err = max(mat_err, float(np.abs(np.asarray(mf[f]) - np.asarray(M)).max()))
                t, z = truth_pixels(c2w[f - off], Kn, Xh)
                ok = in_frame(t, z, W, H)
                pm = maya_pixels(mf[f], d["projection_matrix"], W, H, Xh)       # Maya API (float32 matrix)
                px = maya_pixels_explicit(mf[f], d["lens"], W, H, Xh)          # Maya film-back maths (double)
                dm.append((pm - t)[ok])
                dmx.append((px - t)[ok])
                dme.append((px - pm)[ok])
                dmh.append((px - houdini_pixels(M, lens_h, Xh))[ok])
            L = d["lens"]
            r[f"maya_{kind}"] = {
                "key_range": d.get("key_range"), "key_count": d.get("key_count"),
                "lens": L, "aspectRatio": d["aspectRatio"], "rotateOrder": d["rotateOrder"],
                "parents": d["parents"],
                "focal_diff_mm": L["focalLength"] - ref["focal"],
                "hfa_diff_mm": L["horizontalFilmAperture"] * 25.4 - ref["aperture"],
                "vfa_diff_mm": L["verticalFilmAperture"] * 25.4 - ref["aperture"] * ref["resy"] / ref["resx"],
                "hfo_expected_in": ref["winx"] * L["horizontalFilmAperture"],
                "vfo_expected_in": ref["winy"] * L["verticalFilmAperture"],
                "world_matrix_max_abs_diff_vs_houdini": mat_err,
                "maya_vs_truth": errstats(np.vstack(dmx)),
                "maya_api_projmatrix_vs_truth": errstats(np.vstack(dm)),
                "maya_vs_houdini": errstats(np.vstack(dmh)),
                "api_projmatrix_vs_explicit": errstats(np.vstack(dme)),
            }
            # observation check: real COLMAP 2D features (undistorted with upstream K/D)
            allres = []
            for f_t, xy in obs.items():
                fm = f_t + off
                if fm not in mf or len(xy) == 0:
                    continue
                keep = np.array([int(i) in pts3d for i in xy[:, 2]])
                if not keep.any():
                    continue
                X = np.array([pts3d[int(i)] for i in xy[keep, 2]])
                und = cv2.undistortPoints(xy[keep, :2].reshape(-1, 1, 2), cam.K, cam.D, P=Kn).reshape(-1, 2)
                allres.append(maya_pixels_explicit(mf[fm], L, W, H, X @ FLIP.T) - und)
            allres = np.vstack(allres)
            o = errstats(allres)
            o["n"] = int(len(allres))
            o["sem_dv"] = float(allres[:, 1].std() / np.sqrt(len(allres)))
            o["sem_du"] = float(allres[:, 0].std() / np.sqrt(len(allres)))
            r[f"maya_{kind}"]["observations"] = o
        r["maya_scene"] = {k: dump.get(k) for k in ("fbx_scene_before", "fbx_scene_after", "fbx_scene_after_sidecar", "abc_scene_after")}
        res["modes"][mode] = r

    # point cloud ABC
    # points are exported once, by whichever mode ran first
    for pmode in ("corrected", "original"):
        ref = json.load(open(os.path.join(a.export_dir, f"houdini_reference_{pmode}.json")))
        pdump = json.load(open(os.path.join(a.export_dir, f"maya_dump_{pmode}.json"))).get("points")
        if pdump:
            break
    if pdump:
        pr = {"houdini_count": ref["point_count"], "maya_count": pdump.get("count"),
              "maya_type": pdump.get("type"), "new_nodes": pdump.get("new_nodes"),
              "maya_attrs": pdump.get("attrs"), "houdini_attrs": ref["point_attribs"]}
        if pdump.get("sample"):
            mp = np.asarray(pdump["sample"])
            Hs = np.asarray(ref["points_sample"])
            if pdump.get("parent_world"):
                pw = np.asarray(pdump["parent_world"]).reshape(4, 4)
                mp = np.hstack([mp, np.ones((len(mp), 1))]) @ pw
                mp = mp[:, :3]
            if pdump.get("stride") == ref["point_stride"] and len(mp) == len(Hs):
                pr["position_max_abs_diff"] = float(np.abs(mp - Hs).max())
            else:
                pr["position_max_abs_diff"] = None
                pr["note"] = "sample stride/order differs; only bbox compared"
            pr["maya_bbox"] = [mp.min(0).tolist(), mp.max(0).tolist()]
            pr["houdini_bbox"] = ref["point_bbox"]
            pr["parent_world"] = pdump.get("parent_world")
        res["points"] = pr

    o, c = res["modes"]["original"], res["modes"]["corrected"]
    res["winy_summary"] = {
        "original_winy": o["winy"], "corrected_winy": c["winy"], "difference": c["winy"] - o["winy"],
        "predicted_shift_px_v": -(res["cy_minus_h2"]) * (1 + H / W),
        "measured_houdini_mean_dv_original": o["houdini_vs_truth"]["mean_dv"],
        "measured_houdini_mean_dv_corrected": c["houdini_vs_truth"]["mean_dv"],
    }
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1)[:8000])


if __name__ == "__main__":
    main()

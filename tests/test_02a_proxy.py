"""TEST 02A -- proxy STMap validation.

    python test_02a_proxy.py --meta META --stmap-dir DIR --work DIR --out result.json

1. Nuke ramp test: real Nuke STMap samples a coordinate ramp; the rendered value
   IS the sample position.  Compared against upstream's own map for both
   normalisations -> decides normalisation, Y orientation, pixel centre.
2. Image test: proxy images/ -> STMap (validated convention) -> compare with
   upstream images_undistorted/ (JPEG on disk) and with an in-memory
   re-run of upstream's exact remap (lossless).
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "stmap"))
import stmap_core as sc  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "common"))
import site_config  # noqa: E402

NUKE = site_config.get("nuke")
NUKE_RENDER = os.path.join(HERE, "..", "stmap", "nuke_stmap_render.py")


def stats(err, mask=None):
    e = np.abs(err) if mask is None else np.abs(err[mask])
    if e.size == 0:
        return None
    return {"max": float(e.max()), "mean": float(e.mean()), "rmse": float(np.sqrt((e.astype(np.float64) ** 2).mean())),
            "p99": float(np.percentile(e, 99)), "n": int(e.size)}


def ramp(w, h):
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return np.dstack([np.ones_like(gx), gy, gx])  # BGR -> R=x, G=y, B=1 (valid flag)


def nuke_render(stmap, src, out, filt):
    r = subprocess.run([NUKE, "-t", NUKE_RENDER, stmap, src, out, filt], capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"Nuke failed: {r.stdout[-2000:]} {r.stderr[-2000:]}")
    return [l for l in r.stdout.splitlines() if l.startswith(("STMap inputs", "format"))]


def border_masks(valid, width=3):
    """interior = sample footprint fully inside the source, edge = the rest of valid."""
    k = np.ones((2 * width + 1, 2 * width + 1), np.uint8)
    interior = cv2.erode(valid.astype(np.uint8), k).astype(bool)
    return interior, valid & ~interior


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=0, help="limit image test frames (0 = all)")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    meta = json.load(open(a.meta))
    tj = json.load(open(meta["transforms_json"]))
    cam = sc.Camera(tj)
    nw, nh, ncx, ncy = sc.canvas(cam)
    mx, my = sc.undistort_map(cam, nw, nh, ncx, ncy)
    res = {"proxy_plate": [cam.w, cam.h], "proxy_canvas": [nw, nh, ncx, ncy]}

    # in-source sample positions (the only pixels where upstream draws image data)
    valid = (mx >= 0) & (mx <= cam.w - 1) & (my >= 0) & (my <= cam.h - 1)
    interior, edge = border_masks(valid)
    res["canvas_pixels"] = {"total": int(valid.size), "in_source": int(valid.sum()),
                            "interior": int(interior.sum()), "edge_band": int(edge.sum()),
                            "outside_source": int((~valid).sum())}

    # ---- 1. Nuke ramp test ------------------------------------------------------
    ramp_path = os.path.join(a.work, "proxy_src_ramp.exr")
    cv2.imwrite(ramp_path, ramp(cam.w, cam.h), [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT])
    res["nuke"] = {}
    for norm in sc.NORMALISATIONS:
        s, t = sc.to_stmap(mx, my, cam.w, cam.h, norm)
        st_path = os.path.join(a.work, f"proxy_undistort_{norm}.exr")
        sc.write_stmap_exr(st_path, s, t)
        for filt in ("Cubic", "Impulse"):
            out = os.path.join(a.work, f"nuke_ramp_{norm}_{filt}.exr")
            log = nuke_render(st_path, ramp_path, out, filt)
            img = cv2.imread(out, cv2.IMREAD_UNCHANGED)  # B G R A
            nx, ny, nb = img[..., 2], img[..., 1], img[..., 0]
            r = {"nuke_log": log, "out_size": [img.shape[1], img.shape[0]]}
            r["size_ok"] = (img.shape[1], img.shape[0]) == (nw, nh)
            if filt == "Impulse":
                # nearest neighbour: Nuke picks the source pixel containing the sample;
                # compare against round() of the upstream position
                ex, ey = np.floor(mx + 0.5), np.floor(my + 0.5)
            else:
                ex, ey = mx, my
            dx, dy = nx - ex, ny - ey
            r["x_err_interior"] = stats(dx, interior)
            r["y_err_interior"] = stats(dy, interior)
            r["x_err_edge"] = stats(dx, edge)
            r["y_err_edge"] = stats(dy, edge)
            r["mean_signed_dx_interior"] = float(dx[interior].mean())
            r["mean_signed_dy_interior"] = float(dy[interior].mean())
            # y flip detector: correlation of Nuke y vs upstream y
            r["corr_y"] = float(np.corrcoef(ny[interior].ravel(), my[interior].ravel())[0, 1])
            outside = ~valid
            r["outside_source_value_max"] = float(np.abs(img[outside][:, :3]).max()) if outside.any() else None
            r["outside_source_valid_flag_mean"] = float(nb[outside].mean()) if outside.any() else None
            res["nuke"][f"{norm}/{filt}"] = r

    # ---- 2. image test vs upstream images_undistorted ---------------------------
    scene_dir = meta["scene_dir"]
    und_dir = os.path.join(scene_dir, "undistort", "images_undistorted")
    files = sorted(glob.glob(os.path.join(und_dir, "frame_*.jpg")))
    if a.frames:
        files = files[:: max(1, len(files) // a.frames)]
    s, t = sc.to_stmap(mx, my, cam.w, cam.h, "center")
    st_center = os.path.join(a.work, "proxy_undistort_center.exr")
    s, t = sc.read_stmap_exr(st_center)  # use the file actually delivered
    acc = {"stmap_vs_disk": [], "upstream_mem_vs_disk": [], "stmap_vs_upstream_mem": [],
           "wminus1_vs_upstream_mem": []}
    s_w, t_w = sc.to_stmap(mx, my, cam.w, cam.h, "wminus1")
    for und in files:
        name = os.path.basename(und)
        src = cv2.imread(os.path.join(scene_dir, "images", name))
        disk = cv2.imread(und).astype(np.float32)
        mem = cv2.remap(src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT).astype(np.float32)
        via = sc.apply_stmap(src, s, t, "center").astype(np.float32)
        via_w = sc.apply_stmap(src, s_w, t_w, "wminus1").astype(np.float32)
        acc["stmap_vs_disk"].append(np.abs(via - disk).max(axis=2))
        acc["upstream_mem_vs_disk"].append(np.abs(mem - disk).max(axis=2))
        acc["stmap_vs_upstream_mem"].append(np.abs(via - mem).max(axis=2))
        acc["wminus1_vs_upstream_mem"].append(np.abs(via_w - mem).max(axis=2))
    res["image_test"] = {"frames": len(files), "units": "8-bit code values, max over BGR"}
    for k, v in acc.items():
        arr = np.stack(v)
        res["image_test"][k] = {"all": stats(arr), "interior": stats(arr[:, interior]),
                                "edge_band": stats(arr[:, edge]), "outside_source": stats(arr[:, ~valid])}
    # visual evidence for the report
    diff = (np.clip(acc["stmap_vs_disk"][0] * 10, 0, 255)).astype(np.uint8)
    cv2.imwrite(os.path.join(a.work, "diff_x10_stmap_vs_disk_first.png"), diff)

    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1)[:6000])


if __name__ == "__main__":
    main()

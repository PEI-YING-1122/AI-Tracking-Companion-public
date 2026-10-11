"""TEST 02B/02C -- full-resolution STMaps and round trip.

    python test_02c_roundtrip.py --meta META --stmap-dir DIR --work DIR --out result.json

Uses the delivered full-res EXR STMaps (as Nuke would) and checks:
  * geometric round trip  p -> redistort -> undistort -> p'   (pure coordinates)
  * Nuke round trip of a coordinate ramp (real Nuke, Cubic filter)
  * image round trip of the real full-res plate frame (OpenCV linear, Nuke convention)
Regions: centre (inner 50% of each axis), edge band (outer 5%), all.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "stmap"))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import stmap_core as sc  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from companion_meta import find_ffprobe  # noqa: E402
from test_02a_proxy import NUKE, NUKE_RENDER, ramp, stats  # noqa: E402


def regions(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    centre = (np.abs(xx - (w - 1) / 2) <= w / 4) & (np.abs(yy - (h - 1) / 2) <= h / 4)
    bw, bh = max(1, int(round(w * 0.05))), max(1, int(round(h * 0.05)))
    edge = (xx < bw) | (xx >= w - bw) | (yy < bh) | (yy >= h - bh)
    return {"centre": centre, "edge_band_5pct": edge, "all": np.ones_like(centre)}


def extract_frame(video, n, out):
    ffmpeg = os.path.join(os.path.dirname(find_ffprobe()), "ffmpeg.exe")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", video, "-vf", f"select=eq(n\\,{n})", "-vframes", "1", out], check=True)
    return cv2.imread(out)


def nuke(stmap, src, out, filt="Cubic"):
    r = subprocess.run([NUKE, "-t", NUKE_RENDER, stmap, src, out, filt], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
    return cv2.imread(out, cv2.IMREAD_UNCHANGED)


def offset_report(dx, dy, px, py, mask):
    m = mask
    A = np.stack([px[m], np.ones(m.sum())], 1)
    slope_x = np.linalg.lstsq(A, (px + dx)[m], rcond=None)[0][0]
    A = np.stack([py[m], np.ones(m.sum())], 1)
    slope_y = np.linalg.lstsq(A, (py + dy)[m], rcond=None)[0][0]
    return {"mean_dx": float(dx[m].mean()), "mean_dy": float(dy[m].mean()),
            "scale_x": float(slope_x), "scale_y": float(slope_y),
            "corr_y": float(np.corrcoef((py + dy)[m], py[m])[0, 1])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--stmap-dir", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    meta = json.load(open(a.meta))
    scene = meta["scene_name"]
    smeta = json.load(open(os.path.join(a.stmap_dir, f"{scene}_stmap_meta.json")))
    W, H = smeta["full"]["plate"]
    fw, fh = smeta["full"]["canvas"][:2]
    und_p = os.path.join(a.stmap_dir, f"{scene}_full_undistort_stmap.exr")
    red_p = os.path.join(a.stmap_dir, f"{scene}_full_redistort_stmap.exr")
    us, ut = sc.read_stmap_exr(und_p)
    rs, rt = sc.read_stmap_exr(red_p)
    res = {"plate": [W, H], "full_canvas": smeta["full"]["canvas"],
           "proxy_canvas_scaled": smeta["proxy_canvas_scaled_to_full"],
           "file_check": {"undistort_size": [us.shape[1], us.shape[0]], "redistort_size": [rs.shape[1], rs.shape[0]],
                          "dtype": str(us.dtype)}}
    res["file_check"]["sizes_ok"] = (us.shape[1], us.shape[0]) == (fw, fh) and (rs.shape[1], rs.shape[0]) == (W, H)

    # independent re-derivation: delivered undistort map == direct upstream-style map
    cam = sc.Camera(json.load(open(meta["transforms_json"]))).scaled(W, H)
    fcx, fcy = smeta["full"]["canvas"][2:]
    mx, my = sc.undistort_map(cam, fw, fh, fcx, fcy)
    ux, uy = sc.from_stmap(us, ut, W, H)
    res["undistort_file_vs_direct_px"] = {"x": stats(ux - mx), "y": stats(uy - my)}

    reg = regions(W, H)
    px, py = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))

    # ---- geometric round trip (coordinates only) -------------------------------
    qx, qy = sc.from_stmap(rs, rt, fw, fh)            # plate px -> canvas px
    bx = cv2.remap(ux, qx, qy, cv2.INTER_LINEAR)      # canvas px -> plate px
    by = cv2.remap(uy, qx, qy, cv2.INTER_LINEAR)
    dx, dy = bx - px, by - py
    dist = np.hypot(dx, dy)
    res["geometric_roundtrip_px"] = {k: stats(dist, m) for k, m in reg.items()}
    res["geometric_roundtrip_px"]["offset"] = offset_report(dx, dy, px, py, reg["all"])
    # exact undistortPoints residual (no bilinear map lookup): re-distort analytically
    cam_K, cam_D = cam.K, cam.D
    pts = np.stack([qx.ravel(), qy.ravel()], 1).astype(np.float64)
    nK = sc.new_K(cam, fcx, fcy)
    norm = (pts - nK[:2, 2]) / np.array([nK[0, 0], nK[1, 1]])
    proj, _ = cv2.projectPoints(np.hstack([norm, np.ones((len(norm), 1))]).reshape(-1, 1, 3),
                                np.zeros(3), np.zeros(3), cam_K, cam_D)
    proj = proj.reshape(H, W, 2)
    adist = np.hypot(proj[..., 0] - px, proj[..., 1] - py)
    res["analytic_redistort_residual_px"] = {k: stats(adist, m) for k, m in reg.items()}
    # where the residual lives (corners vs. edge mid-points)
    big = adist > 0.5
    res["analytic_redistort_residual_px"]["pixels_over_0.5px"] = int(big.sum())
    if big.any():
        yy, xx = np.nonzero(big)
        res["analytic_redistort_residual_px"]["over_0.5px_min_dist_to_corner_px"] = float(np.min(np.hypot(
            np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy))))
        res["analytic_redistort_residual_px"]["over_0.5px_max_dist_to_corner_px"] = float(np.max(np.hypot(
            np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy))))
    # NOT delivered: same inverse solved to convergence (undistortPointsIter), for comparison only
    gpts = np.stack([px.ravel(), py.ravel()], 1).astype(np.float64).reshape(-1, 1, 2)
    it = cv2.undistortPointsIter(gpts, cam_K, cam_D, None, nK,
                                 (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 200, 1e-12)).reshape(-1, 2)
    nrm = (it - nK[:2, 2]) / np.array([nK[0, 0], nK[1, 1]])
    pj, _ = cv2.projectPoints(np.hstack([nrm, np.ones((len(nrm), 1))]).reshape(-1, 1, 3),
                              np.zeros(3), np.zeros(3), cam_K, cam_D)
    idist = np.hypot(pj.reshape(H, W, 2)[..., 0] - px, pj.reshape(H, W, 2)[..., 1] - py)
    res["alternative_iterative_inverse_residual_px"] = {k: stats(idist, m) for k, m in reg.items()}
    shift = np.hypot(it.reshape(H, W, 2)[..., 0] - qx, it.reshape(H, W, 2)[..., 1] - qy)
    res["alternative_vs_delivered_redistort_px"] = {k: stats(shift, m) for k, m in reg.items()}

    # ---- Nuke round trip of a coordinate ramp ----------------------------------
    ramp_p = os.path.join(a.work, "full_src_ramp.exr")
    cv2.imwrite(ramp_p, ramp(W, H), [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT])
    mid = os.path.join(a.work, "nuke_ramp_undistorted.exr")
    back = os.path.join(a.work, "nuke_ramp_restored.exr")
    m_img = nuke(und_p, ramp_p, mid)
    res["nuke_undistort_out_size"] = [m_img.shape[1], m_img.shape[0]]
    b_img = nuke(red_p, mid, back)
    ndx, ndy = b_img[..., 2] - px, b_img[..., 1] - py
    valid = b_img[..., 0] > 0.999  # B=1 survives only where every tap hit the source
    nd = np.hypot(ndx, ndy)
    res["nuke_roundtrip_px"] = {k: stats(nd, m & valid) for k, m in reg.items()}
    res["nuke_roundtrip_px"]["offset"] = offset_report(ndx, ndy, px, py, reg["centre"] & valid)
    res["nuke_roundtrip_px"]["invalid_pixels"] = int((~valid).sum())

    # ---- image round trip (real plate frame) -----------------------------------
    src = meta["source"]
    imgs = {}
    if src["kind"] == "video":
        for n in (0, (meta["tracking"]["extracted_frames"] or 1) // 2):
            imgs[n] = extract_frame(src["path"], n, os.path.join(a.work, f"plate_full_{n:06d}.png"))
    res["image_roundtrip_8bit"] = {}
    for n, orig in imgs.items():
        und = sc.apply_stmap(orig, us, ut)
        cv2.imwrite(os.path.join(a.work, f"plate_full_{n:06d}_undistorted.png"), und)
        rest = sc.apply_stmap(und, rs, rt)
        cv2.imwrite(os.path.join(a.work, f"plate_full_{n:06d}_restored.png"), rest)
        d = np.abs(rest.astype(np.float32) - orig.astype(np.float32)).max(axis=2)
        res["image_roundtrip_8bit"][str(n)] = {k: stats(d, m) for k, m in reg.items()}
        # controls: same STMaps, (a) Lanczos resampling, (b) low-frequency input (Gaussian sigma 2).
        # If geometry is right, error must collapse when interpolation loss is removed.
        rl = sc.apply_stmap(sc.apply_stmap(orig, us, ut, interp=cv2.INTER_LANCZOS4), rs, rt, interp=cv2.INTER_LANCZOS4)
        dl = np.abs(rl.astype(np.float32) - orig.astype(np.float32)).max(axis=2)
        res["image_roundtrip_8bit"][f"{n}_lanczos"] = {k: stats(dl, m) for k, m in reg.items()}
        soft = cv2.GaussianBlur(orig, (0, 0), 2.0)
        rb = sc.apply_stmap(sc.apply_stmap(soft, us, ut), rs, rt)
        db = np.abs(rb.astype(np.float32) - soft.astype(np.float32)).max(axis=2)
        res["image_roundtrip_8bit"][f"{n}_lowfreq_sigma2"] = {k: stats(db, m) for k, m in reg.items()}
        cv2.imwrite(os.path.join(a.work, f"plate_full_{n:06d}_diff_x10.png"), np.clip(d * 10, 0, 255).astype(np.uint8))

    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1)[:6000])


if __name__ == "__main__":
    main()

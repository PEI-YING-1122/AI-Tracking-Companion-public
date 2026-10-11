"""TEST 03 -- Nuke package builder: build, relocate, open in Nuke, QC.

    python tests/test_03_nuke_package.py --meta META --out result.json

Steps
  1. build package (demo shot) under <test data>/poc/packages
  2. .nk path audit (no drive letters / workstation paths)
  3. open + render taps in Nuke at the build location
  4. copy the package to another drive (C: scratch), rename its parent, open + render again
  5. QC statistics (code values 0-255 from raw renders; sub-pixel shift by phase correlation)
  6. frame handling on a synthetic sequence numbered 1001+ (offset Reads)
  7. Unsupported scene -> exit 2, no package
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "nuke_package"))
sys.path.insert(0, os.path.join(ROOT, "stmap"))
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, HERE)
import test_paths as tp  # noqa: E402
import build_nuke_package as bnp  # noqa: E402
import stmap_core as sc  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import companion_meta as cm  # noqa: E402
from test_02a_proxy import stats  # noqa: E402
from test_meta_and_unsupported import make_scene, make_seq  # noqa: E402

NUKE = bnp.NUKE
VALIDATE = os.path.join(ROOT, "nuke_package", "validate_nuke_package.py")
SCRATCH = os.environ.get("COMPANION_RELOCATE_ROOT") or os.path.join(tempfile.gettempdir(), "ai_tracking_companion_relocate")


def nuke_validate(nk, out_dir, frames, raw=True):
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    r = subprocess.run([NUKE, "-t", VALIDATE, nk, out_dir, "frames=" + ",".join(map(str, frames))] + (["raw"] if raw else []),
                       capture_output=True, text=True, timeout=1800)
    p = os.path.join(out_dir, "validate.json")
    if r.returncode != 0 or not os.path.exists(p):
        raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])
    return json.load(open(p))


def load(out_dir, tap, f):
    img = cv2.imread(os.path.join(out_dir, f"{tap}.{f:04d}.exr"), cv2.IMREAD_UNCHANGED)
    return img[..., :3][..., ::-1].astype(np.float64) * 255.0  # RGB code values


def gray(a):
    return a.mean(axis=2).astype(np.float32)


def shift(a, b, mask):
    """sub-pixel translation b->a on the masked region (phase correlation, Hann window)"""
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    A, B = gray(a)[y0:y1, x0:x1], gray(b)[y0:y1, x0:x1]
    win = cv2.createHanningWindow((A.shape[1], A.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(B, A, win)
    return {"dx_px": float(dx), "dy_px_image_down": float(dy), "response": float(resp)}


def valid_from_stmap(path, src_w, src_h, erode=3):
    s, t = sc.read_stmap_exr(path)
    x, y = sc.from_stmap(s, t, src_w, src_h)
    v = (x >= 0) & (x <= src_w - 1) & (y >= 0) & (y <= src_h - 1)
    k = np.ones((2 * erode + 1, 2 * erode + 1), np.uint8)
    inner = cv2.erode(v.astype(np.uint8), k).astype(bool)
    return v, inner


def regions(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    centre = (np.abs(xx - (w - 1) / 2) <= w / 4) & (np.abs(yy - (h - 1) / 2) <= h / 4)
    bw, bh = max(1, round(w * 0.05)), max(1, round(h * 0.05))
    edge = (xx < bw) | (xx >= w - bw) | (yy < bh) | (yy >= h - bh)
    return centre, edge


def audit_nk(nk):
    text = open(nk, encoding="utf-8").read()
    pats = {"drive_letter": r"(?i)(?<![A-Za-z])[A-Z]:[\\/]", "ai_tracking": r"(?i)AI_Tracking",
            "unc": r"\\\\[A-Za-z0-9]", "users_dir": r"(?i)[\\/]Users[\\/]"}
    hits = {k: [l.strip() for l in text.splitlines() if re.search(p, l)] for k, p in pats.items()}
    files = re.findall(r"^\s*file\s+(\S+)", text, re.M)
    return {"hits": hits, "file_knobs": files, "all_relative": all(f.startswith("..") for f in files),
            "project_directory": re.findall(r"project_directory\s+(.+)", text)}


def black_corner_pixels(redist, plate):
    """invalid mapping: output exactly 0 in every channel (= sampled outside the Crop
    black-outside box) while the plate is not black.  Keys filter overshoot on dark
    content gives small non-zero/negative values and is NOT counted."""
    blk = (np.abs(redist).max(axis=2) == 0.0) & (np.abs(plate).max(axis=2) > 0.0)
    yy, xx = np.nonzero(blk)
    H, W = blk.shape
    return {"count": int(blk.sum()),
            "max_dist_from_corner_px": float(np.max(np.hypot(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy)))) if len(xx) else None}


def qc_raw(out_dir, frames, pkg):
    """raw pass: 8-bit sources as code values (0-255)"""
    lj = json.load(open(glob.glob(os.path.join(pkg, "metadata", "*_lens.json"))[0]))
    SW, SH = lj["source"]["resolution"]
    PW, PH = lj["tracking"]["proxy_resolution"]
    und_p = os.path.join(pkg, "lens", lj["stmap"]["undistort"]["file"].split("/")[-1])
    v_full, in_full = valid_from_stmap(und_p, SW, SH)
    v_prox, in_prox = valid_from_stmap(os.path.join(pkg, "lens", lj["stmap"]["proxy_undistort_qc"]["file"].split("/")[-1]), PW, PH)
    c_plate, e_plate = regions(SW, SH)
    res = {}
    for f in frames:
        r = {}
        d = load(out_dir, "QC_DIFFERENCE_PROXY", f).max(axis=2)
        r["QC1A_tracking_reference_vs_proxy_stmap"] = {
            "interior": stats(d, in_prox), "outside_source": stats(d, ~v_prox),
            "shift": shift(load(out_dir, "APPLY_UNDISTORT_PROXY_QC", f), load(out_dir, "TRACKING_REFERENCE_FLATTEN", f), in_prox)}
        d = load(out_dir, "QC_TRACKING_REF_ALIGNMENT", f).max(axis=2)
        ref = load(out_dir, "TRACKING_REF_CROP_TO_CANVAS", f)
        both = in_full & (ref.max(axis=2) > 0)
        r["QC1B_tracking_reference_in_production_space"] = {
            "interior": stats(d, both),
            "shift": shift(load(out_dir, "UNDISTORT_LIVE", f), ref, both)}
        plate = load(out_dir, "READ_ORIGINAL_PLATE", f)
        rq = load(out_dir, "APPLY_REDISTORT_QC", f)
        d = load(out_dir, "QC_ROUNDTRIP_DIFFERENCE", f).max(axis=2)
        r["QC2_roundtrip"] = {"centre": stats(d, c_plate), "edge_band_5pct": stats(d, e_plate), "all": stats(d),
                              "shift": shift(rq, plate, np.ones((SH, SW), bool)),
                              "black_corner_pixels": black_corner_pixels(rq, plate)}
        # Nuke undistort vs Companion maths on the same decoded plate (Nuke Keys vs OpenCV linear)
        s_, t_ = sc.read_stmap_exr(und_p)
        mine = sc.apply_stmap(plate.astype(np.float32), s_, t_)
        d = np.abs(load(out_dir, "UNDISTORT_LIVE", f) - mine).max(axis=2)
        r["nuke_undistort_vs_companion_opencv"] = {"interior": stats(d, in_full),
                                                   "shift": shift(load(out_dir, "UNDISTORT_LIVE", f), mine.astype(np.float64), in_full)}
        res[str(f)] = r
    return res


def qc_linear(out_dir, frames, pkg):
    """default-colourspace pass (as a compositor sees it): linear float x 255"""
    lj = json.load(open(glob.glob(os.path.join(pkg, "metadata", "*_lens.json"))[0]))
    SW, SH = lj["source"]["resolution"]
    v_full, in_full = valid_from_stmap(os.path.join(pkg, "lens", lj["stmap"]["undistort"]["file"].split("/")[-1]), SW, SH)
    res = {}
    for f in frames:
        live = load(out_dir, "UNDISTORT_LIVE", f)
        pf = load(out_dir, "PRODUCTION_FLATTEN", f)
        d = load(out_dir, "QC_DIFFERENCE", f).max(axis=2)
        rel = np.abs(pf - live) / np.maximum(np.abs(live), 1e-3)
        res[str(f)] = {
            "QC1_production_flatten_vs_live_stmap": {"all": stats(d), "interior": stats(d, in_full),
                                                     "max_relative": float(rel[in_full].max()),
                                                     "shift": shift(live, pf, in_full)},
            "comp_input_equals_production_flatten_max": float(np.abs(load(out_dir, "COMP_INPUT", f) - pf).max()),
            "delivery_equals_qc_roundtrip_max": float(np.abs(load(out_dir, "APPLY_REDISTORT", f)
                                                             - load(out_dir, "APPLY_REDISTORT_QC", f)).max()),
            "delivery_black_corner_pixels": black_corner_pixels(load(out_dir, "APPLY_REDISTORT", f),
                                                                load(out_dir, "READ_ORIGINAL_PLATE", f)),
            "production_flatten_size": list(pf.shape[1::-1]),
        }
    return res


def compare_dirs(a, b, taps, frames):
    out = {}
    for t in taps:
        for f in frames:
            pa, pb = os.path.join(a, f"{t}.{f:04d}.exr"), os.path.join(b, f"{t}.{f:04d}.exr")
            if os.path.exists(pa) and os.path.exists(pb):
                out[f"{t}.{f}"] = float(np.abs(cv2.imread(pa, cv2.IMREAD_UNCHANGED).astype(np.float64)
                                               - cv2.imread(pb, cv2.IMREAD_UNCHANGED).astype(np.float64)).max())
    return out


def seq_fixture(work):
    """JPG plate shot.1001-1010, tracking frames 2..9 registered, offset 1000"""
    demo = tp.poc("walking-forest", "12588331_720_1280_24fps")
    b = os.path.join(work, "seq_fixture")
    if os.path.exists(b):
        shutil.rmtree(b)
    make_seq(os.path.join(b, "src", "shotseq"), [f"shotseq.{n}.jpg" for n in range(1001, 1011)], w=360, h=640)
    scene = make_scene(b, demo, 10, range(2, 10))
    fl = os.path.join(scene, "undistort", "images_undistorted")
    os.makedirs(fl, exist_ok=True)
    for k in range(2, 10):  # registered frames only, like upstream
        cv2.imwrite(os.path.join(fl, f"frame_{k:06d}.jpg"), np.full((838, 472, 3), 20 * k, np.uint8))
    meta = cm.build_meta(scene, os.path.join(b, "src", "shotseq"))
    mp = os.path.join(b, "meta.json")
    json.dump(meta, open(mp, "w"), indent=1)
    res = bnp.build(mp, os.path.join(b, "packages"))
    v = nuke_validate(res["nk"], os.path.join(b, "nuke_validate"), [1001, 1002, 1009, 1010], raw=True)
    # unregistered tracking frames (1 and 10) must render black, not hold a neighbour
    means = {f: float(cv2.imread(os.path.join(b, "nuke_validate", f"TRACKING_REFERENCE_FLATTEN.{f:04d}.exr"),
                                 cv2.IMREAD_UNCHANGED)[..., :3].mean() * 255) for f in (1001, 1002, 1009, 1010)}
    expected = {1001: 0.0, 1002: 40.0, 1009: 180.0, 1010: 0.0}
    return {"meta_tracking": {k: meta["tracking"][k] for k in ("tracking_first_frame", "tracking_last_frame",
                                                               "frame_offset_tracking_to_source")},
            "meta_source": {k: meta["source"][k] for k in ("source_first_frame", "source_last_frame", "fps", "fps_source")},
            "root": v["root"], "plate_frame_map": v["plate_frame_map"], "flatten_frame_map": v["flatten_frame_map"],
            "plate_read": {k: v["nodes"]["READ_ORIGINAL_PLATE"][k] for k in ("file_raw", "first", "last")},
            "flatten_read": {k: v["nodes"]["TRACKING_REFERENCE_FLATTEN"][k] for k in ("file_raw", "first", "last", "frame_mode", "frame", "on_error")},
            "lens_json_fps_source": json.load(open(res["lens_json"]))["source"]["fps_source"],
            "flatten_render_mean": means, "flatten_render_expected": expected,
            "flatten_render_ok": all(abs(means[k] - v) < 0.5 for k, v in expected.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--maya-dir", help="production Maya export to include in the package")
    a = ap.parse_args()
    work = tp.poc("work_03")
    os.makedirs(work, exist_ok=True)
    res = {}

    built = bnp.build(a.meta, tp.poc("packages"), maya_dir=a.maya_dir)
    pkg, nk = built["package"], built["nk"]
    nk_sha = hashlib.sha256(open(nk, "rb").read()).hexdigest()
    res["package"] = {"root": pkg, "files": sorted(os.path.relpath(p, pkg).replace("\\", "/")
                                                   for p in glob.glob(os.path.join(pkg, "**", "*"), recursive=True)
                                                   if os.path.isfile(p) and "frame_0" not in p),
                      "reference_frames": {d: len(os.listdir(os.path.join(pkg, "reference", d))) for d in ("tracking_flatten", "tracking_proxy")},
                      "lens_json": json.load(open(built["lens_json"]))}
    res["package"]["lens_json"].pop("_nuke", None)
    res["nk_audit"] = audit_nk(nk)

    frames = [1, 168, 337]
    v1 = nuke_validate(nk, os.path.join(work, "orig"), frames)               # raw pass
    nuke_validate(nk, os.path.join(work, "orig_linear"), frames, raw=False)  # compositor view
    res["nuke_structure"] = {k: v1[k] for k in ("root", "missing_required", "backdrops", "production_path",
                                                "production_path_has_difference", "production_path_has_qc",
                                                "offset_probe", "flatten_frame_map", "plate_frame_map", "nk_sha256_unchanged")}
    res["nuke_structure"]["nodes"] = {k: {kk: vv for kk, vv in v.items() if kk != "file_eval"} for k, v in v1["nodes"].items()}
    res["nuke_structure"]["read_errors"] = [k for k, v in v1["nodes"].items() if v.get("error") is True]
    res["qc_raw"] = qc_raw(os.path.join(work, "orig"), frames, pkg)
    res["qc_linear"] = qc_linear(os.path.join(work, "orig_linear"), frames, pkg)

    # relocation: different drive, different parent name
    dst_parent = os.path.join(SCRATCH, "moved_delivery_X")
    if os.path.exists(SCRATCH):
        shutil.rmtree(SCRATCH)
    shutil.copytree(pkg, os.path.join(dst_parent, os.path.basename(pkg)))
    nk2 = os.path.join(dst_parent, os.path.basename(pkg), "nuke", os.path.basename(nk))
    v2 = nuke_validate(nk2, os.path.join(SCRATCH, "validate"), [168])
    res["relocation"] = {"target": nk2, "drive": os.path.splitdrive(nk2)[0],
                         "project_directory_eval": v2["root"]["project_directory_eval"],
                         "read_errors": [k for k, v in v2["nodes"].items() if v.get("error") is True],
                         "reads_resolve_inside_new_location": all(
                             os.path.splitdrive(v.get("file_eval", nk2))[0].lower() == os.path.splitdrive(nk2)[0].lower()
                             for v in v2["nodes"].values() if v["class"] == "Read"),
                         "render_max_abs_diff_vs_original_location": compare_dirs(
                             os.path.join(work, "orig"), os.path.join(SCRATCH, "validate"),
                             ["UNDISTORT_LIVE", "PRODUCTION_FLATTEN", "APPLY_REDISTORT", "QC_DIFFERENCE",
                              "QC_ROUNDTRIP_DIFFERENCE", "QC_DIFFERENCE_PROXY", "QC_TRACKING_REF_ALIGNMENT"], [168])}

    res["sequence_fixture"] = seq_fixture(work)

    # Unsupported
    fx = tp.poc("fixtures", "fisheye", "meta.json")
    out_root = os.path.join(work, "unsupported_pkg")
    if os.path.exists(out_root):
        shutil.rmtree(out_root)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "nuke_package", "build_nuke_package.py"), "--meta", fx,
                        "--out-root", out_root], capture_output=True, text=True)
    res["unsupported_fisheye"] = {"rc": r.returncode, "msg": (r.stdout + r.stderr).strip()[-300:],
                                  "package_created": os.path.exists(out_root)}
    res["nk_unchanged_after_all_validation"] = hashlib.sha256(open(nk, "rb").read()).hexdigest() == nk_sha
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("nk_audit", "relocation", "unsupported_fisheye", "nk_unchanged_after_all_validation")}, indent=1, default=str))


if __name__ == "__main__":
    main()

"""Per-shot regression smoke for companion_run.py (re-uses validated maths, no new research).

Checks (each only when the asset exists in this run)
  canvas   delivered redistort STMap: plate samples outside the production canvas (must be 0)
  maya     headless Maya projection of the production camera (ABC primary, FBX+sidecar fallback)
           vs pinhole truth on the production canvas (< 0.01 px); gate aspect; frame range
  points   Houdini readback of the point cloud Alembic (count / P exact)
  flatten  reference mode: AI Tracking flatten frames present + canvas compatibility
           render mode: production flatten frame count
  nuke     setup opens; no Read error / missing file; no QC node; exact-zero
           (invalid-mapping) pixels after redistort at first/mid/last frame (must be 0)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for sub in ("common", "stmap"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.path.insert(0, HERE)
import site_config  # noqa: E402
import stmap_core as sc  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from test_01_validate import truth_pixels, maya_pixels_explicit, errstats, fnum, in_frame  # noqa: E402

MAYA_TOL_PX = 0.01


def _remapped(R, path, name):
    """Stage validation: a copy of a delivery file with final paths mapped to the stage.
    The delivered file itself (final paths) is never changed."""
    rm = R.get("validate_remap")
    if not rm:
        return path
    txt = open(path, encoding="utf-8").read()
    for a, b in rm["pairs"]:
        txt = txt.replace(a, b)
    os.makedirs(rm["dir"], exist_ok=True)
    out = os.path.join(rm["dir"], name)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    return out


def _corner_zero(img, plate, k=16):
    """exact-zero pixels in the four k x k corners where the plate is not black"""
    h, w = img.shape[:2]
    z = (np.abs(img[..., :3]).max(axis=2) == 0) & (np.abs(plate[..., :3]).max(axis=2) > 0)
    return int(z[:k, :k].sum() + z[:k, w - k:].sum() + z[h - k:, :k].sum() + z[h - k:, w - k:].sum())


def _nuke(R, plate, out_dir, smeta, meta):
    P = R["planned"]
    W, H = smeta["full"]["canvas"][:2]
    f1, f2 = plate[1], plate[2]
    frames = sorted({f1, (f1 + f2) // 2, f2})
    nd = os.path.join(out_dir, "nuke")
    nk = _remapped(R, P["nuke_setup"], os.path.basename(P["nuke_setup"]).replace(".nk", ".validate.nk"))
    r = subprocess.run([site_config.get("nuke"), "-t", os.path.join(ROOT, "nuke_package", "check_nuke_setup.py"),
                        nk, nd, "frames=" + ",".join(map(str, frames))], capture_output=True, text=True)
    chk = json.load(open(os.path.join(nd, "check.json"))) if os.path.exists(os.path.join(nd, "check.json")) else {}
    imgs = {}
    stats_ = {}
    for f in frames:
        for t in ("PLATE", "UNDISTORT", "REFERENCE", "REDISTORT", "ROUNDTRIP"):
            fp_ = os.path.join(nd, f"{t}.{f:04d}.exr")
            imgs[(t, f)] = cv2.imread(fp_, cv2.IMREAD_UNCHANGED) if os.path.exists(fp_) else None
        if imgs[("REFERENCE", f)] is None:   # flatten_mode none: no reference node
            imgs[("REFERENCE", f)] = imgs[("UNDISTORT", f)]
        pl, rt, ex = imgs[("PLATE", f)], imgs[("ROUNDTRIP", f)], imgs[("REDISTORT", f)]
        stats_[f] = {
            "roundtrip_invalid_exact_zero": int(((np.abs(rt[..., :3]).max(axis=2) == 0) & (np.abs(pl[..., :3]).max(axis=2) > 0)).sum()),
            "roundtrip_corner_zero": _corner_zero(rt, pl),
            "example_redistort_corner_zero": _corner_zero(ex, pl),
            "sizes": {t: list(imgs[(t, f)].shape[1::-1]) for t in ("PLATE", "UNDISTORT", "REFERENCE", "REDISTORT")},
            "mean": {t: float(imgs[(t, f)][..., :3].mean()) for t in ("PLATE", "UNDISTORT", "REFERENCE", "REDISTORT")},
        }
    for f in os.listdir(nd) if os.path.isdir(nd) else []:
        if f.endswith(".exr"):  # temporary 32-bit renders: measured above, not kept
            os.remove(os.path.join(nd, f))
    nodes = chk.get("nodes", {})
    reads = {k: {kk: v.get(kk) for kk in ("file", "raw", "first", "last", "frame_mode", "frame", "on_error", "files_at", "file_exists_at")}
             for k, v in nodes.items() if v["class"] == "Read"}
    has_ref = R["options"]["flatten_mode"] != "none"
    expected_nodes = {"BD_SOURCE", "BD_UNDISTORT", "BD_REDISTORT", "LENS_INFO", "READ_ORIGINAL_PLATE", "CROP_BLACK_OUTSIDE",
                      "READ_STMAP_UNDISTORT", "APPLY_UNDISTORT", "READ_STMAP_REDISTORT", "APPLY_REDISTORT"}
    if has_ref:
        expected_nodes |= {"TRACKING_REFERENCE_FLATTEN", "BD_TRACKING_REFERENCE"}
    consumers_of_ref = sorted(k for k, v in nodes.items() if "TRACKING_REFERENCE_FLATTEN" in (v.get("inputs") or []))
    off = meta["tracking"]["frame_offset_tracking_to_source"] or 0
    ref_files = reads.get("TRACKING_REFERENCE_FLATTEN", {}).get("files_at", {})
    res = {"rc": r.returncode, "root": chk.get("root"), "nodes": sorted(nodes), "read_errors": chk.get("read_errors"),
           "clutter": chk.get("clutter"), "reads": reads, "undistort_format": chk.get("undistort_format"),
           "redistort_format": chk.get("redistort_format"), "renders": stats_, "nk_unchanged": chk.get("nk_unchanged"),
           "crop": {k: nodes.get("CROP_BLACK_OUTSIDE", {}).get(k) for k in ("inputs",)},
           "apply_undistort_inputs": nodes.get("APPLY_UNDISTORT", {}).get("inputs"),
           "apply_redistort_inputs": nodes.get("APPLY_REDISTORT", {}).get("inputs"),
           "apply_redistort_label": nodes.get("APPLY_REDISTORT", {}).get("label"),
           "tracking_reference_label": nodes.get("TRACKING_REFERENCE_FLATTEN", {}).get("label")}
    checks = {
        "nuke_opens_clean": r.returncode == 0 and chk.get("read_errors") == []
                            and all(all(v.get("file_exists_at", {}).values()) for k, v in reads.items() if k != "TRACKING_REFERENCE_FLATTEN"),
        "nuke_graph_exact": set(nodes) == expected_nodes,
        "nuke_no_clutter": chk.get("clutter") == [],
        "nuke_root": [chk.get("root", {}).get("first"), chk.get("root", {}).get("last")] == [f1, f2]
                     and abs(chk.get("root", {}).get("fps", 0) - meta["source"]["fps"]) < 1e-6,
        "nuke_formats": res["undistort_format"] == [W, H] and res["redistort_format"] == smeta["full"]["plate"],
        "nuke_stmaps_raw": reads.get("READ_STMAP_UNDISTORT", {}).get("raw") and reads.get("READ_STMAP_REDISTORT", {}).get("raw"),
        "nuke_undistort_path": res["apply_undistort_inputs"] == ["CROP_BLACK_OUTSIDE", "READ_STMAP_UNDISTORT"]
                               and res["crop"]["inputs"] == ["READ_ORIGINAL_PLATE"],
        # v0.2.1 TEST2 (Artist reference topology): tracking reference -> APPLY_REDISTORT <- redistort STMap.
        # No reference: the earlier example input APPLY_UNDISTORT (no-reference case not redesigned yet)
        "nuke_redistort_example": res["apply_redistort_inputs"] == [("TRACKING_REFERENCE_FLATTEN" if has_ref
                                                                     else "APPLY_UNDISTORT"), "READ_STMAP_REDISTORT"],
        "nuke_reference_feeds_redistort_only": consumers_of_ref == (["APPLY_REDISTORT"] if has_ref else []),
        "nuke_reference_frame_map": (not has_ref) or all(
            ref_files.get(str(f), ref_files.get(f)) == os.path.basename(R["inputs"]["tracking_flatten_pattern"] % (f - off)
                                                                        if R["options"]["flatten_mode"] == "reference_ai_tracking"
                                                                        else R["outputs"]["production_flatten"] % f)
            for f in frames),
        "nuke_no_corner_black": all(v["roundtrip_invalid_exact_zero"] == 0 and v["example_redistort_corner_zero"] == 0
                                    for v in stats_.values()),
        "nuke_renders_nonblack": all(min(v["mean"].values()) > 0 for v in stats_.values()),
    }
    return res, checks


def _maya_loader(R, out_dir, maya_stage):
    P = R["planned"]
    out = os.path.join(out_dir, "maya_loader_check.json")
    cmd = [site_config.get("mayapy"), os.path.join(HERE, "maya_loader_check.py"), P["maya_loader"],
           os.path.join(maya_stage, "houdini_reference_corrected.json"), out]
    if R.get("validate_remap"):  # the delivered loader, reading a stage-remapped metadata copy
        cmd.append(_remapped(R, P["metadata"], os.path.basename(P["metadata"]).replace(".json", ".validate.json")))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        return {"error": (r.stdout + r.stderr)[-2000:]}, {"maya_loader_runs": False}
    c = json.load(open(out))
    shot = R["shot"]
    sc_ = c["scene"]
    side = json.load(open(P["maya_sidecar"]))
    pc = c["pointcloud"]
    frames = [k for k in pc if k.isdigit()]
    checks = {
        "maya_loader_runs": True,
        "maya_loader_fps_timeline": sc_["time_unit"] == side["maya_time_unit"]
                                    and sc_["timeline"] == [side["frame_start"], side["frame_end"]],
        "maya_loader_resolution": sc_["resolution"] == side["resolution"],
        "maya_loader_hierarchy": sorted(c["hierarchy"]["children"]) == sorted([f"{shot}_CAM", f"{shot}_POINTCLOUD"])
                                 and c["hierarchy"]["camera_shapes"] == [f"{shot}_CAMShape"]
                                 and (R["options"]["flatten_mode"] == "none" or (
                                     bool(c.get("image_plane"))
                                     and c["image_plane"]["full_path"].startswith(f"|AI_TRACKING_GRP|{shot}_CAM|{shot}_CAMShape->")
                                     and c["image_plane"]["full_path"].split("|")[-2].endswith(f"{shot}_IMAGEPLANE"))),
        "maya_loader_camera": c["camera"]["world_matrix_max_abs_diff_vs_houdini"] < 1e-6
                              and abs(c["camera"]["gate_aspect"] - side["resolution"][0] / side["resolution"][1]) < 1e-9
                              and max(abs(v) for v in c["camera"]["film_offset_diff"]) < 1e-9,
        "maya_loader_image_plane": (R["options"]["flatten_mode"] == "none" and not c.get("image_plane")) or (
            bool(c.get("image_plane")) and all(v["exists"] for v in c["image_plane"]["mapping"].values())),
        "maya_points_count": all(pc[f]["count"] == pc["npz_count"] for f in frames),
        "maya_points_positions": all(pc[f]["max_abs_pos_diff"] is not None and pc[f]["max_abs_pos_diff"] < 1e-6
                                     and pc[f]["transform_is_identity"] for f in frames),
        "maya_points_colors": pc.get("color_count") == pc["npz_count"] and pc.get("max_abs_color_diff", 1) < 1e-6,
        "maya_points_native_single": pc["type"] == "particle" and c["new_dag_count"] <= 12,
    }
    return c, checks


def verify(meta, smeta, R, plate, out_dir, maya_stage):
    os.makedirs(out_dir, exist_ok=True)
    P = R["planned"]
    W, H, ccx, ccy = smeta["full"]["canvas"]
    res, checks = {}, {}

    # canvas coverage from the delivered file
    if os.path.exists(P["lens_redistort"]):
        s, t = sc.read_stmap_exr(P["lens_redistort"])
        qx, qy = sc.from_stmap(s, t, W, H)
        outside = (qx < -0.5) | (qx > W - 0.5) | (qy < -0.5) | (qy > H - 0.5)
        res["canvas"] = {"production_canvas": [W, H, ccx, ccy], "plate": smeta["full"]["plate"],
                         "plate_samples_outside_canvas": int(outside.sum())}
        checks["canvas_no_outside"] = res["canvas"]["plate_samples_outside_canvas"] == 0

    # maya
    tr = meta["tracking"]
    off = tr["frame_offset_tracking_to_source"] or 0
    if os.path.exists(P["maya_sidecar"]):
        uj = json.load(open(R["inputs"]["transforms_undistorted_json"]))
        fc = smeta["full"]["camera"]
        Kp = np.array([[fc["fl_x"], 0, ccx], [0, fc["fl_y"], ccy], [0, 0, 1]])
        c2w = {fnum(f["file_path"]): f["transform_matrix"] for f in uj["frames"]}
        ref = json.load(open(os.path.join(maya_stage, "houdini_reference_corrected.json")))
        dump = json.load(open(os.path.join(maya_stage, "maya_dump_corrected.json")))
        side = json.load(open(P["maya_sidecar"]))
        Xh = np.asarray(ref["points_sample"])
        res["maya"] = {"sidecar_resolution": side["resolution"], "frames": [side["frame_start"], side["frame_end"]],
                       "fps": side["fps"], "fps_source": side["fps_source"], "maya_time_unit": side["maya_time_unit"]}
        for kind in ("abc", "fbx"):
            d = dump.get(kind)
            if d is None:
                res["maya"][kind] = {"error": "camera not found in Maya"}
                continue
            mf = {int(round(fr["frame"])): fr["world"] for fr in d["frames"]}
            err = []
            for fr in ref["frames"]:
                f = int(round(fr["frame"]))
                tt, z = truth_pixels(c2w[f - ref["frame_offset"]], Kp, Xh)
                ok = in_frame(tt, z, W, H)
                if f in mf:
                    err.append((maya_pixels_explicit(mf[f], d["lens"], W, H, Xh) - tt)[ok])
            L = d["lens"]
            res["maya"][kind] = {"vs_truth": errstats(np.vstack(err)), "frames_checked": len(err),
                                 "gate_aspect": L["horizontalFilmAperture"] / L["verticalFilmAperture"],
                                 "key_range": d.get("key_range")}
        ab = res["maya"].get("abc", {}).get("vs_truth", {})
        fb = res["maya"].get("fbx", {}).get("vs_truth", {})
        checks["maya_abc_projection"] = ab.get("max_px", 1e9) < MAYA_TOL_PX
        checks["maya_fbx_projection"] = fb.get("max_px", 1e9) < MAYA_TOL_PX
        checks["maya_gate"] = abs(res["maya"].get("abc", {}).get("gate_aspect", 0) - W / H) < 1e-9 and side["resolution"] == [W, H]
        checks["maya_frame_range"] = res["maya"]["frames"] == [tr["tracking_first_frame"] + off, tr["tracking_last_frame"] + off]
        res["points"] = ref.get("points_readback")
        npz = (res["points"] or {}).get("npz") or {}
        checks["points_npz_exact"] = npz.get("count") == (res["points"] or {}).get("src_count") \
            and npz.get("max_abs_P_diff") == 0.0 and npz.get("max_abs_Cd_diff") in (0.0, None)

    # flatten
    mode = R["options"]["flatten_mode"]
    if mode == "reference_ai_tracking":
        pat = R["inputs"]["tracking_flatten_pattern"]
        n = sum(os.path.exists(pat % k) for k in range(tr["tracking_first_frame"], tr["tracking_last_frame"] + 1))
        res["flatten"] = {"mode": mode, "pattern": pat, "frames_found": n, "frames_expected": tr["registered_frames"]}
        checks["flatten_frames"] = n == tr["registered_frames"]
    elif mode == "render":
        pf = R["outputs"]["production_flatten"]
        n = sum(os.path.exists(pf % f) for f in range(plate[1], plate[2] + 1))
        res["flatten"] = {"mode": mode, "pattern": pf, "frames_found": n, "frames_expected": plate[2] - plate[1] + 1}
        checks["flatten_frames"] = n == plate[2] - plate[1] + 1

    # maya loader (the Artist entry point), run for real in headless Maya
    if os.path.exists(P.get("maya_loader", "")):
        res["maya_loader"], lchk = _maya_loader(R, out_dir, maya_stage)
        checks.update(lchk)

    # nuke
    if os.path.exists(P["nuke_setup"]):
        res["nuke"], nchk = _nuke(R, plate, out_dir, smeta, meta)
        checks.update(nchk)

    res["summary"] = {"pass": bool(checks) and all(checks.values()), "checks": checks,
                      "maya_abc_max_px": res.get("maya", {}).get("abc", {}).get("vs_truth", {}).get("max_px"),
                      "maya_fbx_max_px": res.get("maya", {}).get("fbx", {}).get("vs_truth", {}).get("max_px"),
                      "canvas": [W, H]}
    return res

"""AI Tracking Companion -- production run for one shot.

    python companion_run.py <shot_config.json> [--overwrite] [--dry-run] [--steps ...]

Takes over from a finished AI Tracking output and writes ONLY the Companion's own
production assets into the Artist export (paths from common/path_resolver.py):

    <export>/lens/      <shot>_undistort_stmap.exr  <shot>_redistort_stmap.exr   (32-bit float, DATA)
    <export>/maya/      <shot>_cam_corrected.abc (primary)
                        <shot>_cam_corrected.fbx + <shot>_camera.json (fallback)
                        <shot>_points.npz  (P, Cd -- Maya-native point cloud)
                        <shot>_load_maya.py (Artist entry point)
    <export>/metadata/  <shot>_metadata.json
    <export>/nuke/      <shot>_lens_setup.nk  (lens handoff / example setup, not a comp template)

Plate, AI Tracking flatten and source sequences are referenced at their real
locations, never copied.  Logs / QC / developer files go to work_dir, outside
the export.  The HIP is never saved; AI Tracking is never written to.
"""
import argparse
import fractions
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ("common", "stmap", "maya_export", "nuke_package", "tests"):
    sys.path.insert(0, os.path.join(ROOT, sub))
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import site_config  # noqa: E402
import path_resolver  # noqa: E402
import companion_meta  # noqa: E402

from version import __version__ as COMPANION_VERSION  # noqa: E402
STEPS = ("stmap", "maya", "metadata", "nuke", "flatten", "verify")
DEFAULT_STEPS = ("stmap", "maya", "metadata", "nuke", "flatten", "verify")
PP_TOL = 0.01  # px: AI Tracking flatten counts as production space only within this


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd, logfile):
    env = os.environ.copy()
    for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(k, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with open(logfile, "w", encoding="utf-8", errors="replace") as f:
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env).returncode


def plate_read_path(meta, R):
    """Absolute plate path (video or %0Nd pattern) + first/last frame."""
    src = meta["source"]
    if src["kind"] == "video":
        return src["path"].replace("\\", "/"), src["source_first_frame"], src["source_last_frame"]
    if R["inputs"]["source_plate_pattern"]:
        return R["inputs"]["source_plate_pattern"], src["source_first_frame"], src["source_last_frame"]
    import build_nuke_package as bnp
    exts = (".exr",) if src["kind"] == "exr_sequence" else (".jpg", ".jpeg")
    files = sorted(f for f in glob.glob(os.path.join(src["path"], "*")) if os.path.splitext(f)[1].lower() in exts)
    pat = bnp.seq_pattern(files)
    if pat is None:
        raise SystemExit("UNSUPPORTED: source sequence is not a single padded file pattern")
    return os.path.join(src["path"], pat[0]).replace("\\", "/"), pat[1], pat[2]


def flatten_compatibility(meta, smeta, R):
    """Is the AI Tracking flatten already in the production space (so it can be referenced)?"""
    tr, src = meta["tracking"], meta["source"]
    legacy, prod = smeta["legacy_full_canvas_info_only"], smeta["full"]["canvas"]
    n_flat = len(glob.glob(os.path.join(R["inputs"]["tracking_flatten_dir"], "frame_*.jpg")))
    checks = {
        "tracking_resolution_equals_source": [tr["proxy_width"], tr["proxy_height"]] == [src["width"], src["height"]],
        "canvas_size_equal": legacy[:2] == prod[:2],
        "principal_point_within_tol": abs(legacy[2] - prod[2]) < PP_TOL and abs(legacy[3] - prod[3]) < PP_TOL,
        "frames_present": n_flat == tr["registered_frames"],
    }
    return {"compatible": all(checks.values()), "checks": checks, "flatten_frames": n_flat,
            "legacy_canvas": legacy, "production_canvas": prod,
            "pp_delta_px": [prod[2] - legacy[2], prod[3] - legacy[3]], "tolerance_px": PP_TOL}


def build_metadata(meta, smeta, R, plate, flat):
    src, tr = meta["source"], meta["tracking"]
    pc, fc = smeta["proxy"]["camera"], smeta["full"]["camera"]
    P, I, O = R["planned"], R["inputs"], R["outputs"]
    off = tr["frame_offset_tracking_to_source"] or 0
    return {
        "schema": "ai_tracking_companion.metadata/1",
        "companion_version": COMPANION_VERSION,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "shot_name": R["shot"],
        "ai_tracking_scene": R["scene"],
        "paths": {
            "source_plate": plate[0],
            "tracking_output": I["ai_tracking_output"],
            "tracking_scene": I["ai_tracking_scene_dir"],
            "tracking_flatten": I["tracking_flatten_pattern"],
            "hip": I["hip"],
            "export_root": O["export_root"],
        },
        "source": {"kind": src["kind"], "resolution": [src["width"], src["height"]],
                   "first_frame": plate[1], "last_frame": plate[2], "frame_numbering": src["frame_numbering"],
                   "fps": src["fps"], "fps_rational": src.get("fps_rational"), "fps_source": src["fps_source"]},
        "tracking": {"resolution": [tr["proxy_width"], tr["proxy_height"]],
                     "scale_to_source": [tr["scale_x"], tr["scale_y"]],
                     "undistorted_resolution": smeta["proxy"]["canvas"][:2],
                     "first_frame": tr["tracking_first_frame"], "last_frame": tr["tracking_last_frame"],
                     "first_frame_in_source_numbering": tr["source_frame_of_tracking_first"],
                     "last_frame_in_source_numbering": tr["source_frame_of_tracking_last"],
                     "frame_offset_tracking_to_source": off,
                     "unregistered_frames": tr["unregistered_frames"],
                     "points3d": meta["camera"].get("points3d")},
        "production_canvas": {"resolution": smeta["full"]["canvas"][:2], "principal_point": smeta["full"]["canvas"][2:],
                              "rule": smeta["full_canvas_rule"],
                              "legacy_canvas_info_only": smeta["legacy_full_canvas_info_only"]},
        "camera": {"colmap_model": meta["camera"]["colmap_cameras"][0]["model"],
                   "lens_model": "OPENCV k1 k2 p1 p2 k3 k4 (as undistortionNerfstudioColmap.py)",
                   "focal_mm": smeta["full"]["filmback"]["focal_mm"], "sensor_width_mm_assumed": 36.0,
                   "full_res_intrinsics": {"fx": fc["fl_x"], "fy": fc["fl_y"], "cx": fc["cx"], "cy": fc["cy"]},
                   "production_principal_point": smeta["full"]["canvas"][2:],
                   "tracking_intrinsics": {"fx": pc["fl_x"], "fy": pc["fl_y"], "cx": pc["cx"], "cy": pc["cy"]},
                   "distortion": {k: pc[k] for k in ("k1", "k2", "k3", "k4", "p1", "p2")},
                   "winy_mode": "corrected",
                   "maya_filmback": {k: smeta["full"]["filmback"][k] for k in ("aperture_mm", "resx", "resy", "winx", "winy_corrected")}},
        "stmap": {"undistort": P["lens_undistort"], "redistort": P["lens_redistort"],
                  "undistort_size": smeta["full"]["canvas"][:2], "redistort_size": smeta["full"]["plate"],
                  "dtype": "32-bit float EXR", "data": "DATA -- read raw, no colour transform",
                  "redistort_solver": smeta["redistort_solver"],
                  "convention": {"U": "(col + 0.5) / W", "V_top_origin_row": "1 - (row + 0.5) / H",
                                 "V_nuke_bottom_origin": "(y_nuke + 0.5) / H", "nuke_y_flip": "none"}},
        "flatten": {"mode": R["options"]["flatten_mode"],
                    "path": (I["tracking_flatten_pattern"] if R["options"]["flatten_mode"] == "reference_ai_tracking"
                             else O.get("production_flatten")),
                    "frame_numbering": ("tracking (1..N); source frame = tracking frame + frame_offset"
                                        if R["options"]["flatten_mode"] == "reference_ai_tracking" else "source"),
                    "frame_offset": off if R["options"]["flatten_mode"] == "reference_ai_tracking" else 0,
                    "compatibility": flat},
        "maya": {"loader": P["maya_loader"], "camera_primary": P["maya_cam_abc"], "camera_fallback_fbx": P["maya_cam_fbx"],
                 "camera_fallback_sidecar": P["maya_sidecar"], "pointcloud_npz": P["maya_points_npz"],
                 "pointcloud_format": "npz: P (N,3 float32, Houdini/Maya world), Cd (N,3 float32 0-1)",
                 "hierarchy": f"AI_TRACKING_GRP|{R['shot']}_CAM (+{R['shot']}_IMAGEPLANE) , AI_TRACKING_GRP|{R['shot']}_POINTCLOUD"},
        "nuke": {"setup": P["nuke_setup"], "status": "pending",
                 "role": "lens handoff / example setup -- not a comp template"},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="resolve and validate paths only")
    ap.add_argument("--steps", nargs="+", choices=STEPS, default=list(DEFAULT_STEPS))
    a = ap.parse_args()
    t0 = time.time()
    try:
        R = path_resolver.resolve(a.config, protected_roots=[os.path.dirname(site_config.get("upstream_repo"))],
                                  overwrite=a.overwrite)
    except path_resolver.ConfigError as e:
        print(f"CONFIG ERROR: {e}")
        sys.exit(3)
    I, O, P, shot, opts = R["inputs"], R["outputs"], R["planned"], R["shot"], R["options"]
    log(f"shot {shot}  (AI Tracking scene '{R['scene']}')  export {O['export_root']}")
    if a.dry_run:
        print(json.dumps(R, indent=1))
        return

    work = O["work_dir"]
    logs = os.path.join(work, "logs")
    os.makedirs(logs, exist_ok=True)
    json.dump(R, open(os.path.join(work, f"{shot}_resolved_paths.json"), "w"), indent=1)

    # ---- meta + Unsupported / solve guard (before any export is written) ----------
    meta = companion_meta.build_meta(I["ai_tracking_scene_dir"], I["source_plate"], I["transforms_json"],
                                     I["transforms_undistorted_json"])
    meta["delivery_name"] = shot
    # FPS chain: source (ffprobe / EXR header) -> project config -> default 24
    if meta["source"]["fps_source"] == "default" and opts.get("project_fps"):
        fr = fractions.Fraction(str(opts["project_fps"]))
        meta["source"].update(fps=float(fr), fps_rational=f"{fr.numerator}/{fr.denominator}", fps_source="project_config")
    meta_path = os.path.join(work, f"{shot}_companion_meta.json")
    json.dump(meta, open(meta_path, "w"), indent=1)
    if not meta["support"]["supported"]:
        print("UNSUPPORTED -- no export produced:\n  " + "\n  ".join(meta["support"]["reasons"]))
        sys.exit(2)
    plate = plate_read_path(meta, R)
    log(f"source {meta['source']['kind']} {meta['source']['width']}x{meta['source']['height']} "
        f"frames {plate[1]}-{plate[2]}  fps {meta['source']['fps']:.3f} [{meta['source']['fps_source']}]  "
        f"tracking {meta['tracking']['proxy_width']}x{meta['tracking']['proxy_height']}")

    # ---- STMaps computed in work/stage; nothing reaches the export until checks pass ----
    stage = os.path.join(work, "stage")
    import stmap_generator
    if os.path.exists(os.path.join(stage, "lens")):
        shutil.rmtree(os.path.join(stage, "lens"))
    smeta = stmap_generator.build(meta, os.path.join(stage, "lens"), norm="center", solver="converged")
    log(f"production canvas {smeta['full']['canvas'][:2]} pp ({smeta['full']['canvas'][2]:.4f}, {smeta['full']['canvas'][3]:.4f})")

    flat = None
    if opts["flatten_mode"] == "reference_ai_tracking":
        flat = flatten_compatibility(meta, smeta, R)
        if not flat["compatible"]:
            print("FLATTEN NOT IN PRODUCTION SPACE -- cannot reference the AI Tracking flatten:\n  "
                  + json.dumps(flat, indent=1) + "\n  set options.flatten_mode to 'render' or 'none' (decision needed)")
            sys.exit(4)
        log(f"AI Tracking flatten referenced (production space, pp delta {flat['pp_delta_px'][0]:.2e}, {flat['pp_delta_px'][1]:.2e} px)")

    if "stmap" in a.steps:
        os.makedirs(O["lens_dir"], exist_ok=True)
        shutil.copy2(smeta["files"]["full_undistort"], P["lens_undistort"])
        shutil.copy2(smeta["files"]["full_redistort"], P["lens_redistort"])
        log("lens: STMaps written")
    dev = os.path.join(work, "dev")
    os.makedirs(dev, exist_ok=True)
    json.dump(smeta, open(os.path.join(dev, f"{shot}_stmap_meta.json"), "w"), indent=2)
    # staged STMaps are now either in the export or not wanted: do not keep a second copy
    if opts.get("developer_nk"):
        shutil.copy2(smeta["files"]["proxy_undistort"], os.path.join(dev, f"{shot}_proxy_undistort_qc.exr"))
    shutil.rmtree(os.path.join(stage, "lens"))

    # ---- Maya: production camera + point cloud (HIP memory-only) --------------------
    mstage = os.path.join(stage, "maya")
    if "maya" in a.steps:
        if os.path.exists(mstage):
            shutil.rmtree(mstage)
        smeta_dev = os.path.join(dev, f"{shot}_stmap_meta.json")
        cmd = [sys.executable, os.path.join(ROOT, "maya_export", "run_maya_export.py"), "--meta", meta_path,
               "--hip", I["hip"], "--out-dir", mstage, "--modes", "corrected", "--production-canvas", smeta_dev]
        if opts.get("verify", True):
            cmd.append("--maya-qc")
        rc = run(cmd, os.path.join(logs, "maya_export.log"))
        summ_p = os.path.join(mstage, "export_summary.json")
        summ = json.load(open(summ_p)) if os.path.exists(summ_p) else {}
        if rc != 0 or not summ.get("hip_unchanged"):
            raise SystemExit(f"Maya export failed rc={rc} (see {logs}/maya_export.log)")
        os.makedirs(O["maya_dir"], exist_ok=True)
        sc_name = R["scene"]
        for src_name, dst in ((f"{sc_name}_cam_corrected.abc", P["maya_cam_abc"]),
                              (f"{sc_name}_cam_corrected.fbx", P["maya_cam_fbx"]),
                              (f"{sc_name}_cam_corrected.maya_camera.json", P["maya_sidecar"]),
                              (f"{sc_name}_points.npz", P["maya_points_npz"])):
            shutil.copy2(os.path.join(mstage, src_name), dst)
        tpl = open(os.path.join(ROOT, "maya_export", "shot_loader_template.py"), encoding="utf-8").read()
        with open(P["maya_loader"], "w", encoding="utf-8", newline="\n") as f:
            f.write(tpl.replace("__METADATA_ABS__", P["metadata"]).replace("__SHOT__", shot))
        log("maya: camera ABC (primary), FBX + camera.json (fallback), points.npz, load_maya.py written")

    # ---- metadata --------------------------------------------------------------------
    md = build_metadata(meta, smeta, R, plate, flat)
    nuke_done = "nuke" in a.steps
    if nuke_done:
        md["nuke"]["status"] = "written"
    else:
        md["nuke"]["status"] = "not generated this run (Artist graph pending approval)"
    if "metadata" in a.steps:
        os.makedirs(O["metadata_dir"], exist_ok=True)
        json.dump(md, open(P["metadata"], "w"), indent=1)
        log(f"metadata: {P['metadata']}")

    # ---- Nuke Artist setup ------------------------------------------------------------
    if nuke_done:
        import build_nuke_package as bnp
        spec = dict(md)
        spec["_nuke"] = {"path_mode": "absolute", "graph": "artist", "metadata": P["metadata"],
                         "plate": plate[0], "plate_first": plate[1], "plate_last": plate[2],
                         "stmap_undistort": P["lens_undistort"], "stmap_redistort": P["lens_redistort"],
                         "tracking_reference_flatten": md["flatten"]["path"],
                         "flatten_mode": opts["flatten_mode"],
                         "flatten_frame_offset": md["flatten"]["frame_offset"],
                         "flatten_first": md["tracking"]["first_frame"] if md["flatten"]["frame_offset"] else plate[1],
                         "flatten_last": md["tracking"]["last_frame"] if md["flatten"]["frame_offset"] else plate[2]}
        spec_path = os.path.join(dev, f"{shot}_nk_spec.json")
        json.dump(spec, open(spec_path, "w"), indent=1)
        bnp.write_nk(spec_path, P["nuke_setup"], path_mode="absolute")
        log(f"nuke: {P['nuke_setup']}")

    # ---- optional production flatten render (flatten_mode "render") -------------------
    if "flatten" in a.steps and opts["flatten_mode"] == "render":
        if not nuke_done:
            raise SystemExit("flatten_mode 'render' needs the nuke step")
        os.makedirs(os.path.dirname(O["production_flatten"]), exist_ok=True)
        rc = run([site_config.get("nuke"), "-t", os.path.join(ROOT, "nuke_package", "render_production_flatten.py"),
                  P["nuke_setup"], f"out={O['production_flatten']}", f"range={plate[1]},{plate[2]}"],
                 os.path.join(logs, "flatten_render.log"))
        if rc != 0:
            raise SystemExit("production flatten render failed (see logs)")

    # ---- verify (regression smoke on the real outputs) --------------------------------
    verify = {}
    if "verify" in a.steps and opts.get("verify", True):
        import verify_shot
        verify = verify_shot.verify(meta, smeta, R, plate, os.path.join(work, "verify"), mstage)
        json.dump(verify, open(os.path.join(work, f"{shot}_verify.json"), "w"), indent=1)
        log("verify: " + json.dumps(verify["summary"]))

    # ---- manifest (work dir) + storage ---------------------------------------------------
    purposes = {
        "lens_undistort": ("undistort STMap: original plate -> production canvas", True),
        "lens_redistort": ("redistort STMap: production canvas -> original plate (converged)", True),
        "maya_cam_abc": ("Maya camera PRIMARY (production canvas, corrected winy)", True),
        "maya_cam_fbx": ("Maya camera FALLBACK (use with camera.json)", False),
        "maya_sidecar": ("FBX fallback sidecar: fps, film offset, gate", False),
        "maya_points_npz": ("point cloud P + Cd for the Maya-native importer", True),
        "maya_loader": ("Maya Artist entry point (one-call scene setup)", True),
        "metadata": ("shot / lens / path metadata", True),
        "nuke_setup": ("Nuke lens handoff / example setup", True),
    }
    files = [{"key": k, "path": P[k], "bytes": os.path.getsize(P[k]), "purpose": why, "required_production_asset": req}
             for k, (why, req) in purposes.items() if os.path.exists(P[k])]
    export_all = [os.path.join(b, f) for b, _, fs in os.walk(O["export_root"]) for f in fs]
    ours = {os.path.normcase(os.path.normpath(f["path"])) for f in files}
    work_bytes = sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(work) for f in fs)
    manifest = {
        "schema": "ai_tracking_companion.manifest/2", "companion_version": COMPANION_VERSION, "shot": shot,
        "config": R["config"], "created": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": a.steps,
        "files": files, "export_bytes_added": sum(f["bytes"] for f in files),
        "export_other_files_untouched": sorted(f for f in export_all if os.path.normcase(os.path.normpath(f)) not in ours),
        "referenced_not_copied": {"source_plate": plate[0], "tracking_flatten": I["tracking_flatten_pattern"],
                                  "hip": I["hip"], "tracking_scene": I["ai_tracking_scene_dir"]},
        "work_dir": work, "work_bytes": work_bytes,
        "verify": verify.get("summary"), "elapsed_s": round(time.time() - t0, 1),
    }
    json.dump(manifest, open(P["manifest"], "w"), indent=1)
    log(f"export added {manifest['export_bytes_added'] / 1e6:.2f} MB in {len(files)} files; work {work_bytes / 1e6:.1f} MB")
    if verify and not verify["summary"]["pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

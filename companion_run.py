"""AI Tracking Companion -- transactional production build for one shot.

Shot-config mode (explicit paths; regression / scripted use):
    python companion_run.py <shot_config.json> [--overwrite] [--dry-run] [--outputs lens maya nuke]

Project mode (auto detect; what the GUI will call):
    python companion_run.py --project <project.json> --input <AI Tracking folder> --shot <name>
                            [--export <root>] [--plate <override>] [--scene <name>] [--fps <override>]
                            [--overwrite] [--dry-run] [--outputs lens maya nuke]

Flow:  Preflight -> Resolve -> Stage -> Validate -> Publish -> Summary
  * everything is built in <work>/builds/<build_id>/stage with the final filenames;
    file contents already carry the final export paths
  * validation runs on the stage (path-remapped copies for Nuke / Maya)
  * publish only if nothing is BLOCKED / FAIL; existing delivery -> CANCELLED unless
    --overwrite, which backs the old files up to <build>/backup first; a failed publish
    is rolled back to the exact previous state
  * metadata is always built; Nuke implies Lens

Deliveries under the export root (names = Artist shot name):
    lens/      <shot>_undistort_stmap.exr  <shot>_redistort_stmap.exr
    maya/      <shot>_load_maya.py  <shot>_cam_corrected.abc  <shot>_cam_corrected.fbx  <shot>_camera.json  <shot>_points.npz
    metadata/  <shot>_metadata.json
    nuke/      <shot>_lens_setup.nk
Never copies plates / flatten / sources; never writes into AI Tracking; never saves the HIP.
Exit codes: 0 PASS (warnings allowed), 1 FAIL, 2 BLOCKED, 5 CANCELLED.
"""
import argparse
import copy
import fractions
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ("common", "stmap", "maya_export", "nuke_package", "tests"):
    sys.path.insert(0, os.path.join(ROOT, sub))
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import site_config  # noqa: E402
import path_resolver  # noqa: E402
import companion_meta  # noqa: E402
import project_config  # noqa: E402
import auto_detect  # noqa: E402
import build_transaction as bt  # noqa: E402
from version import __version__ as COMPANION_VERSION  # noqa: E402

PP_TOL = 0.01  # px: AI Tracking flatten counts as production space only within this
ALL_OUTPUTS = ("lens", "maya", "nuke")
OUTPUT_KEYS = {
    "lens": ("lens_undistort", "lens_redistort"),
    "maya": ("maya_loader", "maya_cam_abc", "maya_cam_fbx", "maya_sidecar", "maya_points_npz"),
    "metadata": ("metadata",),
    "nuke": ("nuke_setup",),
}
PURPOSE = {
    "lens_undistort": ("undistort STMap: original plate -> production canvas", True),
    "lens_redistort": ("redistort STMap: production canvas -> original plate (converged)", True),
    "maya_loader": ("Maya Artist entry point (one-call scene setup)", True),
    "maya_cam_abc": ("Maya camera PRIMARY (production canvas, corrected winy)", True),
    "maya_cam_fbx": ("Maya camera FALLBACK (use with camera.json)", False),
    "maya_sidecar": ("FBX fallback sidecar: fps, film offset, gate", False),
    "maya_points_npz": ("point cloud P + Cd for the Maya-native importer", True),
    "metadata": ("shot / lens / path metadata", True),
    "nuke_setup": ("Nuke lens handoff / example setup", True),
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd, logfile):
    env = os.environ.copy()
    for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(k, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with open(logfile, "w", encoding="utf-8", errors="replace") as f:
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env).returncode


# ------------------------------------------------------------------ project mode -> shot config
def shot_config_from_project(a):
    """Auto detect from an AI Tracking folder + project rules; persist overrides; return config path."""
    proj = project_config.load(a.project)
    scenes = auto_detect.find_scenes(a.input)
    if a.scene:
        scenes = [s for s in scenes if os.path.basename(s) == a.scene]
    if len(scenes) != 1:
        raise bt.BuildStop(bt.BLOCKED, "scene", f"{len(scenes)} AI Tracking scene(s) found in {a.input}"
                           + ("" if scenes else "") + (" -- choose one with --scene" if len(scenes) > 1 else ""),
                           [os.path.basename(s) for s in auto_detect.find_scenes(a.input)])
    scene_dir = scenes[0].replace("\\", "/")
    shot = a.shot
    tokens = dict(proj.get("vars") or {})
    tokens.update(shot=shot, scene=os.path.basename(scene_dir), ai_tracking_scene_dir=scene_dir,
                  ai_tracking_output=os.path.dirname(scene_dir))
    work_dir = os.path.join(project_config.work_root(proj), shot).replace("\\", "/")
    cfg_path = os.path.join(work_dir, f"{shot}.shot.json")
    prev = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    overrides = dict(prev.get("overrides") or {})
    if a.plate:
        overrides["source_plate"] = a.plate.replace("\\", "/")
    if a.fps:
        overrides["fps"] = str(a.fps)
    facts = auto_detect.tracking_facts(scene_dir)
    ffp = None
    try:
        ffp = site_config.get("ffprobe")
    except (KeyError, FileNotFoundError):
        pass
    plate = auto_detect.resolve_plate(proj, tokens, facts, ffp, override=overrides.get("source_plate"))
    if plate["status"] not in ("auto", "override"):
        msg = {"none": "no source plate candidate passed validation",
               "ambiguous": "several plate candidates are valid -- Artist override required (--plate)",
               "override_invalid": "the plate override does not match this AI Tracking scene"}[plate["status"]]
        raise bt.BuildStop(bt.BLOCKED, f"plate_{plate['status']}", msg, plate["candidates"])
    export_root = a.export or project_config.substitute(proj["export_root"], tokens, "export_root")
    cfg = {
        "schema": "ai_tracking_companion.shot/2",
        "_generated_by": f"companion_run project mode {COMPANION_VERSION}",
        "project": proj["_path"],
        "shot": shot,
        "inputs": {"ai_tracking_scene_dir": scene_dir, "source_plate": plate["selected"]},
        "outputs": {"export_root": export_root.replace("\\", "/"), "work_dir": work_dir},
        "options": {"flatten_mode": proj.get("flatten_mode", "reference_ai_tracking"),
                    "project_fps": proj.get("fps"), "fps_override": overrides.get("fps"), "verify": True},
        "overrides": overrides,
        "auto_detect": {"scene": os.path.basename(scene_dir), "plate": plate,
                        "shot_name_suggestion": auto_detect.suggest_shot_name(proj.get("shot_name_regex"), plate["selected"], scene_dir)},
    }
    os.makedirs(work_dir, exist_ok=True)
    json.dump(cfg, open(cfg_path, "w"), indent=1)
    return cfg_path, cfg


# ------------------------------------------------------------------ helpers
def plate_read_path(meta, R):
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
        raise bt.BuildStop(bt.BLOCKED, "plate_pattern", "source sequence is not a single padded file pattern")
    return os.path.join(src["path"], pat[0]).replace("\\", "/"), pat[1], pat[2]


def flatten_compatibility(meta, smeta, R):
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


def fingerprint(meta, smeta, plate):
    """Identity of the lens / camera solution -- partial builds must match the published one."""
    h = hashlib.sha256()
    for part in (json.dumps(smeta["full"]["canvas"]), json.dumps(smeta["full"]["camera"], sort_keys=True),
                 plate[0], str(plate[1]), str(plate[2]),
                 bt.sha256(meta["transforms_json"]), bt.sha256(meta["transforms_undistorted_json"])):
        h.update(part.encode())
    return h.hexdigest()[:16]


def build_metadata(meta, smeta, R, plate, flat, build_id, fp, outputs):
    src, tr = meta["source"], meta["tracking"]
    pc, fc = smeta["proxy"]["camera"], smeta["full"]["camera"]
    P, I, O = R["planned"], R["inputs"], R["outputs"]
    off = tr["frame_offset_tracking_to_source"] or 0
    mode = R["options"]["flatten_mode"]
    return {
        "schema": "ai_tracking_companion.metadata/1",
        "companion_version": COMPANION_VERSION,
        "build_id": build_id,
        "fingerprint": fp,
        "outputs_built": sorted(outputs | {"metadata"}),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "shot_name": R["shot"],
        "ai_tracking_scene": R["scene"],
        "paths": {"source_plate": plate[0], "tracking_output": I["ai_tracking_output"],
                  "tracking_scene": I["ai_tracking_scene_dir"], "tracking_flatten": I["tracking_flatten_pattern"],
                  "hip": I["hip"], "export_root": O["export_root"]},
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
        "flatten": {"mode": mode,
                    "path": (I["tracking_flatten_pattern"] if mode == "reference_ai_tracking" else O.get("production_flatten")),
                    "frame_numbering": ("tracking (1..N); source frame = tracking frame + frame_offset"
                                        if mode == "reference_ai_tracking" else "source"),
                    "frame_offset": off if mode == "reference_ai_tracking" else 0,
                    "compatibility": flat},
        "maya": {"loader": P["maya_loader"], "camera_primary": P["maya_cam_abc"], "camera_fallback_fbx": P["maya_cam_fbx"],
                 "camera_fallback_sidecar": P["maya_sidecar"], "pointcloud_npz": P["maya_points_npz"],
                 "pointcloud_format": "npz: P (N,3 float32, Houdini/Maya world), Cd (N,3 float32 0-1)",
                 "hierarchy": f"AI_TRACKING_GRP|{R['shot']}_CAM (+{R['shot']}_IMAGEPLANE) , AI_TRACKING_GRP|{R['shot']}_POINTCLOUD"},
        "nuke": {"setup": P["nuke_setup"], "status": "written" if "nuke" in outputs else "not built",
                 "role": "lens handoff / example setup -- not a comp template"},
    }


# ------------------------------------------------------------------ main build
def build(cfg_path, a, record, generated_cfg=None):
    t = time.time()
    # ---- Preflight + Resolve -------------------------------------------------------
    upstream_install = os.path.dirname(site_config.get("upstream_repo"))
    try:
        R = path_resolver.resolve(cfg_path, protected_roots=[upstream_install], overwrite=True)
    except path_resolver.ConfigError as e:
        raise bt.BuildStop(bt.BLOCKED, "config", str(e))
    I, O, P, shot, opts = R["inputs"], R["outputs"], R["planned"], R["shot"], R["options"]
    record.shot = shot
    outputs = set(a.outputs or ALL_OUTPUTS)
    if "nuke" in outputs and "lens" not in outputs:
        outputs.add("lens")
        record.issue(bt.WARNING, "dependency", "Nuke needs the lens STMaps: Lens enabled automatically")
    keys = [k for o in sorted(outputs | {"metadata"}) for k in OUTPUT_KEYS[o]]
    tools = {"hython": "maya" in outputs, "mayapy": "maya" in outputs and opts.get("verify", True),
             "nuke": "nuke" in outputs or opts["flatten_mode"] == "render"}
    for tool, needed in tools.items():
        if needed:
            try:
                site_config.get(tool)
            except (KeyError, FileNotFoundError) as e:
                raise bt.BuildStop(bt.BLOCKED, "tool_missing", f"{tool}: {e}")
    render = opts["flatten_mode"] == "render"
    if render and "nuke" not in outputs:
        raise bt.BuildStop(bt.BLOCKED, "dependency", "flatten_mode 'render' renders through the Nuke setup: enable Nuke")
    finals = [P[k] for k in keys]
    flat_frames = []
    if render:  # rendered flatten is part of the delivery: same transaction
        m0 = companion_meta.build_meta(I["ai_tracking_scene_dir"], I["source_plate"], I["transforms_json"],
                                       I["transforms_undistorted_json"])
        flat_frames = list(range(m0["source"]["source_first_frame"], m0["source"]["source_last_frame"] + 1))
        finals += [O["production_flatten"] % f for f in flat_frames]
    present = bt.existing_targets(finals)
    if present and not a.overwrite:
        raise bt.BuildStop(bt.CANCELLED, "outputs_exist", "delivery already exists -- rerun with --overwrite (old files are backed up)", present)
    record.step("preflight", bt.PASS, time.time() - t, outputs=sorted(outputs | {"metadata"}))
    if a.dry_run:
        print(json.dumps(R, indent=1))
        return None

    build_dir = record.build_dir
    stage = os.path.join(build_dir, "stage").replace("\\", "/")
    logs = os.path.join(build_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    D = {k: bt.stage_path(v, O["export_root"], stage) for k, v in P.items() if k != "manifest"}
    remap = [(O["export_root"], stage)]
    if render:
        flat_dir = os.path.dirname(O["production_flatten"])
        flat_stage_dir = stage + "/_flatten"
        flat_stage = flat_stage_dir + "/" + os.path.basename(O["production_flatten"])
        remap.append((flat_dir, flat_stage_dir))
    validate_dir = os.path.join(build_dir, "validate").replace("\\", "/")
    os.makedirs(validate_dir, exist_ok=True)

    def remapped_copy(path, name):
        txt = open(path, encoding="utf-8").read()
        for a_, b_ in remap:
            txt = txt.replace(a_, b_)
        out = os.path.join(validate_dir, name)
        open(out, "w", encoding="utf-8", newline="\n").write(txt)
        return out

    t = time.time()
    meta = companion_meta.build_meta(I["ai_tracking_scene_dir"], I["source_plate"], I["transforms_json"],
                                     I["transforms_undistorted_json"])
    meta["delivery_name"] = shot
    if opts.get("fps_override"):
        fr = fractions.Fraction(str(opts["fps_override"]))
        meta["source"].update(fps=float(fr), fps_rational=f"{fr.numerator}/{fr.denominator}", fps_source="artist_override")
    elif meta["source"]["fps_source"] == "default" and opts.get("project_fps"):
        fr = fractions.Fraction(str(opts["project_fps"]))
        meta["source"].update(fps=float(fr), fps_rational=f"{fr.numerator}/{fr.denominator}", fps_source="project_config")
    meta_path = os.path.join(build_dir, f"{shot}_companion_meta.json")
    json.dump(meta, open(meta_path, "w"), indent=1)
    if not meta["support"]["supported"]:
        raise bt.BuildStop(bt.BLOCKED, "unsupported", "; ".join(meta["support"]["reasons"]), meta["support"])
    for w in meta["support"]["warnings"]:
        record.issue(bt.WARNING, "source", w)
    if meta["source"]["fps_source"] == "default":
        record.issue(bt.WARNING, "fps_default", "source has no fps and no project fps: default 24 used")
    if meta["tracking"]["unregistered_frames"]:
        record.issue(bt.WARNING, "unregistered_frames",
                     f"{len(meta['tracking']['unregistered_frames'])} tracking frame(s) not registered (black in reference)")
    plate = plate_read_path(meta, R)
    log(f"{shot}: {meta['source']['kind']} {meta['source']['width']}x{meta['source']['height']} "
        f"{plate[1]}-{plate[2]} @{meta['source']['fps']:g} [{meta['source']['fps_source']}]")

    import stmap_generator
    smeta = stmap_generator.build(meta, os.path.join(build_dir, "lens_work"), norm="center", solver="converged")
    flat = None
    if opts["flatten_mode"] == "reference_ai_tracking":
        flat = flatten_compatibility(meta, smeta, R)
        if not flat["compatible"]:
            raise bt.BuildStop(bt.BLOCKED, "flatten_space",
                               "AI Tracking flatten is not in the production space (set flatten_mode 'none')", flat)
    fp = fingerprint(meta, smeta, plate)
    # partial build: the published delivery must be the same solution
    if outputs != set(ALL_OUTPUTS) and os.path.exists(P["metadata"]):
        old = json.load(open(P["metadata"]))
        if old.get("fingerprint") != fp:
            raise bt.BuildStop(bt.BLOCKED, "fingerprint", "partial build over a delivery of a different solution -- build all outputs",
                               {"published": old.get("fingerprint"), "this_build": fp})
    record.extra["fingerprint"] = fp
    record.step("resolve", bt.PASS, time.time() - t, canvas=smeta["full"]["canvas"][:2])

    # ---- Stage -----------------------------------------------------------------------
    t = time.time()
    if "lens" in outputs:
        os.makedirs(os.path.dirname(D["lens_undistort"]), exist_ok=True)
        shutil.copy2(smeta["files"]["full_undistort"], D["lens_undistort"])
        shutil.copy2(smeta["files"]["full_redistort"], D["lens_redistort"])
    smeta_path = os.path.join(build_dir, f"{shot}_stmap_meta.json")
    json.dump(smeta, open(smeta_path, "w"), indent=2)
    shutil.rmtree(os.path.join(build_dir, "lens_work"))

    mstage = os.path.join(build_dir, "maya_work")
    if "maya" in outputs:
        cmd = [sys.executable, os.path.join(ROOT, "maya_export", "run_maya_export.py"), "--meta", meta_path,
               "--hip", I["hip"], "--out-dir", mstage, "--modes", "corrected", "--production-canvas", smeta_path]
        if opts.get("verify", True):
            cmd.append("--maya-qc")
        rc = run(cmd, os.path.join(logs, "maya_export.log"))
        summ_p = os.path.join(mstage, "export_summary.json")
        summ = json.load(open(summ_p)) if os.path.exists(summ_p) else {}
        if rc != 0 or not summ.get("hip_unchanged"):
            raise bt.BuildStop(bt.FAIL, "maya_export", f"Maya export failed rc={rc} (logs/maya_export.log)")
        os.makedirs(os.path.dirname(D["maya_cam_abc"]), exist_ok=True)
        sc_name = R["scene"]
        for src_name, k in ((f"{sc_name}_cam_corrected.abc", "maya_cam_abc"), (f"{sc_name}_cam_corrected.fbx", "maya_cam_fbx"),
                            (f"{sc_name}_cam_corrected.maya_camera.json", "maya_sidecar"), (f"{sc_name}_points.npz", "maya_points_npz")):
            shutil.copy2(os.path.join(mstage, src_name), D[k])
        tpl = open(os.path.join(ROOT, "maya_export", "shot_loader_template.py"), encoding="utf-8").read()
        with open(D["maya_loader"], "w", encoding="utf-8", newline="\n") as f:
            f.write(tpl.replace("__METADATA_ABS__", P["metadata"]).replace("__SHOT__", shot))

    md = build_metadata(meta, smeta, R, plate, flat, record.build_id, fp, outputs)
    os.makedirs(os.path.dirname(D["metadata"]), exist_ok=True)
    json.dump(md, open(D["metadata"], "w"), indent=1)

    if "nuke" in outputs:
        import build_nuke_package as bnp
        spec = dict(md)
        spec["_nuke"] = {"path_mode": "absolute", "graph": "artist", "metadata": P["metadata"],
                         "plate": plate[0], "plate_first": plate[1], "plate_last": plate[2],
                         "stmap_undistort": P["lens_undistort"], "stmap_redistort": P["lens_redistort"],
                         "tracking_reference_flatten": md["flatten"]["path"], "flatten_mode": opts["flatten_mode"],
                         "flatten_frame_offset": md["flatten"]["frame_offset"],
                         "flatten_first": md["tracking"]["first_frame"] if md["flatten"]["frame_offset"] else plate[1],
                         "flatten_last": md["tracking"]["last_frame"] if md["flatten"]["frame_offset"] else plate[2]}
        spec_path = os.path.join(build_dir, f"{shot}_nk_spec.json")
        json.dump(spec, open(spec_path, "w"), indent=1)
        bnp.write_nk(spec_path, D["nuke_setup"], path_mode="absolute")
    if render:  # render from a stage-remapped copy (the final paths do not exist yet)
        rnk = remapped_copy(D["nuke_setup"], f"{shot}_lens_setup.render.nk")
        os.makedirs(flat_stage_dir, exist_ok=True)
        rc = run([site_config.get("nuke"), "-t", os.path.join(ROOT, "nuke_package", "render_production_flatten.py"),
                  rnk, f"out={flat_stage}", f"range={plate[1]},{plate[2]}"], os.path.join(logs, "flatten_render.log"))
        missing = [f for f in flat_frames if not os.path.exists(flat_stage % f)]
        if rc != 0 or missing:
            raise bt.BuildStop(bt.FAIL, "flatten_render", f"production flatten render failed rc={rc}, {len(missing)} frame(s) missing")
    staged = [k for k in keys if os.path.exists(D[k])]
    if sorted(staged) != sorted(keys):
        raise bt.BuildStop(bt.FAIL, "stage_incomplete", "stage is missing files", sorted(set(keys) - set(staged)))
    record.step("stage", bt.PASS, time.time() - t, files=len(staged))

    # ---- Validate --------------------------------------------------------------------
    t = time.time()
    leaks = []
    for k in ("metadata", "nuke_setup", "maya_loader"):
        if k in keys and stage.lower() in open(D[k], encoding="utf-8", errors="replace").read().replace("\\", "/").lower():
            leaks.append(k)
    if leaks:
        raise bt.BuildStop(bt.FAIL, "stage_path_leak", "staged files reference the stage folder", leaks)
    if opts.get("verify", True):
        import verify_shot
        Rv = copy.deepcopy(R)
        Rv["planned"] = {k: (D[k] if k in D else v) for k, v in P.items()}
        Rv["validate_remap"] = {"pairs": remap, "dir": validate_dir}
        if render:
            Rv["outputs"]["production_flatten"] = flat_stage
        verify = verify_shot.verify(meta, smeta, Rv, plate, os.path.join(build_dir, "validate"), mstage)
        json.dump(verify, open(os.path.join(build_dir, f"{shot}_verify.json"), "w"), indent=1)
        failed = [k for k, v in verify["summary"]["checks"].items() if not v]
        if os.environ.get("COMPANION_FAULT_VALIDATE"):  # test hook: prove a failed validation never publishes
            failed.append("injected_validation_fault")
        if failed:
            raise bt.BuildStop(bt.FAIL, "validation", f"{len(failed)} validation check(s) failed", failed)
        record.extra["verify"] = verify["summary"]
    else:
        record.issue(bt.WARNING, "not_validated", "validation disabled (options.verify = false)")
    record.step("validate", bt.PASS, time.time() - t)

    # ---- Publish ---------------------------------------------------------------------
    t = time.time()
    pairs = [(D[k], P[k]) for k in keys]
    if render:
        pairs += [(flat_stage % f, O["production_flatten"] % f) for f in flat_frames]
    fault = os.environ.get("COMPANION_FAULT_PUBLISH_AFTER")
    pub = bt.publish(pairs, os.path.join(build_dir, "backup"), a.overwrite, record,
                     fault_after=int(fault) if fault not in (None, "") else None)
    record.step("publish", bt.PASS, time.time() - t, **pub)
    shutil.rmtree(stage, ignore_errors=True)  # published: do not keep a second copy

    # ---- Summary / provenance --------------------------------------------------------------
    prov = {"build_id": record.build_id, "companion_version": COMPANION_VERSION, "shot_name": shot,
            "config": cfg_path, "project": (generated_cfg or {}).get("project"),
            "input_root": I["ai_tracking_output"], "ai_tracking_scene": I["ai_tracking_scene_dir"],
            "export_root": O["export_root"], "resolved_plate": plate[0], "resolved_flatten": md["flatten"]["path"],
            "hip": I["hip"], "source_resolution": md["source"]["resolution"],
            "source_frame_range": [plate[1], plate[2]],
            "tracking_frame_range": [md["tracking"]["first_frame"], md["tracking"]["last_frame"]],
            "fps": md["source"]["fps"], "fps_source": md["source"]["fps_source"],
            "camera_model": md["camera"]["colmap_model"], "production_canvas": md["production_canvas"],
            "artist_overrides": (generated_cfg or {}).get("overrides", {}),
            "auto_detect": (generated_cfg or {}).get("auto_detect"), "fingerprint": fp,
            "outputs": sorted(outputs | {"metadata"})}
    json.dump(prov, open(os.path.join(build_dir, "shot_config.json"), "w"), indent=1)
    files = [{"key": k, "path": P[k], "bytes": os.path.getsize(P[k]), "purpose": PURPOSE[k][0],
              "required_production_asset": PURPOSE[k][1]} for k in keys]
    if render:
        files.append({"key": "production_flatten", "path": O["production_flatten"], "frames": len(flat_frames),
                      "bytes": sum(os.path.getsize(O["production_flatten"] % f) for f in flat_frames),
                      "purpose": "production flatten (rendered)", "required_production_asset": True})
    manifest = {"schema": "ai_tracking_companion.manifest/3", "companion_version": COMPANION_VERSION,
                "build_id": record.build_id, "shot": shot, "files": files,
                "export_bytes_added": sum(f["bytes"] for f in files),
                "delivery_bytes": sum(f["bytes"] for f in files),
                "work_bytes": sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(O["work_dir"]) for f in fs),
                "verify": record.extra.get("verify"),
                "referenced_not_copied": {"source_plate": plate[0], "tracking_flatten": I["tracking_flatten_pattern"],
                                          "hip": I["hip"], "tracking_scene": I["ai_tracking_scene_dir"]}}
    json.dump(manifest, open(os.path.join(build_dir, "manifest.json"), "w"), indent=1)
    # stable copies for tools that look up the latest build of a shot
    shutil.copy2(os.path.join(build_dir, "manifest.json"), os.path.join(O["work_dir"], f"{shot}_companion_manifest.json"))
    if os.path.exists(os.path.join(build_dir, f"{shot}_verify.json")):
        shutil.copy2(os.path.join(build_dir, f"{shot}_verify.json"), os.path.join(O["work_dir"], f"{shot}_verify.json"))
    record.extra["export_bytes_added"] = manifest["export_bytes_added"]
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", nargs="?", help="shot config (shot-config mode)")
    ap.add_argument("--project")
    ap.add_argument("--input", help="AI Tracking folder (output root or scene folder)")
    ap.add_argument("--shot")
    ap.add_argument("--export")
    ap.add_argument("--plate", help="Artist override for the source plate (recorded for this shot)")
    ap.add_argument("--scene")
    ap.add_argument("--fps", help="Artist override fps (recorded as artist_override)")
    ap.add_argument("--outputs", nargs="+", choices=ALL_OUTPUTS, help="default: all (metadata is always built)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing delivery (backed up first)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    shot_guess = a.shot or "unknown"
    record = bt.BuildRecord(None, bt.new_build_id(), shot_guess)
    generated = None
    try:
        if a.config:
            cfg_path = a.config
        else:
            if not (a.project and a.input and a.shot):
                raise bt.BuildStop(bt.BLOCKED, "arguments", "project mode needs --project, --input and --shot")
            cfg_path, generated = shot_config_from_project(a)
        cfg = json.load(open(cfg_path))
        R0 = path_resolver.resolve(cfg_path, overwrite=True)
        record.build_dir = os.path.join(R0["outputs"]["work_dir"], "builds", record.build_id).replace("\\", "/")
        os.makedirs(record.build_dir, exist_ok=True)
        log(f"build {record.build_id}  shot {R0['shot']}  export {R0['outputs']['export_root']}")
        build(cfg_path, a, record, generated or (cfg if cfg.get("overrides") is not None else None))
    except bt.BuildStop as e:
        record.issue(e.level, e.code, e.message, e.detail)
    except path_resolver.ConfigError as e:
        record.issue(bt.BLOCKED, "config", str(e))
    except Exception as e:  # noqa: BLE001 -- any runtime error is a FAIL, never a silent success
        record.issue(bt.FAIL, "exception", f"{type(e).__name__}: {e}", traceback.format_exc())
    if record.build_dir is None:  # failed before a build folder existed
        record.build_dir = os.path.join(project_config.COMPANION_ROOT, "work", "_failed_builds", record.build_id)
    res = record.write()
    for i in res["issues"]:
        log(f"{i['level']:9} {i['code']}: {i['message']}")
    log(f"RESULT {res['status']}  (build {res['build_id']}, {res['elapsed_s']} s, "
        f"{len(res['published'])} file(s) published)  -> {record.build_dir}/build_result.json")
    sys.exit(res["exit_code"])


if __name__ == "__main__":
    main()

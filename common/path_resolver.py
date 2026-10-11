"""Shot path resolver: turns a shot config into concrete, validated absolute paths.

The ONLY place that knows how a project lays out its folders is the shot config
(later written by the GUI from the Artist's choices: input folder, export folder,
shot name).  Every lower module receives finished paths from here.

Shot config (JSON):
{
  "schema": "ai_tracking_companion.shot/2",
  "vars":    {"proj": "X:/myproj"},                 # free tokens
  "shot":    "demo_sh0010",                       # Artist shot name -> every production filename
  "inputs": {
    "ai_tracking_scene_dir": "{proj}/work/jpg",     # REQUIRED  <AI Tracking output>/<scene>
    "source_plate":          "{proj}/plates/{shot}.####.exr",   # REQUIRED video / sequence dir / pattern
    "hip":                   optional (default {ai_tracking_scene_dir}/{scene}.hip)
    "tracking_flatten_dir":  optional (default {ai_tracking_scene_dir}/undistort/images_undistorted)
  },
  "outputs": {
    "export_root": "{proj}/work/export",            # REQUIRED: Artist production export
    "lens_dir":     optional (default {export_root}/lens)
    "maya_dir":     optional (default {export_root}/maya)
    "metadata_dir": optional (default {export_root}/metadata)
    "nuke_dir":     optional (default {export_root}/nuke)
    "work_dir":     optional (default <Companion>/work/{shot}) -- logs / QC, never in the export
    "production_flatten": only for flatten_mode "render" (pattern)
  },
  "options": {
    "flatten_mode": "reference_ai_tracking" | "render" | "none",   (default reference_ai_tracking)
    "project_fps": optional project fps, e.g. 24 or "24000/1001".  FPS chain:
                   source (ffprobe / EXR header) -> project_fps -> default 24
    "verify": true, "developer_nk": false
  }
}

Built-in tokens: {shot} {scene} {ai_tracking_scene_dir} {ai_tracking_output} {config_dir} {export_root}.
Relative paths resolve against the config file's folder.  The AI Tracking output
layout (<out>/<scene>_transforms.json, <scene>/sparse, <scene>/undistort, .hip)
is the upstream tool's fixed contract and is derived here, not configured.
"""
import glob
import json
import os
import re

TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
FRAME_PAT = re.compile(r"(%0?\d*d|#+)")
OUTPUT_DIRS = ("lens_dir", "maya_dir", "metadata_dir", "nuke_dir", "work_dir")
FLATTEN_MODES = ("reference_ai_tracking", "render", "none")
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".mxf", ".m4v"}
COMPANION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigError(Exception):
    pass


def norm(p):
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/")


def _sub(value, tokens, where):
    for _ in range(10):
        new = TOKEN.sub(lambda m: tokens[m.group(1)] if m.group(1) in tokens else m.group(0), value)
        if new == value:
            break
        value = new
    left = TOKEN.findall(value)
    if left:
        raise ConfigError(f"{where}: unknown token(s) {left} in '{value}'")
    return value


def _inside(child, parent):
    child, parent = norm(child).lower(), norm(parent).lower().rstrip("/")
    return child == parent or child.startswith(parent + "/")


def planned_files(shot, O):
    """Production filenames: Artist shot name only (resolution / fps live in metadata)."""
    return {
        "lens_undistort": f"{O['lens_dir']}/{shot}_undistort_stmap.exr",
        "lens_redistort": f"{O['lens_dir']}/{shot}_redistort_stmap.exr",
        "maya_cam_abc": f"{O['maya_dir']}/{shot}_cam_corrected.abc",
        "maya_cam_fbx": f"{O['maya_dir']}/{shot}_cam_corrected.fbx",
        "maya_sidecar": f"{O['maya_dir']}/{shot}_camera.json",
        "maya_points_npz": f"{O['maya_dir']}/{shot}_points.npz",
        "maya_loader": f"{O['maya_dir']}/{shot}_load_maya.py",
        "metadata": f"{O['metadata_dir']}/{shot}_metadata.json",
        "nuke_setup": f"{O['nuke_dir']}/{shot}_lens_setup.nk",
        "manifest": f"{O['work_dir']}/{shot}_companion_manifest.json",
    }


def resolve(config_path, protected_roots=(), overwrite=False):
    """Return a dict of absolute, validated paths for one shot."""
    config_path = norm(config_path)
    cfg = json.load(open(config_path))
    base = os.path.dirname(config_path)
    tokens = {"config_dir": base}
    for k, v in (cfg.get("vars") or {}).items():
        tokens[k] = str(v)

    def path(v, where):
        p = _sub(v, tokens, where)
        return norm(p if os.path.isabs(p) else os.path.join(base, p))

    inp = cfg.get("inputs") or {}
    for k in ("ai_tracking_scene_dir", "source_plate"):
        if k not in inp:
            raise ConfigError(f"inputs.{k} is required")
    scene_dir = path(inp["ai_tracking_scene_dir"], "inputs.ai_tracking_scene_dir")
    scene = os.path.basename(scene_dir)
    ai_out = os.path.dirname(scene_dir)
    tokens.update(scene=scene, ai_tracking_scene_dir=scene_dir, ai_tracking_output=ai_out)
    if not cfg.get("shot"):
        raise ConfigError("shot (Artist shot name) is required -- it names every production file")
    tokens["shot"] = _sub(str(cfg["shot"]), tokens, "shot")
    shot = tokens["shot"]
    if not re.match(r"^[A-Za-z0-9_.-]+$", shot):
        raise ConfigError(f"shot name '{shot}' must be filename-safe")

    opts = {"flatten_mode": "reference_ai_tracking", "project_fps": None, "verify": True, "developer_nk": False,
            "backup_keep": 2}
    opts.update(cfg.get("options") or {})
    if opts["flatten_mode"] not in FLATTEN_MODES:
        raise ConfigError(f"options.flatten_mode must be one of {FLATTEN_MODES}")
    r = {"config": config_path, "shot": shot, "scene": scene, "vars": dict(cfg.get("vars") or {}),
         "inputs": {}, "outputs": {}, "options": opts}

    # ---- inputs (read only, never copied) ------------------------------------------
    I = r["inputs"]
    I["ai_tracking_scene_dir"] = scene_dir
    I["ai_tracking_output"] = ai_out
    I["transforms_json"] = norm(os.path.join(ai_out, f"{scene}_transforms.json"))
    I["transforms_undistorted_json"] = norm(os.path.join(scene_dir, "undistort", "transforms_undistorted.json"))
    I["hip"] = path(inp.get("hip", "{ai_tracking_scene_dir}/{scene}.hip"), "inputs.hip")
    I["tracking_flatten_dir"] = path(inp.get("tracking_flatten_dir", "{ai_tracking_scene_dir}/undistort/images_undistorted"),
                                     "inputs.tracking_flatten_dir")
    I["tracking_flatten_pattern"] = I["tracking_flatten_dir"] + "/frame_%06d.jpg"  # upstream naming
    I["tracking_proxy_dir"] = norm(os.path.join(scene_dir, "images"))
    src = path(inp["source_plate"], "inputs.source_plate")
    if FRAME_PAT.search(os.path.basename(src)):
        I["source_plate"] = norm(os.path.dirname(src))
        I["source_plate_pattern"] = FRAME_PAT.sub(lambda m: m.group(0) if m.group(0).startswith("%")
                                                  else f"%0{len(m.group(0))}d", src)
    else:
        I["source_plate"], I["source_plate_pattern"] = src, None
    missing = [k for k in ("ai_tracking_scene_dir", "transforms_json", "transforms_undistorted_json", "hip",
                           "tracking_flatten_dir", "source_plate") if not os.path.exists(I[k])]
    if missing:
        raise ConfigError("missing inputs:\n  " + "\n  ".join(f"{k}: {I[k]}" for k in missing))
    if os.path.isfile(I["source_plate"]) and os.path.splitext(I["source_plate"])[1].lower() not in VIDEO_EXTS:
        raise ConfigError(f"source_plate is a file but not a video: {I['source_plate']}")

    # ---- outputs ----------------------------------------------------------------
    out = cfg.get("outputs") or {}
    if "export_root" not in out:
        raise ConfigError("outputs.export_root is required")
    O = r["outputs"]
    O["export_root"] = path(out["export_root"], "outputs.export_root")
    tokens["export_root"] = O["export_root"]
    defaults = {"lens_dir": "{export_root}/lens", "maya_dir": "{export_root}/maya",
                "metadata_dir": "{export_root}/metadata", "nuke_dir": "{export_root}/nuke",
                "work_dir": norm(os.path.join(COMPANION_ROOT, "work", shot))}
    for k in OUTPUT_DIRS:
        O[k] = path(out.get(k, defaults[k]), f"outputs.{k}")
    if opts["flatten_mode"] == "render":
        if "production_flatten" not in out:
            raise ConfigError("flatten_mode 'render' needs outputs.production_flatten (frame pattern)")
        pf = path(out["production_flatten"], "outputs.production_flatten")
        if not FRAME_PAT.search(os.path.basename(pf)):
            raise ConfigError("outputs.production_flatten must be a frame pattern (%04d or ####)")
        O["production_flatten"] = FRAME_PAT.sub(lambda m: m.group(0) if m.group(0).startswith("%")
                                                else f"%0{len(m.group(0))}d", pf)
    if _inside(O["work_dir"], O["export_root"]):
        raise ConfigError("outputs.work_dir must not be inside the Artist export (dev / QC data stays out)")

    # never write into AI Tracking (install or scene output), the plate, or the tracking flatten
    guards = [(p, "protected root") for p in protected_roots] + [
        (scene_dir, "AI Tracking scene output"), (I["source_plate"], "source plate folder"),
        (I["tracking_flatten_dir"], "AI Tracking flatten")]
    for k in ("export_root",) + OUTPUT_DIRS + (("production_flatten",) if "production_flatten" in O else ()):
        target = os.path.dirname(O[k]) if k == "production_flatten" else O[k]
        for g, why in guards:
            if _inside(target, g):
                raise ConfigError(f"outputs.{k} is inside the {why}: {O[k]}")

    r["planned"] = planned_files(shot, O)
    existing = [p for k, p in r["planned"].items() if k != "manifest" and os.path.exists(p)]
    if "production_flatten" in O:
        existing += glob.glob(FRAME_PAT.sub("*", O["production_flatten"]))
    if existing and not overwrite:
        raise ConfigError("outputs already exist (use --overwrite):\n  " + "\n  ".join(existing[:10]))
    return r

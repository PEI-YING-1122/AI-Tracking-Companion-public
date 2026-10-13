"""Build a portable Nuke lens package for one AI Tracking shot.

    python build_nuke_package.py --meta companion_meta.json --out-root DIR [--plate copy|relative]

Package layout (everything referenced relative to the .nk):
    <shot>/
        lens/      <shot>_undistort.exr, <shot>_redistort.exr      (production, converged full-res canvas)
                   <shot>_proxy_undistort_qc.exr                   (QC only: tracking proxy space)
        nuke/      <shot>_lens_setup.nk
        metadata/  <shot>_lens.json, <shot>_stmap_meta.json, <shot>_full_maya_camera.json
        plate/     original source (copied; or omitted with --plate relative)
        reference/ tracking_flatten/  (AI Tracking images_undistorted = solve space)
                   tracking_proxy/    (AI Tracking images = solve input, QC only)
        flatten/   <shot>_production_flatten.%04d.exr           (production flatten, half EXR)
        maya/      production camera ABC (primary) / FBX + sidecar, point cloud ABC  (--maya-dir)
        render/    (DELIVERY_OUTPUT placeholder target -- delivery spec is project specific)

Refuses Unsupported scenes (exit 2) before writing anything.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "stmap"))
sys.path.insert(0, os.path.join(ROOT, "common"))
import stmap_core as sc  # noqa: E402
import stmap_generator  # noqa: E402

COMPANION_VERSION = "0.4.0-r1"
import site_config  # noqa: E402

NUKE = site_config.get("nuke")
NK_WRITER = os.path.join(HERE, "nk_writer.py")
FLATTEN_RENDER = os.path.join(HERE, "render_production_flatten.py")
DRIVE_RE = re.compile(r"(?i)(?<![A-Za-z])[A-Z]:[\\/]")


def seq_pattern(files):
    """['x/shot.1001.exr', ...] -> ('shot.%04d.exr', first, last); None if not one padded pattern."""
    names = [os.path.basename(f) for f in files]
    m = re.match(r"^(.*?)(\d+)(\.[^.]+)$", names[0])
    if not m:
        return None
    pre, digits, ext = m.groups()
    nums = []
    for n in names:
        mm = re.match(rf"^{re.escape(pre)}(\d{{{len(digits)}}}){re.escape(ext)}$", n)
        if not mm:
            return None
        nums.append(int(mm.group(1)))
    return f"{pre}%0{len(digits)}d{ext}", min(nums), max(nums)


def copy_tree_files(files, dst):
    os.makedirs(dst, exist_ok=True)
    for f in files:
        shutil.copy2(f, os.path.join(dst, os.path.basename(f)))


def write_nk(lens_json, nk, nuke=None, path_mode="relative"):
    """Run nk_writer.py in Nuke, strip machine-specific header strings, audit paths.

    relative: no drive letter may remain anywhere in the script.
    absolute: every file knob must be an absolute path (shot assets resolved per run).
    """
    nuke = nuke or NUKE
    os.makedirs(os.path.dirname(nk), exist_ok=True)
    graph = (json.load(open(lens_json)).get("_nuke") or {}).get("graph")
    writer = os.path.join(HERE, "nk_writer_artist.py") if graph == "artist" else NK_WRITER
    r = subprocess.run([nuke, "-t", writer, lens_json, nk], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(nk):
        raise RuntimeError("nk_writer failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
    if os.path.exists(nk + "~"):  # Nuke's own backup when saving over an existing script
        os.remove(nk + "~")
    # strip machine-specific strings Nuke embeds on save (shebang + Root name)
    text = open(nk, encoding="utf-8").read().splitlines()
    clean = []
    for i, line in enumerate(text):
        if i == 0 and line.startswith("#!"):
            line = "#! nuke -nx"
        if re.match(r"^\s*name\s+\S*[\\/]", line) and clean and clean[-1].strip().startswith(("inputs 0", "Root {")):
            continue  # Root's "name <script path>"; Nuke sets it from the opened file
        clean.append(line)
    open(nk, "w", encoding="utf-8", newline="\n").write("\n".join(clean) + "\n")
    files = re.findall(r'^\s*file\s+"?([^"\n]+)"?', "\n".join(clean), re.M)
    if path_mode == "relative":
        hits = [l for l in clean if DRIVE_RE.search(l)]
        if hits:
            raise RuntimeError(f".nk still contains absolute paths: {hits[:5]}")
    else:
        rel = [f for f in files if not (DRIVE_RE.match(f) or f.startswith("//"))]
        if rel:
            raise RuntimeError(f"absolute-path .nk has relative file knobs: {rel}")
    return r


def _tcl_quote(path):
    if re.fullmatch(r"[A-Za-z0-9_./:\\-]+", path):
        return path
    return '"' + re.sub(r'([\\"\[\]$])', r"\\\1", path) + '"'


def finalize_root_name(nk, final_path):
    """Set the Root 'name' of a .nk written in the stage to its final delivery path.
    Nuke records the path it saved to (the stage) as Root name -- some versions in a form the
    header clean-up above does not catch.  Only the Root block's own name knob is touched; every
    other reference (Read files, ...) stays as written, so the stage-leak validation still sees it."""
    lines = open(nk, encoding="utf-8").read().replace("\r\n", "\n").split("\n")
    start, end, depth_at = _root_block(lines)
    if start is None:
        raise RuntimeError(f"no Root block in {nk}")
    final = final_path.replace(os.sep, "/")
    value = f" name {_tcl_quote(final)}"
    # every name knob of the Root itself (depth 1), wherever Nuke put it; nested values untouched
    body = [i for i in range(start + 1, end) if depth_at[i] == 1 and re.match(r"^\s*name(\s|$)", lines[i])]
    first = next((i for i in range(start + 1, end) if depth_at[i] == 1 and lines[i].strip() == "inputs 0"), None)
    for i in reversed(body):
        del lines[i]
    at = start + 1
    if first is not None:
        at = first + 1 - sum(1 for i in body if i < first)
    lines.insert(at, value)
    open(nk, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    names = root_names(nk)
    if names != [final]:  # never hand an ambiguous Root to validation / the Artist
        raise RuntimeError(f"Root name finalisation failed: {names}")
    return value.strip()


def _root_block(lines):
    """(first line, closing line, brace depth at the start of every line) of the top-level Root block.
    TCL rules, as Nuke parses the node body (a braced word): every brace counts except
    backslash-escaped ones; double quotes do not hide braces."""
    depth, start, depth_at = 0, None, []
    for i, ln in enumerate(lines):
        depth_at.append(depth)
        if start is None and depth == 0 and re.match(r"^\s*Root\s*\{\s*$", ln):
            start = i
        esc = False
        for ch in ln:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if start is not None and depth == 0:
                    return start, i, depth_at + [depth] * (len(lines) - i - 1)
    return None, None, depth_at


def root_names(nk):
    """values of the Root block's own name knobs (unquoted)"""
    lines = open(nk, encoding="utf-8").read().replace("\r\n", "\n").split("\n")
    start, end, depth_at = _root_block(lines)
    if start is None:
        return []
    out = []
    for i in range(start + 1, end):
        m = re.match(r"^\s*name(?:\s+(.*))?$", lines[i]) if depth_at[i] == 1 else None
        if m:
            v = (m.group(1) or "").strip()
            if len(v) >= 2 and v[0] == v[-1] == '"':
                v = re.sub(r"\\(.)", r"\1", v[1:-1])
            elif len(v) >= 2 and v[0] == "{" and v[-1] == "}":
                v = v[1:-1]
            out.append(v)
    return out


def build(meta_path, out_root, plate_mode="copy", solver="converged", nuke=NUKE, maya_dir=None,
          render_flatten=True):
    meta = json.load(open(meta_path))
    if not meta["support"]["supported"]:
        raise stmap_generator.Unsupported("; ".join(meta["support"]["reasons"]))
    if solver != "converged":
        print("[WARN] legacy redistort solver: debug package, not for delivery")
    tj = json.load(open(meta["transforms_json"]))
    why = sc.unsupported_reason(sc.Camera(tj), tj)  # second guard, before any write
    if why:
        raise stmap_generator.Unsupported(why)
    shot = meta["scene_name"]
    pkg = os.path.join(os.path.abspath(out_root), shot)
    nk_dir = os.path.join(pkg, "nuke")
    if os.path.exists(pkg):
        shutil.rmtree(pkg)
    for d in ("lens", "nuke", "metadata", "reference"):
        os.makedirs(os.path.join(pkg, d))

    # --- STMaps (production = full-res, converged) ---------------------------------
    tmp = os.path.join(pkg, "lens", "_gen")
    smeta = stmap_generator.build(meta, tmp, norm="center", solver=solver)
    lens = {
        "undistort": f"{shot}_undistort.exr",
        "redistort": f"{shot}_redistort.exr",
        "proxy_undistort_qc": f"{shot}_proxy_undistort_qc.exr",
    }
    shutil.move(smeta["files"]["full_undistort"], os.path.join(pkg, "lens", lens["undistort"]))
    shutil.move(smeta["files"]["full_redistort"], os.path.join(pkg, "lens", lens["redistort"]))
    shutil.move(smeta["files"]["proxy_undistort"], os.path.join(pkg, "lens", lens["proxy_undistort_qc"]))
    shutil.move(smeta["files"]["full_maya_camera"], os.path.join(pkg, "metadata", f"{shot}_full_maya_camera.json"))
    shutil.move(os.path.join(tmp, f"{shot}_stmap_meta.json"), os.path.join(pkg, "metadata", f"{shot}_stmap_meta.json"))
    shutil.rmtree(tmp)  # proxy redistort is not part of the package

    # --- plate -------------------------------------------------------------------
    src = meta["source"]
    if src["kind"] == "video":
        plate_files = [src["path"]]
        plate_name = os.path.basename(src["path"])
        plate_first, plate_last = src["source_first_frame"], src["source_last_frame"]
    else:
        exts = {"exr_sequence": (".exr",), "jpg_sequence": (".jpg", ".jpeg"), "png_sequence": (".png",)}[src["kind"]]
        plate_files = sorted(f for f in glob.glob(os.path.join(src["path"], "*")) if os.path.splitext(f)[1].lower() in exts)
        pat = seq_pattern(plate_files)
        if pat is None:
            raise stmap_generator.Unsupported("source sequence is not a single padded file pattern")
        plate_name, plate_first, plate_last = pat
    if plate_mode == "copy":
        sub = "plate" if src["kind"] == "video" else os.path.join("plate", os.path.basename(os.path.normpath(src["path"])))
        copy_tree_files(plate_files, os.path.join(pkg, sub))
        plate_rel = os.path.relpath(os.path.join(pkg, sub, plate_name), nk_dir)
    else:
        base = src["path"] if src["kind"] == "video" else os.path.join(src["path"], plate_name)
        try:
            plate_rel = os.path.relpath(base, nk_dir)
        except ValueError:
            raise SystemExit("--plate relative needs the source on the same drive as the package")

    # --- tracking references (solve space) -----------------------------------------
    scene_dir = meta["scene_dir"]
    flat = sorted(glob.glob(os.path.join(scene_dir, "undistort", "images_undistorted", "frame_*.jpg")))
    prox = sorted(glob.glob(os.path.join(scene_dir, "images", "frame_*.jpg")))
    copy_tree_files(flat, os.path.join(pkg, "reference", "tracking_flatten"))
    copy_tree_files(prox, os.path.join(pkg, "reference", "tracking_proxy"))

    # --- lens metadata -----------------------------------------------------------------
    pc = smeta["proxy"]["camera"]
    fc = smeta["full"]["camera"]
    tr = meta["tracking"]
    off = tr["frame_offset_tracking_to_source"] or 0
    lj = {
        "schema": "ai_tracking_companion.lens/1",
        "companion_version": COMPANION_VERSION,
        "shot": shot,
        "source": {"kind": src["kind"], "file": os.path.basename(src["path"]) if src["kind"] == "video" else plate_name,
                   "resolution": [src["width"], src["height"]],
                   "first_frame": src["source_first_frame"], "last_frame": src["source_last_frame"],
                   "frame_numbering": src["frame_numbering"],
                   "fps": src["fps"], "fps_rational": src.get("fps_rational"), "fps_source": src["fps_source"]},
        "tracking": {"proxy_resolution": [tr["proxy_width"], tr["proxy_height"]],
                     "proxy_undistorted_resolution": smeta["proxy"]["canvas"][:2],
                     "proxy_undistorted_principal_point": smeta["proxy"]["canvas"][2:],
                     "space_note": "AI Tracking proxy space (HIP, proxy flatten, solve) -- unchanged; QC/reference only",
                     "first_frame": tr["tracking_first_frame"], "last_frame": tr["tracking_last_frame"],
                     "first_frame_in_source_numbering": tr["source_frame_of_tracking_first"],
                     "last_frame_in_source_numbering": tr["source_frame_of_tracking_last"],
                     "frame_offset_tracking_to_source": off,
                     "unregistered_frames": tr["unregistered_frames"]},
        "production_canvas": {"resolution": smeta["full"]["canvas"][:2],
                              "principal_point": smeta["full"]["canvas"][2:],
                              "rule": smeta["full_canvas_rule"],
                              "legacy_full_canvas_info_only": smeta["legacy_full_canvas_info_only"],
                              "proxy_canvas_x_scale_info_only": smeta["proxy_canvas_scaled_to_full"],
                              "maya_camera": f"metadata/{shot}_full_maya_camera.json"},
        "camera": {"colmap_model": meta["camera"]["colmap_cameras"][0]["model"],
                   "opencv_model": "OPENCV (k1 k2 p1 p2 k3 k4) as undistortionNerfstudioColmap.py",
                   "full_res": {"fx": fc["fl_x"], "fy": fc["fl_y"], "cx": fc["cx"], "cy": fc["cy"],
                                "focal_mm": smeta["full"]["filmback"]["focal_mm"],
                                "sensor_width_mm_assumed": 36.0},
                   "proxy": {"fx": pc["fl_x"], "fy": pc["fl_y"], "cx": pc["cx"], "cy": pc["cy"]},
                   "distortion": {k: pc[k] for k in ("k1", "k2", "k3", "k4", "p1", "p2")},
                   "principal_point_convention": "COLMAP cx/cy used as OpenCV pixel-index centre (as upstream)"},
        "stmap": {"convention": {"U": "(col + 0.5) / W",
                                 "V_top_origin_row": "1 - (row + 0.5) / H",
                                 "V_nuke_bottom_origin": "(y_nuke + 0.5) / H",
                                 "note": "same map; Nuke applies no extra Y flip. Never plug a top-origin row "
                                         "into the y_nuke form."},
                  "channels": "R=U G=V", "dtype": "32-bit float EXR", "data": "DATA -- read raw, no colour transform",
                  "nuke_inputs": "STMap input0=src (via Crop black outside), input1=stmap, uv=rgb",
                  "undistort": {"file": f"lens/{lens['undistort']}", "size": smeta["full"]["canvas"][:2],
                                "samples": "original full-res plate"},
                  "redistort": {"file": f"lens/{lens['redistort']}", "size": smeta["full"]["plate"],
                                "samples": "full-res undistorted canvas"},
                  "proxy_undistort_qc": {"file": f"lens/{lens['proxy_undistort_qc']}", "size": smeta["proxy"]["canvas"][:2],
                                         "use": "QC only: tracking proxy -> tracking flatten"}},
        "redistort_solver": solver,
        "production_flatten": {"file": f"flatten/{shot}_production_flatten.%04d.exr",
                               "made_from": "original full-res plate -> production undistort STMap (Nuke, Keys)",
                               "resolution": smeta["full"]["canvas"][:2], "frames": [src["source_first_frame"], src["source_last_frame"]],
                               "encoding": "EXR 16-bit half, ZIP, Nuke linear working space"},
        "delivery_output": {"status": "placeholder -- set per project delivery specification",
                            "note": "Write uses Nuke defaults; Companion does not define the comp render spec"},
        "winy_mode": "corrected",
        "paths": {"nk": f"nuke/{shot}_lens_setup.nk",
                  "plate": os.path.relpath(os.path.join(nk_dir, plate_rel), pkg).replace("\\", "/") if plate_mode == "copy" else plate_rel.replace("\\", "/"),
                  "plate_mode": plate_mode,
                  "tracking_flatten": "reference/tracking_flatten/frame_%06d.jpg",
                  "tracking_proxy": "reference/tracking_proxy/frame_%06d.jpg",
                  "delivery_output": f"render/{shot}_comp.%04d.exr"},
        "_nuke": {  # consumed by nk_writer.py (paths relative to the .nk directory)
            "plate": plate_rel.replace("\\", "/"), "plate_first": plate_first, "plate_last": plate_last,
            "stmap_undistort": f"../lens/{lens['undistort']}", "stmap_redistort": f"../lens/{lens['redistort']}",
            "stmap_proxy_qc": f"../lens/{lens['proxy_undistort_qc']}",
            "tracking_reference_flatten": "../reference/tracking_flatten/frame_%06d.jpg",
            "production_flatten": f"../flatten/{shot}_production_flatten.%04d.exr",
            "proxy": "../reference/tracking_proxy/frame_%06d.jpg",
            "track_first": 1, "track_last": tr["extracted_frames"],
            "delivery": f"../render/{shot}_comp.%04d.exr",
        },
    }
    lens_json = os.path.join(pkg, "metadata", f"{shot}_lens.json")
    json.dump(lj, open(lens_json, "w"), indent=1)

    # --- .nk written by Nuke itself (guaranteed-valid syntax and wiring) ---------------
    nk = os.path.join(nk_dir, f"{shot}_lens_setup.nk")
    r = write_nk(lens_json, nk, nuke, path_mode="relative")

    # --- production flatten, rendered by the package's own graph ----------------------
    if render_flatten:
        r2 = subprocess.run([nuke, "-t", FLATTEN_RENDER, nk, f"range={src['source_first_frame']},{src['source_last_frame']}"],
                            capture_output=True, text=True)
        n_out = len(glob.glob(os.path.join(pkg, "flatten", "*.exr")))
        if r2.returncode != 0 or n_out != src["source_last_frame"] - src["source_first_frame"] + 1:
            raise RuntimeError("production flatten render failed:\n" + r2.stdout[-3000:] + r2.stderr[-3000:])

    # --- Maya production delivery (optional) -----------------------------------------
    if maya_dir:
        md = os.path.join(pkg, "maya")
        os.makedirs(md)
        want = [f"{shot}_cam_corrected.abc", f"{shot}_cam_corrected.fbx", f"{shot}_cam_corrected.maya_camera.json",
                f"{shot}_points.abc"]
        for f in want:
            shutil.copy2(os.path.join(maya_dir, f), os.path.join(md, f))
        shutil.copy2(os.path.join(ROOT, "maya_export", "maya_apply_sidecar.py"), os.path.join(md, "maya_apply_sidecar.py"))
        shutil.copy2(os.path.join(ROOT, "maya_export", "load_production_in_maya.py"), os.path.join(md, "load_production_in_maya.py"))
        side = json.load(open(os.path.join(md, f"{shot}_cam_corrected.maya_camera.json")))
        if side.get("resolution_kind") != "production_full_canvas" or side["resolution"] != smeta["full"]["canvas"][:2]:
            raise RuntimeError(f"maya camera is not on the production canvas: {side.get('resolution')}")
    return {"package": pkg, "nk": nk, "lens_json": lens_json, "nk_writer_log": r.stdout[-2000:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--plate", choices=("copy", "relative"), default="copy")
    ap.add_argument("--redistort-solver", choices=sc.REDISTORT_SOLVERS, default="converged",
                    help="legacy = debug only, never delivery")
    ap.add_argument("--nuke", default=NUKE)
    ap.add_argument("--maya-dir", help="production Maya export dir (run_maya_export --production-canvas) to include")
    ap.add_argument("--no-flatten", action="store_true", help="skip rendering the production flatten")
    a = ap.parse_args()
    try:
        res = build(a.meta, a.out_root, a.plate, a.redistort_solver, a.nuke, a.maya_dir, not a.no_flatten)
    except stmap_generator.Unsupported as e:
        print(f"UNSUPPORTED -- no Nuke package produced: {e}")
        sys.exit(2)
    print(json.dumps({k: v for k, v in res.items() if k != "nk_writer_log"}, indent=1))


if __name__ == "__main__":
    main()

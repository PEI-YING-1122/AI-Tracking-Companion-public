"""Generate Nuke STMaps (float32 EXR) from an AI Tracking scene.

    python stmap_generator.py --meta companion_meta.json --out-dir DIR [--norm center]

Writes (all R=s, G=t, origin bottom-left, 32-bit float):
    <scene>_proxy_undistort_stmap.exr   proxy canvas  -> samples proxy plate
    <scene>_proxy_redistort_stmap.exr   proxy plate   -> samples proxy canvas
    <scene>_full_undistort_stmap.exr    full canvas   -> samples full plate
    <scene>_full_redistort_stmap.exr    full plate    -> samples full canvas
    <scene>_stmap_meta.json             intrinsics, canvases, filmback, checks
Refuses (exit 2) on Unsupported scenes; nothing is written then.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stmap_core as sc  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "maya_export"))
from maya_units import maya_time_unit  # noqa: E402


class Unsupported(Exception):
    pass


def build(meta, out_dir, norm="center", sensor_width_mm=36.0, solver="converged"):
    if not meta["support"]["supported"]:
        raise Unsupported("; ".join(meta["support"]["reasons"]))
    with open(meta["transforms_json"]) as f:
        tj = json.load(f)
    with open(meta["transforms_undistorted_json"]) as f:
        uj = json.load(f)
    cam = sc.Camera(tj)
    why = sc.unsupported_reason(cam, tj)
    if why:
        raise Unsupported(why)

    # crop vs expand: the undistorted JSON tells which rule upstream used
    nw, nh, ncx, ncy = sc.canvas(cam, crop=False)
    crop = (int(uj["w"]), int(uj["h"]), float(uj["cx"]), float(uj["cy"])) == (cam.w, cam.h, cam.cx, cam.cy) \
        and (nw, nh) != (cam.w, cam.h)
    if crop:
        nw, nh, ncx, ncy = sc.canvas(cam, crop=True)
    proxy_check = {
        "recomputed": [nw, nh, ncx, ncy],
        "transforms_undistorted": [int(uj["w"]), int(uj["h"]), float(uj["cx"]), float(uj["cy"])],
    }
    proxy_check["match"] = (nw == proxy_check["transforms_undistorted"][0] and nh == proxy_check["transforms_undistorted"][1]
                            and math.isclose(ncx, uj["cx"], abs_tol=1e-9) and math.isclose(ncy, uj["cy"], abs_tol=1e-9))
    if not proxy_check["match"]:
        raise SystemExit(f"[ERROR] proxy canvas does not reproduce upstream: {proxy_check}")

    W, H = int(meta["source"]["width"]), int(meta["source"]["height"])
    full = cam.scaled(W, H)
    # production space: converged canvas (Revision 01); legacy full canvas kept for reference only
    fw, fh, fcx, fcy = sc.canvas(full, crop=crop, solver="converged")
    legacy_full = sc.canvas(full, crop=crop, solver="legacy")

    os.makedirs(out_dir, exist_ok=True)
    scene = meta["scene_name"]
    paths = {}

    def emit(tag, mx, my, src_w, src_h):
        s, t = sc.to_stmap(mx, my, src_w, src_h, norm)
        p = os.path.join(out_dir, f"{scene}_{tag}_stmap.exr")
        sc.write_stmap_exr(p, s, t)
        paths[tag] = p

    emit("proxy_undistort", *sc.undistort_map(cam, nw, nh, ncx, ncy), cam.w, cam.h)
    emit("proxy_redistort", *sc.redistort_map(cam, ncx, ncy, solver), nw, nh)
    emit("full_undistort", *sc.undistort_map(full, fw, fh, fcx, fcy), W, H)
    emit("full_redistort", *sc.redistort_map(full, fcx, fcy, solver), fw, fh)

    sx, sy = W / cam.w, H / cam.h

    def filmback(c, cw, ch, ccx, ccy):
        # same formulas build_houdini_scene.py uses, plus the corrected winy
        return {"focal_mm": c.fl_x / c.w * sensor_width_mm,
                "aperture_mm": sensor_width_mm * cw / c.w,
                "resx": cw, "resy": ch,
                "winx": (cw / 2 - ccx) / cw,
                "winy_upstream": (ch / 2 - ccy) / cw,
                "winy_corrected": (ccy - ch / 2) / ch}

    out = {
        "schema": "ai_tracking_companion.stmap/1",
        "scene_name": scene,
        "normalisation": norm,
        "redistort_solver": solver,
        "nuke_setup": "STMap input0=src (Crop black-outside recommended), input1=stmap, uv=rgb; filter Keys/Mitchell for least resampling bias",
        "mode": "crop" if crop else "expand",
        "upstream_undistort_sha256": sc.upstream_sha256(),
        "proxy": {"camera": cam.as_dict(), "canvas": [nw, nh, ncx, ncy], "check": proxy_check,
                  "filmback": filmback(cam, nw, nh, ncx, ncy)},
        "full": {"plate": [W, H], "scale": [sx, sy], "camera": full.as_dict(),
                 "canvas": [fw, fh, fcx, fcy], "filmback": filmback(full, fw, fh, fcx, fcy)},
        "proxy_canvas_scaled_to_full": [nw * sx, nh * sy, ncx * sx, ncy * sy],
        "full_canvas_rule": "upstream expanded-canvas rule with converged inverse (production)",
        "legacy_full_canvas_info_only": list(legacy_full),
        "stmap_convention": "U=(col+0.5)/W; V=1-(row+0.5)/H for top-origin rows == (y_nuke+0.5)/H; no Nuke Y flip",
        "stmap_dtype": "32-bit float EXR, data (no colour transform)",
        "files": paths,
    }
    # Maya camera for the FULL-RES undistorted canvas.  The CG render must match
    # this canvas, which can differ from (proxy canvas x scale) by a pixel or two.
    fb = out["full"]["filmback"]
    hfa = fb["aperture_mm"] / 25.4
    vfa = fb["aperture_mm"] * fh / fw / 25.4
    fps = float(meta["source"]["fps"])
    off = meta["tracking"]["frame_offset_tracking_to_source"] or 0
    side = {"schema": "ai_tracking_companion.maya_camera/1", "winy_mode": "corrected",
            "resolution": [fw, fh], "resolution_kind": "full_undistorted_canvas",
            "fps": fps, "fps_source": meta["source"]["fps_source"], "maya_time_unit": maya_time_unit(fps),
            "frame_start": meta["tracking"]["tracking_first_frame"] + off,
            "frame_end": meta["tracking"]["tracking_last_frame"] + off,
            "focalLength_mm": fb["focal_mm"],
            "horizontalFilmAperture_in": hfa, "verticalFilmAperture_in": vfa,
            "horizontalFilmOffset_in": fb["winx"] * hfa,
            "verticalFilmOffset_in": fb["winy_corrected"] * vfa}
    side_path = os.path.join(out_dir, f"{scene}_full_maya_camera.json")
    with open(side_path, "w") as f:
        json.dump(side, f, indent=1)
    out["files"]["full_maya_camera"] = side_path
    with open(os.path.join(out_dir, f"{scene}_stmap_meta.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--norm", choices=sc.NORMALISATIONS, default="center")
    ap.add_argument("--sensor-width-mm", type=float, default=36.0)
    ap.add_argument("--redistort-solver", choices=sc.REDISTORT_SOLVERS, default="converged",
                    help="converged = production (default); legacy = restore_distortion.py behaviour, debug only")
    a = ap.parse_args()
    with open(a.meta) as f:
        meta = json.load(f)
    try:
        out = build(meta, a.out_dir, a.norm, a.sensor_width_mm, a.redistort_solver)
    except Unsupported as e:
        print(f"UNSUPPORTED -- no STMap produced: {e}")
        sys.exit(2)
    print(json.dumps({k: out[k] for k in ("mode", "proxy", "full", "files")}, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()

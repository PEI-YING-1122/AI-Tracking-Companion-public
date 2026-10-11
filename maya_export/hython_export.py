"""Headless Houdini -> Maya delivery export.  Run with hython, never with plain python.

    hython hython_export.py --hip scene.hip --meta companion_meta.json --out-dir DIR
                            [--winy-mode corrected|original] [--no-fps] [--no-frame-offset]

Load HIP -> in-memory modification -> export -> exit.  The HIP is NEVER saved:
this script contains no hou.hipFile.save* call, and the driver verifies the
HIP's sha256 before/after.

Outputs in --out-dir:
    <scene>_cam_<mode>.fbx        camera only, no unit/axis conversion
    <scene>_cam_<mode>.abc        same camera as Alembic (QC reference)
    <scene>_points.abc            point cloud (only written when --with-points)
    houdini_reference_<mode>.json per-frame Houdini world matrices + lens values
"""
import argparse
import hashlib
import json
import math
import os
import sys

import hou

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maya_units import maya_time_unit  # noqa: E402

CAM_PATH = "/obj/NeRF_Import/Nerfstudio_Animated_Cam"
PTS_PATH = "/obj/NeRF_Import/Scene/COLMAP_to_Houdini"
SCENE_GEO = "/obj/NeRF_Import/Scene"
XFORM_PARMS = ("tx", "ty", "tz", "rx", "ry", "rz")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def winy_formulas(w, h, cy):
    return {
        "upstream": (h / 2.0 - cy) / w,     # build_houdini_scene.py
        "corrected": (cy - h / 2.0) / h,    # per-axis normalised, NDC y-up
    }


def shift_keys(parm, offset):
    keys = parm.keyframes()
    parm.deleteAllKeyframes()
    for k in keys:
        k.setFrame(k.frame() + offset)
        parm.setKeyframe(k)


def key_range(cam):
    frames = sorted({k.frame() for p in XFORM_PARMS for k in cam.parm(p).keyframes()})
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hip", required=True)
    ap.add_argument("--meta", required=True, help="companion_meta.json")
    ap.add_argument("--out-dir", required=True)
    # corrected = Companion default (validated in TEST 01B); original = HIP value, QC only
    ap.add_argument("--winy-mode", choices=("corrected", "original"), default="corrected")
    ap.add_argument("--with-points", action="store_true")
    ap.add_argument("--production-canvas", metavar="STMAP_META",
                    help="*_stmap_meta.json: re-derive the lens for the converged full-res production canvas "
                         "(memory only). Without it the camera stays in tracking (proxy) space.")
    ap.add_argument("--no-fps", action="store_true", help="keep HIP fps (24) instead of source fps")
    ap.add_argument("--no-frame-offset", action="store_true")
    a = ap.parse_args()

    with open(a.meta) as f:
        meta = json.load(f)
    if not meta["support"]["supported"]:
        print("UNSUPPORTED: " + "; ".join(meta["support"]["reasons"]))
        sys.exit(2)

    hip = os.path.abspath(a.hip)
    hip_hash_before = sha256(hip)
    os.makedirs(a.out_dir, exist_ok=True)
    scene = meta["scene_name"]

    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    cam = hou.node(CAM_PATH)
    pts = hou.node(PTS_PATH)
    if cam is None or pts is None:
        print(f"[ERROR] expected nodes missing: cam={cam} pts={pts}")
        sys.exit(1)

    hip_fps = hou.fps()
    hip_frames = key_range(cam)
    hip_range = (hip_frames[0], hip_frames[-1])

    # --- lens: recompute what build_houdini_scene.py should have written ---------
    with open(meta["transforms_undistorted_json"]) as f:
        uj = json.load(f)
    w, h = float(uj["w"]), float(uj["h"])
    cx, cy = float(uj["cx"]), float(uj["cy"])
    winy_hip = cam.parm("winy").eval()
    forms = winy_formulas(w, h, cy)
    if not math.isclose(winy_hip, forms["upstream"], rel_tol=0, abs_tol=1e-9):
        print(f"[ERROR] HIP winy {winy_hip!r} does not match upstream formula {forms['upstream']!r}")
        sys.exit(1)
    winx_expected = (w / 2.0 - cx) / w
    if not math.isclose(cam.parm("winx").eval(), winx_expected, abs_tol=1e-9):
        print(f"[ERROR] HIP winx {cam.parm('winx').eval()!r} != {winx_expected!r}")
        sys.exit(1)

    if a.winy_mode == "corrected":
        cam.parm("winy").set(forms["corrected"])  # memory only

    space = "tracking_proxy"
    if a.production_canvas:
        # Production full-res space (Revision 01): same transforms, lens re-derived for
        # the converged canvas with build_houdini_scene's formulas (+ corrected winy).
        with open(a.production_canvas) as f:
            sm = json.load(f)
        fb = sm["full"]["filmback"]
        w, h = float(fb["resx"]), float(fb["resy"])
        cx, cy = float(sm["full"]["canvas"][2]), float(sm["full"]["canvas"][3])
        cam.parm("resx").set(fb["resx"])
        cam.parm("resy").set(fb["resy"])
        cam.parm("aperture").set(fb["aperture_mm"])
        cam.parm("focal").set(fb["focal_mm"])
        cam.parm("winx").set(fb["winx"])
        cam.parm("winy").set(fb["winy_corrected"] if a.winy_mode == "corrected" else fb["winy_upstream"])
        forms = winy_formulas(w, h, cy)
        space = "production_full_canvas"

    # --- frame numbering (memory only) --------------------------------------------
    offset = 0
    if not a.no_frame_offset:
        offset = int(meta["tracking"]["frame_offset_tracking_to_source"] or 0)
        if offset:
            for p in XFORM_PARMS:
                shift_keys(cam.parm(p), offset)
    frames = key_range(cam)
    f1, f2 = frames[0], frames[-1]
    hou.playbar.setFrameRange(f1, f2)
    hou.playbar.setPlaybackRange(f1, f2)
    hou.setFrame(f1)
    src_fps = float(meta["source"]["fps"])

    tag = a.winy_mode
    out = {k: os.path.join(a.out_dir, v).replace("\\", "/") for k, v in {
        "fbx": f"{scene}_cam_{tag}.fbx",
        "cam_abc": f"{scene}_cam_{tag}.abc",
        "points_abc": f"{scene}_points.abc",
        "points_npz": f"{scene}_points.npz",
        "reference": f"houdini_reference_{tag}.json",
        "sidecar": f"{scene}_cam_{tag}.maya_camera.json",
    }.items()}

    rop_net = hou.node("/out")

    # --- camera FBX --------------------------------------------------------------
    # Written at the HIP fps (24) so FBX key k sits exactly on frame k: Houdini
    # 20.0.547 shifts the first key by ~0.918 frame when fps is 23.976 (measured,
    # see test_01 report).  Maya then switches to the source fps with
    # updateAnimation=False.  The point-cloud geo is hidden: FBX = camera only.
    hou.node(SCENE_GEO).setDisplayFlag(False)
    r = rop_net.createNode("filmboxfbx", "companion_cam_fbx")
    r.parm("trange").set(1)
    r.parmTuple("f").set((f1, f2, 1))
    r.parm("sopoutput").set(out["fbx"])
    r.parm("startnode").set("/obj/NeRF_Import")
    r.parm("createsubnetroot").set(0)
    r.parm("invisobj").set("nonodes")
    r.parm("convertunits").set(0)   # numeric world-space must stay identical
    r.parm("convertaxis").set(0)
    r.parm("exportkind").set(1)     # ASCII: inspectable
    r.render()

    hou.node(SCENE_GEO).setDisplayFlag(True)
    fbx_fps = hou.fps()

    # --- Alembic exports at the real source fps (memory only) ---------------------
    if not a.no_fps:
        # keep every key on its frame; only the frame->seconds mapping changes
        hou.setFps(src_fps, modify_frame_count=False, preserve_keyframes=True, preserve_frame_start=True)
        hou.playbar.setFrameRange(f1, f2)
        hou.playbar.setPlaybackRange(f1, f2)
        hou.setFrame(f1)


    # --- point cloud Alembic (static, current frame) ------------------------------
    if a.with_points:
        r = rop_net.createNode("alembic", "companion_points_abc")
        r.parm("trange").set(0)
        r.parm("filename").set(out["points_abc"])
        r.parm("format").set("ogawa")
        r.parm("use_sop_path").set(1)
        r.parm("sop_path").set(PTS_PATH)
        r.render()
        rb = hou.node("/obj").createNode("geo", "companion_abc_readback").createNode("alembic")
        rb.parm("fileName").set(out["points_abc"])
        rb.parm("loadmode").set("unpack")
        rb_geo = rb.geometry()
        src = pts.geometry()
        a_pts = [p.position() for p in src.points()]
        b_pts = [p.position() for p in rb_geo.points()]
        readback = {"src_count": len(a_pts), "abc_count": len(b_pts),
                    "abc_point_attribs": [x.name() for x in rb_geo.pointAttribs()],
                    "max_abs_pos_diff": max((max(abs(u[i] - v[i]) for i in range(3)) for u, v in zip(a_pts, b_pts)), default=None)}
        if src.findPointAttrib("Cd") and rb_geo.findPointAttrib("Cd"):
            ca = src.pointFloatAttribValues("Cd")
            cb = rb_geo.pointFloatAttribValues("Cd")
            readback["max_abs_Cd_diff"] = max(abs(x - y) for x, y in zip(ca, cb)) if len(ca) == len(cb) else "length mismatch"
        rb.parent().destroy()

        # compact point data for the Maya-native importer: P and Cd only, full count
        import numpy as np
        P_arr = np.frombuffer(src.pointFloatAttribValuesAsString("P"), dtype=np.float32).reshape(-1, 3)
        arrays = {"P": P_arr}
        if src.findPointAttrib("Cd"):
            arrays["Cd"] = np.frombuffer(src.pointFloatAttribValuesAsString("Cd"), dtype=np.float32).reshape(-1, 3)
        np.savez_compressed(out["points_npz"], **arrays)
        back = np.load(out["points_npz"])
        readback["npz"] = {"count": int(back["P"].shape[0]), "keys": sorted(back.files),
                           "P_dtype": str(back["P"].dtype),
                           "max_abs_P_diff": float(np.abs(back["P"] - P_arr).max()) if len(P_arr) else 0.0,
                           "max_abs_Cd_diff": float(np.abs(back["Cd"] - arrays["Cd"]).max()) if "Cd" in arrays else None,
                           "bbox": [P_arr.min(0).tolist(), P_arr.max(0).tolist()] if len(P_arr) else None}

    # --- camera Alembic (QC reference: Alembic camera schema carries film offset) --
    r = rop_net.createNode("alembic", "companion_cam_abc")
    r.parm("trange").set(1)
    r.parmTuple("f").set((f1, f2, 1))
    r.parm("filename").set(out["cam_abc"])
    r.parm("format").set("ogawa")
    r.parm("root").set("/obj/NeRF_Import")
    r.parm("objects").set(cam.path())  # must be a full path; a bare name exports nothing
    r.render()

    # --- reference dump (Houdini ground truth for Maya QC) -----------------------
    ref_frames = []
    for fr in frames:
        t = hou.frameToTime(fr)
        m = cam.worldTransformAtTime(t)
        ref_frames.append({"frame": fr, "world": [list(row) for row in m.asTupleOfTuples()],
                           "r": list(cam.parmTuple("r").evalAtFrame(fr))})
    geo = pts.geometry()
    P = [p.position() for p in geo.points()]
    stride = max(1, len(P) // 2000)
    ref = {
        "hip": hip, "hip_sha256": hip_hash_before, "winy_mode": tag,
        "hip_fps": hip_fps, "fbx_fps": fbx_fps, "abc_fps": hou.fps(), "source_fps": src_fps,
        "fps_source": meta["source"]["fps_source"], "points_readback": readback if a.with_points else None,
        "hip_key_range": hip_range, "export_key_range": [f1, f2], "frame_offset": offset,
        "key_frames": frames,
        "space": space, "canvas_w": w, "canvas_h": h, "cx": cx, "cy": cy,
        "focal": cam.parm("focal").eval(), "aperture": cam.parm("aperture").eval(),
        "resx": cam.parm("resx").eval(), "resy": cam.parm("resy").eval(),
        "aspect": cam.parm("aspect").eval(),
        "winx": cam.parm("winx").eval(), "winy": cam.parm("winy").eval(),
        "winy_upstream": forms["upstream"], "winy_corrected": forms["corrected"],
        "winsizex": cam.parm("winsizex").eval(), "winsizey": cam.parm("winsizey").eval(),
        "projection": cam.parm("projection").evalAsString(),
        "point_count": len(P),
        "point_attribs": [a_.name() for a_ in geo.pointAttribs()],
        "point_stride": stride,
        "points_sample": [list(P[i]) for i in range(0, len(P), stride)],
        "point_bbox": [list(geo.boundingBox().minvec()), list(geo.boundingBox().maxvec())],
        "frames": ref_frames,
        "outputs": out,
    }
    with open(out["reference"], "w") as f:
        json.dump(ref, f, indent=1)

    # --- Maya sidecar: what FBX cannot carry -------------------------------------
    ap_mm = cam.parm("aperture").eval()
    resx, resy = cam.parm("resx").eval(), cam.parm("resy").eval()
    hfa_in = ap_mm / 25.4
    vfa_in = ap_mm * resy / resx / 25.4
    sidecar = {
        "schema": "ai_tracking_companion.maya_camera/1",
        "camera": cam.name(), "winy_mode": tag,
        "fps": src_fps, "fps_source": meta["source"]["fps_source"], "maya_time_unit": maya_time_unit(src_fps),
        "fbx_timebase_fps": fbx_fps,
        "frame_start": f1, "frame_end": f2, "frame_offset": offset,
        "resolution": [int(resx), int(resy)],
        "resolution_kind": "production_full_canvas" if space == "production_full_canvas" else "proxy_undistorted_canvas",
        "primary_camera": "Alembic (*.abc); FBX + this sidecar = compatibility fallback",
        "focalLength_mm": cam.parm("focal").eval(),
        "horizontalFilmAperture_in": hfa_in, "verticalFilmAperture_in": vfa_in,
        # measured in TEST 01: Maya film offset = Houdini window offset x aperture
        "horizontalFilmOffset_in": cam.parm("winx").eval() * hfa_in,
        "verticalFilmOffset_in": cam.parm("winy").eval() * vfa_in,
        "linear_unit_note": "values are Houdini units, imported 1:1 into Maya cm (no conversion)",
    }
    with open(out["sidecar"], "w") as f:
        json.dump(sidecar, f, indent=1)

    missing = [k for k in ("fbx", "cam_abc") + (("points_abc",) if a.with_points else ()) if not os.path.isfile(out[k])]
    if missing:
        print(f"[ERROR] outputs not written: {missing}")
        sys.exit(1)
    # Never save: just verify the source is untouched and leave.
    if sha256(hip) != hip_hash_before:
        print("[ERROR] HIP changed on disk during export!")
        sys.exit(1)
    print(json.dumps({"ok": True, "mode": tag, "range": [f1, f2], "fbx_fps": fbx_fps, "abc_fps": hou.fps(),
                      "winy": ref["winy"], "outputs": out}))


if __name__ == "__main__":
    main()

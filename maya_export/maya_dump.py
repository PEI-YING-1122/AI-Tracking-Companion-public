"""Import the delivery into a fresh headless Maya and dump what Maya actually sees.
Run with mayapy:

    mayapy maya_dump.py --fbx cam.fbx --cam-abc cam.abc --points-abc points.abc
                        --frames 1 197 --canvas 372 662 --out maya_dump.json

Only reads the delivery files; writes only --out.  No Maya scene is saved.
"""
import argparse
import json
import os
import sys

import maya.standalone

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.mel as mel  # noqa: E402
import maya.api.OpenMaya as om2  # noqa: E402

DEFAULT_CAMS = {"perspShape", "topShape", "frontShape", "sideShape"}
LENS_ATTRS = ("focalLength", "horizontalFilmAperture", "verticalFilmAperture",
              "horizontalFilmOffset", "verticalFilmOffset", "filmFit", "lensSqueezeRatio",
              "overscan", "preScale", "postScale", "filmTranslateH", "filmTranslateV",
              "nearClipPlane", "farClipPlane", "orthographic", "cameraScale")


SCENE_TIME = None


def new_scene():
    cmds.file(new=True, force=True)
    if SCENE_TIME:
        cmds.currentUnit(time=SCENE_TIME)


def user_cameras():
    return [s for s in cmds.ls(type="camera") if s not in DEFAULT_CAMS]


def dump_camera(shape, frames, canvas):
    xf = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
    cmds.setAttr("defaultResolution.width", canvas[0])
    cmds.setAttr("defaultResolution.height", canvas[1])
    cmds.setAttr("defaultResolution.deviceAspectRatio", float(canvas[0]) / canvas[1])
    cmds.setAttr("defaultResolution.pixelAspect", 1.0)
    sel = om2.MSelectionList()
    sel.add(shape)
    fn = om2.MFnCamera(sel.getDagPath(0))
    out = {"transform": xf, "shape": shape, "lens": {a: cmds.getAttr(f"{shape}.{a}") for a in LENS_ATTRS},
           "rotateOrder": cmds.getAttr(f"{xf}.rotateOrder"),
           "parents": cmds.listRelatives(xf, allParents=True, fullPath=True),
           "anim_curves": cmds.listConnections(xf, type="animCurve") or [],
           "frames": []}
    curves = out["anim_curves"]
    if curves:
        ks = sorted(set(cmds.keyframe(curves, q=True, timeChange=True) or []))
        out["key_range"] = [ks[0], ks[-1]] if ks else None
        out["key_count"] = len(ks)
        out["key_times"] = ks
    out["projection_matrix"] = [[fn.projectionMatrix().getElement(r, c) for c in range(4)] for r in range(4)]
    out["aspectRatio"] = fn.aspectRatio()
    for f in range(frames[0], frames[1] + 1):
        cmds.currentTime(f, edit=True)
        m = cmds.getAttr(f"{xf}.worldMatrix[0]")
        out["frames"].append({"frame": f, "world": [m[0:4], m[4:8], m[8:12], m[12:16]]})
    return out


def scene_info():
    return {"linear_unit": cmds.currentUnit(q=True, linear=True),
            "time_unit": cmds.currentUnit(q=True, time=True),
            "playback": [cmds.playbackOptions(q=True, minTime=True), cmds.playbackOptions(q=True, maxTime=True)],
            "up_axis": cmds.upAxis(q=True, axis=True)}


def dump_points(path, max_samples=2000):
    before = set(cmds.ls(dag=True, long=True))
    cmds.AbcImport(path, mode="import")
    new = [n for n in cmds.ls(dag=True, long=True) if n not in before]
    info = {"new_nodes": [(n, cmds.nodeType(n)) for n in new]}
    for n in new:
        t = cmds.nodeType(n)
        if t in ("particle", "nParticle"):
            cmds.currentTime(cmds.playbackOptions(q=True, minTime=True), edit=True)
            cmds.dgeval(n)
            cnt = cmds.getAttr(f"{n}.count")
            pos = cmds.getAttr(f"{n}.position") or []
            info.update(shape=n, type=t, count=cnt, attrs=cmds.listAttr(n, userDefined=True) or [])
            stride = max(1, len(pos) // max_samples)
            info["stride"], info["sample"] = stride, [list(p) for p in pos[::stride]]
            # particles live in their transform's space
            par = cmds.listRelatives(n, parent=True, fullPath=True)
            info["parent_world"] = cmds.getAttr(f"{par[0]}.worldMatrix[0]") if par else None
        elif t == "mesh":
            pos = cmds.xform(f"{n}.vtx[*]", q=True, ws=True, t=True)
            info.update(shape=n, type=t, count=len(pos) // 3)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fbx")
    ap.add_argument("--cam-abc")
    ap.add_argument("--points-abc")
    ap.add_argument("--frames", nargs=2, type=int, required=True)
    ap.add_argument("--canvas", nargs=2, type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fbx-set-maya-fps", action="store_true",
                    help="FBXImportSetMayaFrameRate true: Maya scene adopts the FBX frame rate")
    ap.add_argument("--scene-time", help="Maya time unit set before every import, e.g. 23.976fps")
    ap.add_argument("--fbx-retime-to", help="after FBX import switch to this time unit keeping keys on their frames")
    ap.add_argument("--fbx-sidecar", help="apply companion maya_camera.json after FBX import (fps + film offset)")
    a = ap.parse_args()
    for k in ("fbx", "cam_abc", "points_abc", "fbx_sidecar"):
        if getattr(a, k):
            setattr(a, k, os.path.abspath(getattr(a, k)).replace("\\", "/"))
    for plug in ("fbxmaya", "AbcImport"):
        if not cmds.pluginInfo(plug, q=True, loaded=True):
            cmds.loadPlugin(plug)
    global SCENE_TIME
    SCENE_TIME = a.scene_time
    res = {"maya_version": cmds.about(version=True), "args": vars(a)}

    if a.fbx:
        new_scene()
        res["fbx_scene_before"] = scene_info()
        mel.eval("FBXResetImport")
        if a.fbx_set_maya_fps:
            mel.eval("FBXImportSetMayaFrameRate -v true")
        mel.eval(f'FBXImport -f "{a.fbx}"')
        if a.fbx_retime_to:
            cmds.currentUnit(time=a.fbx_retime_to, updateAnimation=False)
        res["fbx_scene_after"] = scene_info()
        cams = user_cameras()
        res["fbx_cameras"] = cams
        if len(cams) == 1:
            res["fbx_raw"] = dump_camera(cams[0], a.frames, a.canvas)
            if a.fbx_sidecar:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import maya_apply_sidecar
                maya_apply_sidecar.apply(a.fbx_sidecar, cams[0])
                res["fbx_scene_after_sidecar"] = scene_info()
                res["fbx"] = dump_camera(cams[0], a.frames, a.canvas)
    if a.cam_abc:
        new_scene()
        cmds.AbcImport(a.cam_abc, mode="import")
        cams = user_cameras()
        res["abc_cameras"] = cams
        if len(cams) == 1:
            res["abc"] = dump_camera(cams[0], a.frames, a.canvas)
        res["abc_scene_after"] = scene_info()
    if a.points_abc:
        new_scene()
        res["points"] = dump_points(a.points_abc)

    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print("maya_dump ok", a.out)
    maya.standalone.uninitialize()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

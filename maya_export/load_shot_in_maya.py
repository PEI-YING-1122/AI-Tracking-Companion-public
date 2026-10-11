"""Load one shot's Companion delivery into the open Maya scene.

Maya Script Editor (Python):
    import runpy; runpy.run_path(r"<companion>/maya_export/load_shot_in_maya.py",
                                 init_globals={"METADATA": r"<export>/metadata/<shot>_metadata.json"},
                                 run_name="__main__")
Headless:
    mayapy load_shot_in_maya.py <export>/metadata/<shot>_metadata.json

All paths come from the shot metadata (absolute, resolved per shot by companion_run.py);
the flatten is read where the project keeps it (AI Tracking flatten or a rendered
production flatten) -- nothing is copied.
Order: fps from sidecar -> Camera Alembic (primary) -> render gate = production
canvas -> image plane = production flatten -> point cloud Alembic.  Saves nothing.
"""
import json
import os
import sys

if "maya.cmds" not in sys.modules:  # mayapy: start a headless session
    import maya.standalone
    maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402


def _first_frame_file(pattern, first):
    try:
        return pattern % first
    except TypeError:
        return pattern


def load(metadata_path, with_points=True):
    m = json.load(open(metadata_path))
    p = {"maya_sidecar": m["maya"]["camera_fallback_sidecar"], "maya_cam_abc": m["maya"]["camera_primary"],
         "maya_points_abc": m["maya"]["pointcloud"], "flatten": m["flatten"]["path"]}
    flat_offset = int(m["flatten"].get("frame_offset") or 0)
    side = json.load(open(p["maya_sidecar"]))
    if not cmds.pluginInfo("AbcImport", q=True, loaded=True):
        cmds.loadPlugin("AbcImport")

    # 1. time unit BEFORE the Alembic import so samples land on integer frames
    cmds.currentUnit(time=side["maya_time_unit"])
    cmds.playbackOptions(minTime=side["frame_start"], maxTime=side["frame_end"],
                         animationStartTime=side["frame_start"], animationEndTime=side["frame_end"])
    # 2. primary camera
    before = set(cmds.ls(type="camera"))
    cmds.AbcImport(p["maya_cam_abc"], mode="import")
    cam_shape = [c for c in cmds.ls(type="camera") if c not in before][0]
    cam_xf = cmds.listRelatives(cam_shape, parent=True)[0]
    # 3. render gate = production canvas
    w, h = side["resolution"]
    cmds.setAttr("defaultResolution.width", w)
    cmds.setAttr("defaultResolution.height", h)
    cmds.setAttr("defaultResolution.pixelAspect", 1.0)
    cmds.setAttr("defaultResolution.deviceAspectRatio", w / float(h))
    cmds.setAttr(f"{cam_shape}.displayResolution", 1)
    # 4. image plane = flatten at its project location.  The AI Tracking flatten is
    #    numbered in tracking frames (1..N): frameOffset maps source frame -> file frame.
    first = _first_frame_file(p["flatten"], int(side["frame_start"]) - flat_offset) if p["flatten"] else ""
    ip = None
    if first and os.path.exists(first):
        ip = cmds.imagePlane(camera=cam_shape, fileName=first)[1]
        cmds.setAttr(f"{ip}.useFrameExtension", 1)
        cmds.setAttr(f"{ip}.frameOffset", -flat_offset)
        cmds.setAttr(f"{ip}.fit", 4)
        if first.lower().endswith(".exr"):
            try:  # rendered production flatten is scene-linear; JPG keeps Maya's sRGB file rule
                cmds.setAttr(f"{ip}.ignoreColorSpaceFileRules", 1)
                cmds.setAttr(f"{ip}.colorSpace", "scene-linear Rec.709-sRGB", type="string")
            except Exception:
                pass
    # 5. point cloud
    pts_nodes = []
    if with_points and os.path.exists(p["maya_points_abc"]):
        b = set(cmds.ls(dag=True, long=True))
        try:
            cmds.AbcImport(p["maya_points_abc"], mode="import")
        except Exception as e:  # report, never hide
            print("[Companion] point cloud AbcImport error:", e)
        pts_nodes = [n for n in cmds.ls(dag=True, long=True) if n not in b]
    if not cmds.about(batch=True):
        cmds.lookThru(cam_xf)
    shown = {}
    if ip:  # which file does the image plane show at the first / last frame?
        for f in (side["frame_start"], side["frame_end"]):
            cmds.currentTime(f, edit=True)
            shown[int(f)] = os.path.basename(_first_frame_file(p["flatten"], int(f) - flat_offset))
            shown[f"{int(f)}_frameExtension"] = cmds.getAttr(f"{ip}.frameExtension")
    info = {"shot": m["shot_name"], "camera": cam_xf, "image_plane": ip, "image_plane_first_file": first,
            "image_plane_frames": shown, "frame_offset": flat_offset,
            "time_unit": cmds.currentUnit(q=True, time=True), "resolution": [w, h],
            "frame_range": [side["frame_start"], side["frame_end"]], "point_cloud_nodes": pts_nodes}
    print("[Companion] loaded", json.dumps(info, indent=1))
    return info


if __name__ == "__main__":
    load(globals().get("METADATA") or sys.argv[1])

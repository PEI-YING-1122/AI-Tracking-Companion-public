"""Load the production delivery of one shot into the open Maya scene (manual QC helper).

In Maya (Script Editor, Python tab):

    import runpy; runpy.run_path(r"<package>/maya/load_production_in_maya.py", run_name="__main__")

or headless:  mayapy <package>/maya/load_production_in_maya.py

Paths are resolved relative to this file (package layout), so the package can
live anywhere.  Does: scene fps from the sidecar -> Camera Alembic (primary) ->
render resolution = production canvas -> image plane = PRODUCTION_FLATTEN
sequence -> point cloud Alembic.  Saves nothing.
"""
import glob
import json
import os

import sys

if "maya.cmds" not in sys.modules:  # mayapy: start a headless session
    import maya.standalone
    maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load(here=HERE):
    pkg = os.path.dirname(here)
    side_path = glob.glob(os.path.join(here, "*_cam_corrected.maya_camera.json"))[0]
    side = json.load(open(side_path))
    shot = os.path.basename(side_path).split("_cam_corrected")[0]
    for plug in ("AbcImport",):
        if not cmds.pluginInfo(plug, q=True, loaded=True):
            cmds.loadPlugin(plug)

    # 1. time unit BEFORE the Alembic import so samples land on integer frames
    cmds.currentUnit(time=side["maya_time_unit"])
    cmds.playbackOptions(minTime=side["frame_start"], maxTime=side["frame_end"],
                         animationStartTime=side["frame_start"], animationEndTime=side["frame_end"])

    # 2. primary camera: Alembic
    before = set(cmds.ls(type="camera"))
    cmds.AbcImport(os.path.join(here, f"{shot}_cam_corrected.abc").replace("\\", "/"), mode="import")
    cam_shape = [c for c in cmds.ls(type="camera") if c not in before][0]
    cam_xf = cmds.listRelatives(cam_shape, parent=True)[0]

    # 3. render gate = production canvas
    w, h = side["resolution"]
    cmds.setAttr("defaultResolution.width", w)
    cmds.setAttr("defaultResolution.height", h)
    cmds.setAttr("defaultResolution.pixelAspect", 1.0)
    cmds.setAttr("defaultResolution.deviceAspectRatio", w / float(h))
    cmds.setAttr(f"{cam_shape}.displayResolution", 1)
    cmds.setAttr(f"{cam_shape}.overscan", 1.1)

    # 4. image plane = production flatten (linear half EXR, frame-numbered like the source)
    seq = sorted(glob.glob(os.path.join(pkg, "flatten", f"{shot}_production_flatten.*.exr")))
    ip = None
    if seq:
        ip = cmds.imagePlane(camera=cam_shape, fileName=seq[0].replace("\\", "/"))[1]
        cmds.setAttr(f"{ip}.useFrameExtension", 1)
        cmds.setAttr(f"{ip}.fit", 4)  # to size: the plate has exactly the gate's aspect
        try:  # OCIO space name differs between configs; leave Maya's rule if unknown
            cmds.setAttr(f"{ip}.ignoreColorSpaceFileRules", 1)
            cmds.setAttr(f"{ip}.colorSpace", "scene-linear Rec.709-sRGB", type="string")
        except Exception:
            pass

    # 5. point cloud (see TEST 01: headless AbcImport of points failed -- this is the GUI check)
    pts = os.path.join(here, f"{shot}_points.abc")
    pts_nodes = []
    if os.path.exists(pts):
        b = set(cmds.ls(dag=True, long=True))
        try:
            cmds.AbcImport(pts.replace("\\", "/"), mode="import")
        except Exception as e:  # report, do not hide
            print("[Companion] point cloud AbcImport error:", e)
        pts_nodes = [n for n in cmds.ls(dag=True, long=True) if n not in b]

    cmds.lookThru(cam_xf) if not cmds.about(batch=True) else None
    info = {"shot": shot, "camera": cam_xf, "image_plane": ip, "flatten_frames": len(seq),
            "time_unit": cmds.currentUnit(q=True, time=True), "resolution": [w, h],
            "point_cloud_nodes": pts_nodes}
    print("[Companion] loaded", json.dumps(info, indent=1))
    return info


if __name__ == "__main__":
    load()

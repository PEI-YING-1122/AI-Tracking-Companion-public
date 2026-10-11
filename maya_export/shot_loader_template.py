"""__SHOT__ -- AI Tracking Companion Maya loader (generated; Artist entry point).

Use in Maya (either):
  * drag & drop this file into the Maya viewport, or
  * Script Editor (Python):  import runpy; runpy.run_path(r"<this file>", run_name="__main__")

One call does: fps -> timeline -> render resolution -> corrected camera Alembic ->
gate -> image plane on the AI Tracking flatten (referenced in place, source/tracking
frame mapping) -> point cloud (NPZ -> one native particle object) -> hierarchy:

    AI_TRACKING_GRP
        __SHOT___CAM            (Alembic camera; image plane __SHOT___IMAGEPLANE is attached
                                  under its shape, as Maya does for camera image planes)
        __SHOT___POINTCLOUD     (single particle shape, rgbPP colours, static)

Self-contained: needs only Maya (no numpy, no Companion install).  Saves nothing.
"""
import ast
import json
import os
import struct
import sys
import zipfile
from array import array

import maya.cmds as cmds

SHOT = "__SHOT__"
METADATA_REL = "../metadata/__SHOT___metadata.json"   # export layout
METADATA_ABS = r"__METADATA_ABS__"                   # resolved when this loader was generated
GROUP = "AI_TRACKING_GRP"


# ---------------------------------------------------------------- data
def _metadata_path():
    here = globals().get("__file__")
    if here:
        cand = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(here)), METADATA_REL))
        if os.path.exists(cand):
            return cand
    return METADATA_ABS


def read_npz(path):
    """Minimal .npz reader (little-endian float32 2-D arrays) -> {name: (rows, cols, array('f'))}."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            raw = z.read(name)
            if raw[:6] != b"\x93NUMPY":
                raise ValueError(f"{name}: not a .npy array")
            major = raw[6]
            hlen = struct.unpack("<H", raw[8:10])[0] if major == 1 else struct.unpack("<I", raw[8:12])[0]
            start = 10 if major == 1 else 12
            header = ast.literal_eval(raw[start:start + hlen].decode("latin-1"))
            if header["descr"] != "<f4" or header["fortran_order"]:
                raise ValueError(f"{name}: unsupported layout {header}")
            data = array("f")
            data.frombytes(raw[start + hlen:])
            rows, cols = header["shape"]
            out[os.path.splitext(name)[0]] = (rows, cols, data)
    return out


# ---------------------------------------------------------------- scene
def _unique(name):
    if not cmds.objExists(name):
        return name
    i = 1
    while cmds.objExists(f"{name}{i}"):
        i += 1
    return f"{name}{i}"


def _pointcloud(npz_path, start_frame):
    from maya import OpenMaya as om
    from maya import OpenMayaFX as omfx
    d = read_npz(npz_path)
    n, _, P = d["P"]
    xf, shape = cmds.particle(name=_unique(f"{SHOT}_POINTCLOUD"))
    sel = om.MSelectionList()
    sel.add(shape)
    dag = om.MDagPath()
    sel.getDagPath(0, dag)
    fn = omfx.MFnParticleSystem(dag)
    pts = om.MPointArray()
    pts.setLength(n)
    for i in range(n):
        pts.set(i, P[3 * i], P[3 * i + 1], P[3 * i + 2])
    fn.emit(pts)
    if "Cd" in d:
        Cd = d["Cd"][2]
        for attr in ("rgbPP", "rgbPP0"):
            if not cmds.attributeQuery(attr, node=shape, exists=True):
                cmds.addAttr(shape, longName=attr, dataType="vectorArray")
        cols = om.MVectorArray()
        cols.setLength(n)
        for i in range(n):
            cols.set(om.MVector(Cd[3 * i], Cd[3 * i + 1], Cd[3 * i + 2]), i)
        fn.setPerParticleAttribute("rgbPP", cols)
    fn.saveInitialState()
    cmds.setAttr(f"{shape}.isDynamic", 0)          # static: never simulated
    cmds.setAttr(f"{shape}.startFrame", start_frame)
    cmds.setAttr(f"{shape}.particleRenderType", 3)  # Points
    if not cmds.attributeQuery("pointSize", node=shape, exists=True):
        cmds.addAttr(shape, longName="pointSize", attributeType="long", defaultValue=2)
    return xf, shape, n


def load():
    meta_path = _metadata_path()
    m = json.load(open(meta_path))
    side = json.load(open(m["maya"]["camera_fallback_sidecar"]))   # fps / gate / range (also FBX sidecar)
    f1, f2 = int(side["frame_start"]), int(side["frame_end"])
    w, h = side["resolution"]

    # 1-3. fps, timeline, render resolution (fps BEFORE the Alembic import)
    cmds.currentUnit(time=side["maya_time_unit"])
    cmds.playbackOptions(minTime=f1, maxTime=f2, animationStartTime=f1, animationEndTime=f2)
    cmds.currentTime(f1, edit=True)
    cmds.setAttr("defaultResolution.width", w)
    cmds.setAttr("defaultResolution.height", h)
    cmds.setAttr("defaultResolution.pixelAspect", 1.0)
    cmds.setAttr("defaultResolution.deviceAspectRatio", w / float(h))

    # 4-5. corrected camera (Alembic primary) + gate
    if not cmds.pluginInfo("AbcImport", query=True, loaded=True):
        cmds.loadPlugin("AbcImport")
    before = set(cmds.ls(type="camera"))
    cmds.AbcImport(m["maya"]["camera_primary"], mode="import")
    cam_shape = [c for c in cmds.ls(type="camera") if c not in before][0]
    cam = cmds.rename(cmds.listRelatives(cam_shape, parent=True)[0], _unique(f"{SHOT}_CAM"))
    cam_shape = cmds.rename(cmds.listRelatives(cam, shapes=True, type="camera")[0], f"{cam}Shape")
    cmds.setAttr(f"{cam_shape}.displayResolution", 1)
    cmds.setAttr(f"{cam_shape}.displayGateMask", 1)

    # 6-8. image plane on the AI Tracking flatten (referenced in place)
    fl = m["flatten"]
    off = int(fl.get("frame_offset") or 0)        # source frame - offset = flatten file frame
    first_file = fl["path"] % (f1 - off) if fl.get("path") else ""
    ip = None
    if not first_file:
        cmds.warning(f"[{SHOT}] no flatten for this shot (flatten_mode {fl.get('mode')}): image plane skipped")
    elif os.path.exists(first_file):
        ip_xf, ip = cmds.imagePlane(camera=cam_shape, fileName=first_file)
        ip_xf = cmds.rename(ip_xf, f"{SHOT}_IMAGEPLANE")
        ip = cmds.listRelatives(ip_xf, shapes=True)[0]
        cmds.setAttr(f"{ip}.useFrameExtension", 1)
        cmds.setAttr(f"{ip}.frameOffset", -off)
        cmds.setAttr(f"{ip}.fit", 4)               # to size: flatten == production canvas
        cmds.setAttr(f"{ip}.displayOnlyIfCurrent", 1)
        far = cmds.getAttr(f"{cam_shape}.farClipPlane")
        cmds.setAttr(f"{ip}.depth", far * 0.9)     # behind the point cloud
    else:
        cmds.warning(f"[{SHOT}] flatten not found: {first_file}")

    # 9. point cloud: NPZ -> one native particle object
    pc_xf, pc_shape, n = _pointcloud(m["maya"]["pointcloud_npz"], f1)

    # 10. hierarchy
    grp = cmds.group(empty=True, name=_unique(GROUP))
    cam = cmds.parent(cam, grp)[0]
    pc_xf = cmds.parent(pc_xf, grp)[0]
    cmds.select(clear=True)
    if not cmds.about(batch=True):
        cmds.lookThru(cam)
    info = {"shot": SHOT, "metadata": meta_path, "group": grp, "camera": cam, "image_plane": ip,
            "pointcloud": pc_xf, "points": n, "frames": [f1, f2], "fps": side["fps"],
            "time_unit": cmds.currentUnit(query=True, time=True), "resolution": [w, h]}
    print(f"[{SHOT}] loaded:", json.dumps(info))
    return info


def onMayaDroppedPythonFile(*_):  # drag & drop entry point
    load()


if __name__ == "__main__":
    load()

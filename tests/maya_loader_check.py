"""Run a generated <shot>_load_maya.py in headless Maya and validate the result.  mayapy only.

    mayapy maya_loader_check.py <loader.py> <houdini_reference_corrected.json> <out.json>

Checks: fps / timeline / render resolution; hierarchy (AI_TRACKING_GRP with CAM and
POINTCLOUD, image plane under the camera, no stray DAG nodes); camera world matrix vs
the Houdini reference; gate + film offset vs the sidecar; image plane frame mapping;
point count / positions / colours vs the NPZ (read independently of the loader).
"""
import json
import os
import sys

import maya.standalone

maya.standalone.initialize(name="python")
import runpy  # noqa: E402

import maya.cmds as cmds  # noqa: E402
from maya import OpenMaya as om  # noqa: E402
from maya import OpenMayaFX as omfx  # noqa: E402


def main():
    loader, ref_path, out = sys.argv[1:4]
    cmds.file(new=True, force=True)
    dag_before = set(cmds.ls(dag=True, long=True))
    g = runpy.run_path(loader, run_name="companion_check")   # defines load(), read_npz()
    info = g["load"]()
    dag_new = sorted(set(cmds.ls(dag=True, long=True)) - dag_before)
    meta = json.load(open(info["metadata"]))
    side = json.load(open(meta["maya"]["camera_fallback_sidecar"]))
    ref = json.load(open(ref_path))
    res = {"loader_info": info, "new_dag_nodes": dag_new, "new_dag_count": len(dag_new)}
    shot = info["shot"]

    # scene settings
    res["scene"] = {"time_unit": cmds.currentUnit(q=True, time=True),
                    "timeline": [cmds.playbackOptions(q=True, minTime=True), cmds.playbackOptions(q=True, maxTime=True)],
                    "resolution": [cmds.getAttr("defaultResolution.width"), cmds.getAttr("defaultResolution.height")]}

    # hierarchy
    grp = info["group"]
    kids = cmds.listRelatives(grp, children=True) or []
    cam = info["camera"]
    cam_kids = cmds.listRelatives(cam, children=True) or []
    res["hierarchy"] = {"group": grp, "children": kids, "camera_children": cam_kids,
                        "camera_shapes": cmds.listRelatives(cam, shapes=True)}

    # camera vs Houdini reference
    shape = cmds.listRelatives(cam, shapes=True, type="camera")[0]
    hframes = {int(round(fr["frame"])): fr["world"] for fr in ref["frames"]}
    check = sorted({min(hframes), max(hframes), sorted(hframes)[len(hframes) // 2]})
    md = 0.0
    for f in check:
        cmds.currentTime(f, edit=True)
        mw = cmds.getAttr(f"{cam}.worldMatrix[0]")
        hw = [v for row in hframes[f] for v in row]
        md = max(md, max(abs(a - b) for a, b in zip(mw, hw)))
    L = {a: cmds.getAttr(f"{shape}.{a}") for a in ("focalLength", "horizontalFilmAperture", "verticalFilmAperture",
                                                  "horizontalFilmOffset", "verticalFilmOffset", "filmFit")}
    res["camera"] = {"frames_checked": check, "world_matrix_max_abs_diff_vs_houdini": md, "lens": L,
                     "gate_aspect": L["horizontalFilmAperture"] / L["verticalFilmAperture"],
                     "focal_diff": L["focalLength"] - side["focalLength_mm"],
                     "film_offset_diff": [L["horizontalFilmOffset"] - side["horizontalFilmOffset_in"],
                                          L["verticalFilmOffset"] - side["verticalFilmOffset_in"]]}

    # image plane frame mapping
    ip = info["image_plane"]
    if ip:
        pat = meta["flatten"]["path"]
        mapping = {}
        for f in (int(res["scene"]["timeline"][0]), int(res["scene"]["timeline"][1])):
            cmds.currentTime(f, edit=True)
            fe = cmds.getAttr(f"{ip}.frameExtension")
            fo = cmds.getAttr(f"{ip}.frameOffset")
            file_f = int(round(fe + fo))
            mapping[f] = {"frameExtension": fe, "frameOffset": fo, "file": os.path.basename(pat % file_f),
                          "exists": os.path.exists(pat % file_f)}
        res["image_plane"] = {"node": ip, "full_path": cmds.ls(ip, long=True)[0], "mapping": mapping,
                              "fit": cmds.getAttr(f"{ip}.fit"), "depth": cmds.getAttr(f"{ip}.depth")}

    # point cloud vs NPZ (independent read)
    d = g["read_npz"](meta["maya"]["pointcloud_npz"])
    n, _, P = d["P"]
    pshape = cmds.listRelatives(info["pointcloud"], shapes=True)[0]
    sel = om.MSelectionList()
    sel.add(pshape)
    dag = om.MDagPath()
    sel.getDagPath(0, dag)
    fn = omfx.MFnParticleSystem(dag)
    pc = {"type": cmds.nodeType(pshape), "npz_count": n}
    for f in (int(res["scene"]["timeline"][0]), int(res["scene"]["timeline"][1])):
        cmds.currentTime(f, edit=True)
        pos = om.MVectorArray()
        fn.position(pos)
        mx = max(max(abs(pos[i].x - P[3 * i]), abs(pos[i].y - P[3 * i + 1]), abs(pos[i].z - P[3 * i + 2]))
                 for i in range(pos.length())) if pos.length() == n else None
        wm = cmds.getAttr(f"{info['pointcloud']}.worldMatrix[0]")
        pc[f] = {"count": fn.count(), "max_abs_pos_diff": mx,
                 "transform_is_identity": all(abs(a - b) < 1e-12 for a, b in zip(wm, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]))}
    if "Cd" in d:
        Cd = d["Cd"][2]
        cols = om.MVectorArray()
        fn.getPerParticleAttribute("rgbPP", cols)
        pc["color_count"] = cols.length()
        pc["max_abs_color_diff"] = max(max(abs(cols[i].x - Cd[3 * i]), abs(cols[i].y - Cd[3 * i + 1]),
                                           abs(cols[i].z - Cd[3 * i + 2])) for i in range(cols.length()))
    pc["render_type"] = cmds.getAttr(f"{pshape}.particleRenderType")
    pc["is_dynamic"] = cmds.getAttr(f"{pshape}.isDynamic")
    res["pointcloud"] = pc

    json.dump(res, open(out, "w"), indent=1, default=str)
    print("maya_loader_check ok", out)
    maya.standalone.uninitialize()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

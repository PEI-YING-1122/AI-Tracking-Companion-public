"""Apply a companion camera sidecar to an imported FBX camera inside Maya.

FBX from Houdini 20.0.547 carries focal/filmback/animation but NOT the film
offset (winx/winy), and is written frame-indexed at 24 fps.  This restores both:

    import maya_apply_sidecar
    maya_apply_sidecar.apply("cam_corrected.maya_camera.json", "Nerfstudio_Animated_CamShape")

Works in Maya GUI (Script Editor) and mayapy.  Changes only the open scene.
"""
import json

import maya.cmds as cmds


def apply(sidecar_path, camera_shape):
    with open(sidecar_path) as f:
        sc = json.load(f)
    # keep keys on their frame numbers while switching to the real source rate
    cmds.currentUnit(time=sc["maya_time_unit"], updateAnimation=False)
    cmds.setAttr(f"{camera_shape}.horizontalFilmOffset", sc["horizontalFilmOffset_in"])
    cmds.setAttr(f"{camera_shape}.verticalFilmOffset", sc["verticalFilmOffset_in"])
    cmds.playbackOptions(minTime=sc["frame_start"], maxTime=sc["frame_end"],
                         animationStartTime=sc["frame_start"], animationEndTime=sc["frame_end"])
    cmds.setAttr("defaultResolution.width", sc["resolution"][0])
    cmds.setAttr("defaultResolution.height", sc["resolution"][1])
    cmds.setAttr("defaultResolution.pixelAspect", 1.0)
    cmds.setAttr("defaultResolution.deviceAspectRatio", sc["resolution"][0] / float(sc["resolution"][1]))
    return sc

import hou
for kw in [dict(), dict(modify_frame_count=False, preserve_keyframes=True, preserve_frame_start=True),
           dict(modify_frame_count=False, preserve_keyframes=True, preserve_frame_start=False)]:
    hou.hipFile.clear(suppress_save_prompt=True)
    n = hou.node("/obj").createNode("null"); p = n.parm("tx")
    for f in (1, 10): k = hou.Keyframe(); k.setFrame(f); k.setValue(f); p.setKeyframe(k)
    print("before fps", hou.fps(), "f2t(1)", hou.frameToTime(1), "range", hou.playbar.frameRange())
    hou.setFps(24000/1001, **kw)
    print(kw, "-> f2t(1)=%.6f f2t(10)=%.6f" % (hou.frameToTime(1), hou.frameToTime(10)), "keys", [k.frame() for k in p.keyframes()], "range", hou.playbar.frameRange())

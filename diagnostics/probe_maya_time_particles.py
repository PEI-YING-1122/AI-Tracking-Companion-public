import maya.standalone; maya.standalone.initialize(name="python")
import maya.cmds as cmds, sys
cmds.loadPlugin("AbcImport")
cmds.file(new=True, force=True)
cmds.currentUnit(time="23.976fps"); print("after set:", cmds.currentUnit(q=True, time=True))
cmds.AbcImport(sys.argv[1], mode="import"); print("after abc:", cmds.currentUnit(q=True, time=True), cmds.playbackOptions(q=True,min=True), cmds.playbackOptions(q=True,max=True))
cmds.file(new=True, force=True); print("after new:", cmds.currentUnit(q=True, time=True))
cmds.AbcImport(sys.argv[2], mode="import")
sh = cmds.ls(type="particle", long=True)[0]; print(sh, cmds.listConnections(sh, s=True, d=False, c=True, p=True))
for f in (0, 1, 2):
    cmds.currentTime(f)
    print(f, "count", cmds.getAttr(sh + ".count"), "pos", (cmds.getAttr(sh + ".position") or [])[:1], cmds.particle(sh, q=True, count=True))
print([a for a in (cmds.listAttr(sh) or []) if "pos" in a.lower()][:20])

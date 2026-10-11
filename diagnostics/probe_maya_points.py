import maya.standalone; maya.standalone.initialize(name="python")
import maya.cmds as cmds, sys
cmds.loadPlugin("AbcImport")
for path in sys.argv[1:]:
    for mode in ("import", "open"):
        cmds.file(new=True, force=True)
        try:
            cmds.AbcImport(path, mode=mode)
        except Exception as e:
            print("ERR", e)
        for sh in cmds.ls(type="particle", long=True):
            cmds.currentTime(1)
            print(path.split("/")[-1], mode, sh, "count", cmds.getAttr(sh + ".count"), "conn", bool(cmds.listConnections(sh, s=True, d=False)))

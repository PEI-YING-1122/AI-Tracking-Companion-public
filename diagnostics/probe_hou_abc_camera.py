import hou, sys
hou.hipFile.load(sys.argv[1], suppress_save_prompt=True, ignore_load_warnings=True)
out = sys.argv[2]
for i,(root,objs) in enumerate([("/obj","/obj/NeRF_Import/Nerfstudio_Animated_Cam"),("/obj/NeRF_Import","/obj/NeRF_Import/Nerfstudio_Animated_Cam"),("/obj","*Nerfstudio_Animated_Cam")]):
    r = hou.node("/out").createNode("alembic")
    r.parm("trange").set(1); r.parmTuple("f").set((1,5,1))
    r.parm("filename").set(f"{out}/probe_cam_{i}.abc"); r.parm("root").set(root); r.parm("objects").set(objs)
    r.render(); print(i, root, objs)

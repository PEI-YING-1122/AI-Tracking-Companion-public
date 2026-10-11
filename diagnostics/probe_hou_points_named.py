import hou, sys
hou.hipFile.load(sys.argv[1], suppress_save_prompt=True, ignore_load_warnings=True)
geo = hou.node("/obj/NeRF_Import/Scene"); pts = hou.node("/obj/NeRF_Import/Scene/COLMAP_to_Houdini")
p = geo.createNode("attribwrangle"); p.setInput(0, pts); p.parm("snippet").set('s@path = "pointcloud/particleShape1";')
r = hou.node("/out").createNode("alembic"); r.parm("trange").set(0)
r.parm("filename").set(sys.argv[2]); r.parm("use_sop_path").set(1); r.parm("sop_path").set(p.path())
r.parm("build_from_path").set(1); r.parm("path_attrib").set("path"); r.render()

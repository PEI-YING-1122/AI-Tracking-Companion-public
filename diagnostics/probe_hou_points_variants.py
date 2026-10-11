import hou, sys
hou.hipFile.load(sys.argv[1], suppress_save_prompt=True, ignore_load_warnings=True)
out = sys.argv[2]
pts = hou.node("/obj/NeRF_Import/Scene/COLMAP_to_Houdini")
g = pts.geometry(); print("attribs", [a.name() for a in g.pointAttribs()], "npts", len(g.points()), "prims", len(g.prims()))
geo = hou.node("/obj/NeRF_Import/Scene")
# variant: add an id attribute (Maya particles key on id)
w = geo.createNode("attribwrangle", "add_id"); w.setInput(0, pts); w.parm("snippet").set("i@id = @ptnum;")
# variant: path attrib to control names
p = geo.createNode("attribwrangle", "add_path"); p.setInput(0, w); p.parm("class").set(1) if False else None
p.parm("snippet").set('s@path = "pointcloud";')
for i, (sop, extra) in enumerate([(pts.path(), {}), (w.path(), {}), (p.path(), {"build_from_path": 1, "path_attrib": "path"})]):
    r = hou.node("/out").createNode("alembic"); r.parm("trange").set(0)
    r.parm("filename").set(f"{out}/pts_{i}.abc"); r.parm("use_sop_path").set(1); r.parm("sop_path").set(sop)
    for k, v in extra.items():
        if r.parm(k): r.parm(k).set(v)
        else: print("no parm", k)
    r.render(); print("wrote", i, sop)

import hou
print("ver", hou.applicationVersionString(), "lic", hou.licenseCategory())
print("fps", hou.fps())
for n in ("filmboxfbx","alembic"):
    print("ROP", n, hou.nodeType(hou.ropNodeTypeCategory(), n) is not None)
print("SOP rop_alembic", hou.nodeType(hou.sopNodeTypeCategory(), "rop_alembic") is not None)
print("SOP rop_fbx", hou.nodeType(hou.sopNodeTypeCategory(), "rop_fbx") is not None)
cam = hou.node("/obj").createNode("cam","c")
cam.parm("resx").set(1000); cam.parm("resy").set(500)
cam.parm("focal").set(50); cam.parm("aperture").set(36)
geo = hou.node("/obj").createNode("geo","g")
w = geo.createNode("attribwrangle")
w.parm("class").set(0)
w.parm("snippet").set('vector p=toNDC("/obj/c", set(0,0,-1)); setdetailattrib(0,"ndc",p);')
for winx,winy in ((0,0),(0.1,0),(0,0.1)):
    cam.parm("winx").set(winx); cam.parm("winy").set(winy)
    w.cook(force=True)
    print("win",winx,winy,"-> ndc", w.geometry().attribValue("ndc"))

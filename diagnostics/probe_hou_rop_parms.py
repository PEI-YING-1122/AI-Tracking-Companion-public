import hou
out = hou.node("/out")
for t in ("filmboxfbx", "alembic"):
    r = out.createNode(t)
    print("==", t)
    for p in r.parms():
        tmpl = p.parmTemplate()
        extra = ""
        if tmpl.type() == hou.parmTemplateType.Menu:
            extra = " menu=" + ",".join(tmpl.menuItems())
        print(f"  {p.name()} = {p.eval()!r}{extra}")
print(hou.setFps.__doc__)

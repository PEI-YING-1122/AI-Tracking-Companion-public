import hou; n=hou.node("/obj").createNode("geo").createNode("alembic"); p=n.parm("loadmode"); print(p.menuItems(), p.menuLabels())

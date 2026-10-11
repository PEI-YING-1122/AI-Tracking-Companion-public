import nuke, sys
st = nuke.nodes.Read(file=sys.argv[1], raw=True); src = nuke.nodes.Read(file=sys.argv[2], raw=True)
print("stmap file fmt", st.format().width(), st.format().height(), "src fmt", src.format().width(), src.format().height())
for order in ((0, 1), (1, 0)):
    n = nuke.nodes.STMap(); n.setInput(order[0], st); n.setInput(order[1], src); n["uv"].fromScript("rgb")
    print("stmap->input%d src->input%d" % order, "out fmt", n.format().width(), n.format().height(),
          "sample(100.5,100.5) r,g =", n.sample("red", 100.5, 100.5), n.sample("green", 100.5, 100.5))

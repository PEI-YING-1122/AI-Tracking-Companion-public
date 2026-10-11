import nuke, sys
src = nuke.nodes.Read(file=sys.argv[1], raw=True)
c = nuke.nodes.Crop(); print("crop knobs", [k for k in c.knobs() if k in ("box","crop","reformat","intersect","softness")])
print("src w h", src.width(), src.height(), "bbox", src.bbox().x(), src.bbox().y(), src.bbox().w(), src.bbox().h())
s = nuke.nodes.STMap(); print("filter values", s["filter"].values())
for f in ("Cubic", "Rifman", "Keys"):
    s["filter"].setValue(f); print(f, "->", s["filter"].value(), s["filter"].getValue())

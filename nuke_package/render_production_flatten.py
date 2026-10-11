"""Render a production flatten from a lens setup (flatten_mode "render").  Run inside Nuke:

    Nuke13.2.exe -t render_production_flatten.py <setup.nk> out=<pattern %04d> range=<first>,<last>

Source node: APPLY_UNDISTORT (Artist setup) or UNDISTORT_LIVE (PoC package).
16-bit half EXR, ZIP.  The Write exists in memory only; the .nk is never saved.
(Arguments are key=value: a bare trailing number would be swallowed by Nuke.)
"""
import hashlib
import sys

import nuke

nk = sys.argv[1]
args = dict(a.split("=", 1) for a in sys.argv[2:])
f1, f2 = (int(v) for v in args["range"].split(","))
sha = hashlib.sha256(open(nk, "rb").read()).hexdigest()
nuke.scriptOpen(nk)
src = nuke.toNode("APPLY_UNDISTORT") or nuke.toNode("UNDISTORT_LIVE")
target = args.get("out") or nuke.toNode("PRODUCTION_FLATTEN")["file"].value()
w = nuke.nodes.Write(file=target, file_type="exr", create_directories=True)
w["datatype"].setValue("16 bit half")
w["compression"].setValue("Zip (1 scanline)")
w["channels"].setValue("rgb")
w.setInput(0, src)
nuke.execute(w, f1, f2)
nuke.delete(w)
assert hashlib.sha256(open(nk, "rb").read()).hexdigest() == sha, ".nk changed"
print("rendered", target, f1, f2)

"""Render an STMap through real Nuke (terminal mode, no GUI, no .nk saved).

    Nuke13.2.exe -t nuke_stmap_render.py <stmap.exr> <src.exr> <out.exr> [filter]

src is read raw; out is written as raw 32-bit float EXR (rgba).
"""
import sys

import nuke

stmap_path, src_path, out_path = sys.argv[1:4]
filt = sys.argv[4] if len(sys.argv) > 4 else "Cubic"
black_outside = len(sys.argv) > 5 and sys.argv[5] == "black"

st_read = nuke.nodes.Read(file=stmap_path.replace("\\", "/"), raw=True)
src_read = nuke.nodes.Read(file=src_path.replace("\\", "/"), raw=True)
stm = nuke.nodes.STMap()
# Input order measured in Nuke 13.2v3 (diagnostics/probe_nuke_stmap_inputs.py):
# input 0 = src (image to warp), input 1 = stmap; output takes the stmap format.
src_node = src_read
if black_outside:
    # recommended Nuke setup: samples outside the plate become black (as upstream)
    src_node = nuke.nodes.Crop()
    src_node["box"].setValue([0, 0, src_read.width(), src_read.height()])
    src_node["crop"].setValue(True)  # "black outside"
    src_node.setInput(0, src_read)
stm.setInput(0, src_node)
stm.setInput(1, st_read)
stm["uv"].fromScript("rgb")
stm["filter"].setValue(filt)
w = nuke.nodes.Write(file=out_path.replace("\\", "/"), file_type="exr", raw=True, channels="rgba")
w["datatype"].setValue("32 bit float")
w.setInput(0, stm)
nuke.execute(w, 1, 1)
print("format", stm.format().width(), stm.format().height(), "filter", filt, "->", out_path)

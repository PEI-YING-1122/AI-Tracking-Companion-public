"""Open a lens_setup.nk in Nuke (terminal), inspect it and render QC taps.

    Nuke13.2.exe -t validate_nuke_package.py <setup.nk> <out_dir> frames=<f1,f2,...> [raw]

Never saves the script.  Temporary Write nodes exist only in memory.
'raw' makes the image Reads raw (memory only) so renders are code values / 255.
Writes <out_dir>/validate.json.
"""
import hashlib
import json
import os
import sys

import nuke

# frames passed as "frames=1,2,3": a bare trailing frame list is swallowed by Nuke as its own range
nk, out_dir = sys.argv[1], sys.argv[2]
frames = [int(f) for f in sys.argv[3].split("=", 1)[-1].split(",")]
raw = len(sys.argv) > 4 and sys.argv[4] == "raw"
os.makedirs(out_dir, exist_ok=True)
sha = hashlib.sha256(open(nk, "rb").read()).hexdigest()
nuke.scriptOpen(nk)
root = nuke.root()

REQUIRED = ["READ_ORIGINAL_PLATE", "READ_STMAP_UNDISTORT", "APPLY_UNDISTORT", "UNDISTORT_LIVE",
            "PRODUCTION_FLATTEN", "TRACKING_REFERENCE_FLATTEN", "QC_DIFFERENCE", "QC_DIFFERENCE_PROXY",
            "QC_ROUNDTRIP_DIFFERENCE", "COMP_INPUT", "READ_STMAP_REDISTORT", "APPLY_REDISTORT", "DELIVERY_OUTPUT"]
rep = {"nk": nk, "root": {"fps": root["fps"].value(), "first_frame": root["first_frame"].value(),
                          "last_frame": root["last_frame"].value(),
                          "format": [root.format().width(), root.format().height(), root.format().name()],
                          "project_directory_raw": root["project_directory"].value(),
                          "project_directory_eval": root["project_directory"].evaluate()},
       "nodes": {}, "backdrops": {}}

for n in nuke.allNodes(recurseGroups=False):
    d = {"class": n.Class(), "inputs": [n.input(i).name() if n.input(i) else None for i in range(n.inputs())]}
    if "file" in n.knobs():
        d["file_raw"] = n["file"].value()
        try:
            d["file_eval"] = n["file"].evaluate(frames[0])
        except Exception as e:
            d["file_eval"] = f"ERR {e}"
    if n.Class() == "Read":
        d.update(first=n["first"].value(), last=n["last"].value(), raw=n["raw"].value(),
                 before=n["before"].value(), after=n["after"].value(),
                 frame_mode=n["frame_mode"].value(), frame=n["frame"].value(), on_error=n["on_error"].value())
    if n.Class() not in ("BackdropNode", "StickyNote", "Write", "Viewer"):
        try:
            d["format"] = [n.format().width(), n.format().height()]
            d["error"] = bool(n.hasError())
        except Exception as e:
            d["error"] = f"ERR {e}"
    if n.Class() == "STMap":
        d.update(uv=n["uv"].value(), filter=n["filter"].value())
    if n.Class() == "Crop":
        d.update(box=list(n["box"].value()), black_outside=n["crop"].value(), reformat=n["reformat"].value())
    if n.Class() == "Merge2":
        d["operation"] = n["operation"].value()
    rep["nodes"][n.name()] = d
    if n.Class() == "BackdropNode":
        rep["backdrops"][n["label"].value()] = []

# backdrop membership by position
bds = [n for n in nuke.allNodes("BackdropNode")]
for n in nuke.allNodes(recurseGroups=False):
    if n.Class() == "BackdropNode":
        continue
    for b in bds:
        if b.xpos() <= n.xpos() <= b.xpos() + b["bdwidth"].value() and b.ypos() <= n.ypos() <= b.ypos() + b["bdheight"].value():
            rep["backdrops"][b["label"].value()].append(n.name())
rep["missing_required"] = [r for r in REQUIRED if r not in rep["nodes"]]


def upstream(n, seen=None):
    seen = set() if seen is None else seen
    for i in range(n.inputs()):
        p = n.input(i)
        if p is not None and p.name() not in seen:
            seen.add(p.name())
            upstream(p, seen)
    return seen


prod = upstream(nuke.toNode("DELIVERY_OUTPUT"))
rep["production_path"] = sorted(prod)
rep["production_path_has_difference"] = any(rep["nodes"][x].get("operation") == "difference" for x in prod)
rep["production_path_has_qc"] = sorted(x for x in prod if "QC" in x)

# frame-offset semantics of the tracking Reads (memory only, restored afterwards)
fl = nuke.toNode("TRACKING_REFERENCE_FLATTEN")
saved = (fl["frame_mode"].value(), fl["frame"].value())
rep["offset_probe"] = {}
for val in ("1000", "-1000"):
    fl["frame_mode"].setValue("offset")
    fl["frame"].setValue(val)
    try:
        rep["offset_probe"][val] = {"at_1001_filename": os.path.basename(str(fl.metadata("input/filename", 1001))),
                                    "at_1100_filename": os.path.basename(str(fl.metadata("input/filename", 1100)))}
    except Exception as e:
        rep["offset_probe"][val] = {"error": str(e)}
# as saved in the script: which file does each frame of the tracking range read?
fl["frame_mode"].setValue(saved[0])
fl["frame"].setValue(saved[1])
rep["flatten_frame_map"] = {f: os.path.basename(str(fl.metadata("input/filename", f))) for f in frames}
pl = nuke.toNode("READ_ORIGINAL_PLATE")
rep["plate_frame_map"] = {f: [os.path.basename(str(pl.metadata("input/filename", f))), pl.metadata("input/frame", f)] for f in frames}
fl["frame_mode"].setValue(saved[0])
fl["frame"].setValue(saved[1])

if raw:
    # raw pass: code values for the 8-bit sources.  PRODUCTION_FLATTEN (linear EXR) is only
    # meaningful in the non-raw pass.
    for name in ("READ_ORIGINAL_PLATE", "TRACKING_REFERENCE_FLATTEN", "READ_TRACKING_PROXY_QC"):
        nuke.toNode(name)["raw"].setValue(True)

TAPS = ["READ_ORIGINAL_PLATE", "UNDISTORT_LIVE", "PRODUCTION_FLATTEN", "COMP_INPUT",
        "TRACKING_REFERENCE_FLATTEN", "TRACKING_REF_CROP_TO_CANVAS", "QC_TRACKING_REF_ALIGNMENT",
        "APPLY_UNDISTORT_PROXY_QC", "QC_DIFFERENCE_PROXY", "QC_DIFFERENCE", "APPLY_REDISTORT_QC",
        "QC_ROUNDTRIP_DIFFERENCE", "APPLY_REDISTORT"]
rep["renders"] = {}
for t in TAPS:
    w = nuke.nodes.Write(file=os.path.join(out_dir, f"{t}.%04d.exr").replace("\\", "/"), file_type="exr", raw=True,
                         channels="rgba")
    w["datatype"].setValue("32 bit float")
    src = nuke.toNode(t)
    c = nuke.nodes.Crop(box=[0, 0, src.format().width(), src.format().height()], crop=True)  # data window = format
    c.setInput(0, src)
    w.setInput(0, c)
    for f in frames:
        nuke.execute(w, f, f)
    rep["renders"][t] = w["file"].value()
    nuke.delete(w)
    nuke.delete(c)

rep["nk_sha256_unchanged"] = hashlib.sha256(open(nk, "rb").read()).hexdigest() == sha
json.dump(rep, open(os.path.join(out_dir, "validate.json"), "w"), indent=1)
print("validate ok", out_dir)

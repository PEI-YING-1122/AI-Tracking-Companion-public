"""Smoke-check an Artist lens_setup.nk in Nuke (terminal).  Never saves.

    Nuke13.2.exe -t check_nuke_setup.py <setup.nk> <out_dir> frames=<f1,f2,...>

Reports Read errors / missing files, frame range, formats, graph clutter (any
QC / comp-template / Write / Switch / Merge node), the file each Read uses at the
given frames, and renders (32-bit, temporary in-memory Writes):
  PLATE      READ_ORIGINAL_PLATE
  UNDISTORT  APPLY_UNDISTORT
  REFERENCE  TRACKING_REFERENCE_FLATTEN
  REDISTORT  APPLY_REDISTORT (example input as saved)
  ROUNDTRIP  APPLY_UNDISTORT -> redistort STMap (temporary STMap, memory only)
"""
import hashlib
import json
import os
import sys

import nuke

nk, out_dir = sys.argv[1], sys.argv[2]
frames = [int(f) for f in sys.argv[3].split("=", 1)[-1].split(",")]
os.makedirs(out_dir, exist_ok=True)
sha = hashlib.sha256(open(nk, "rb").read()).hexdigest()
nuke.scriptOpen(nk)
root = nuke.root()
rep = {"root": {"fps": root["fps"].value(), "first": root["first_frame"].value(), "last": root["last_frame"].value(),
                "format": [root.format().width(), root.format().height()]}, "nodes": {}}
CLUTTER_CLASSES = {"Write", "Switch", "Merge2", "Difference", "NoOp", "Dot"}
for n in nuke.allNodes():
    d = {"class": n.Class(), "inputs": [n.input(i).name() if n.input(i) else None for i in range(n.inputs())],
         "label": n["label"].value() if "label" in n.knobs() else ""}
    if n.Class() == "Read":
        d.update(file=n["file"].value(), raw=n["raw"].value(), first=n["first"].value(), last=n["last"].value(),
                 frame_mode=n["frame_mode"].value(), frame=n["frame"].value(), on_error=n["on_error"].value(),
                 colorspace=n["colorspace"].value())
        d["files_at"] = {f: os.path.basename(str(n.metadata("input/filename", f))) for f in frames}
        d["file_exists_at"] = {f: os.path.exists(str(n.metadata("input/filename", f))) for f in frames}
    if n.Class() not in ("BackdropNode", "StickyNote", "Viewer"):
        d["format"] = [n.format().width(), n.format().height()]
        d["error"] = bool(n.hasError())
    rep["nodes"][n.name()] = d
rep["read_errors"] = sorted(k for k, v in rep["nodes"].items() if v.get("error") is True)
rep["clutter"] = sorted(k for k, v in rep["nodes"].items()
                        if v["class"] in CLUTTER_CLASSES or any(t in k for t in ("QC", "COMP_", "DELIVERY", "PRODUCTION")))
rep["undistort_format"] = rep["nodes"].get("APPLY_UNDISTORT", {}).get("format")
rep["redistort_format"] = rep["nodes"].get("APPLY_REDISTORT", {}).get("format")

temp = nuke.nodes.STMap(uv="rgb")
temp["filter"].setValue("Keys")
temp.setInput(0, nuke.toNode("APPLY_UNDISTORT"))
temp.setInput(1, nuke.toNode("READ_STMAP_REDISTORT"))
taps = {"PLATE": nuke.toNode("READ_ORIGINAL_PLATE"), "UNDISTORT": nuke.toNode("APPLY_UNDISTORT"),
        "REFERENCE": nuke.toNode("TRACKING_REFERENCE_FLATTEN"), "REDISTORT": nuke.toNode("APPLY_REDISTORT"),
        "ROUNDTRIP": temp}
for name, src in taps.items():
    if src is None:  # e.g. no TRACKING_REFERENCE_FLATTEN when flatten_mode is "none"
        continue
    c = nuke.nodes.Crop(box=[0, 0, src.format().width(), src.format().height()], crop=True)
    c.setInput(0, src)
    w = nuke.nodes.Write(file=os.path.join(out_dir, f"{name}.%04d.exr").replace("\\", "/"), file_type="exr",
                         raw=True, channels="rgba")
    w["datatype"].setValue("32 bit float")
    w.setInput(0, c)
    for f in frames:
        nuke.execute(w, f, f)
    nuke.delete(w)
    nuke.delete(c)
nuke.delete(temp)
rep["nk_unchanged"] = hashlib.sha256(open(nk, "rb").read()).hexdigest() == sha
json.dump(rep, open(os.path.join(out_dir, "check.json"), "w"), indent=1)
print("check ok")

"""Write the Artist lens handoff / example setup.  Run inside Nuke:

    Nuke13.2.exe -t nk_writer_artist.py <spec.json> <out.nk>

Native nodes only, absolute production paths from the shot spec.  Layout and node
set follow the Artist reference (export/nuke_reference); it shows how the STMaps
connect and is NOT a comp template: no COMP_INPUT / COMP_OUTPUT / Write / Switch /
QC nodes.

    SOURCE              READ_ORIGINAL_PLATE   LENS_INFO
    UNDISTORT           READ_ORIGINAL_PLATE -> CROP_BLACK_OUTSIDE -> APPLY_UNDISTORT <- READ_STMAP_UNDISTORT
    TRACKING REFERENCE  TRACKING_REFERENCE_FLATTEN (when available; reference only)
    REDISTORT           TRACKING_REFERENCE_FLATTEN (example input) -> APPLY_REDISTORT <- READ_STMAP_REDISTORT

Connection topology = the Artist reference setup used in the regression test.
The tracking reference is only the example image fed through the redistort STMap: the STMaps
themselves always come from the production lens data (original plate canvas), never from the flatten.
No tracking reference (flatten incompatible / flatten_mode none): APPLY_REDISTORT keeps the
earlier example input APPLY_UNDISTORT -- unchanged, pending a decision on the no-reference case.
"""
import json
import sys

import nuke

spec_path, nk_path = sys.argv[1:3]
L = json.load(open(spec_path))
N = L["_nuke"]
shot = L["shot_name"]
SW, SH = L["source"]["resolution"]
UW, UH = L["production_canvas"]["resolution"]
F1, F2 = N["plate_first"], N["plate_last"]
fps = L["source"]["fps"]

nuke.scriptSaveAs(nk_path, overwrite=1)
root = nuke.root()
root["fps"].setValue(fps)
root["first_frame"].setValue(F1)
root["last_frame"].setValue(F2)
nuke.addFormat(f"{SW} {SH} 1 {shot}_plate")
nuke.addFormat(f"{UW} {UH} 1 {shot}_undistort")
root["format"].setValue(f"{shot}_plate")


def node(cls, name, x, y, inputs=(), **knobs):
    n = getattr(nuke.nodes, cls)()
    n.setName(name)
    for i, inp in enumerate(inputs):
        n.setInput(i, inp)
    for k, v in knobs.items():
        n[k].setValue(v)
    n.setXYpos(x, y)
    return n


def read(name, path, first, last, x, y, raw=False, hold=False, offset=0, missing_black=False, label=None):
    n = node("Read", name, x, y)
    n["file"].fromUserText(path)
    n["file"].setValue(path)
    for k, v in (("first", first), ("last", last), ("origfirst", first), ("origlast", last)):
        n[k].setValue(v)
    if raw:
        n["raw"].setValue(True)          # STMap = DATA, no colour transform
    if hold:
        n["before"].setValue("hold")
        n["after"].setValue("hold")
    if offset:
        n["frame_mode"].setValue("offset")
        n["frame"].setValue(str(-offset))  # Nuke reads file frame = frame + value
    if missing_black:
        n["on_error"].setValue("black")
    if label:
        n["label"].setValue(label)
    return n


def stmap(name, x, y, src, st, label=None):
    n = node("STMap", name, x, y, [src, st])   # input0 = image, input1 = STMap
    n["uv"].fromScript("rgb")
    n["filter"].setValue("Keys")
    if label:
        n["label"].setValue(label)
    return n


def backdrop(name, label, x, y, w, h, color):
    b = nuke.nodes.BackdropNode(xpos=x, ypos=y, bdwidth=w, bdheight=h, tile_color=color, note_font_size=36)
    b.setName(name)
    b["label"].setValue(label)
    return b


# layout (positions / backdrop geometry only): Artist reference setup (v0.2.1 final)
backdrop("BD_SOURCE", "SOURCE", 468, -681, 665, 283, 0x3f4f5fff)
backdrop("BD_UNDISTORT", "UNDISTORT", 468, -356, 438, 300, 0x4f5f3fff)
backdrop("BD_REDISTORT", "REDISTORT", 984, -363, 471, 306, 0x5f3f4fff)
REF_LABEL = {"reference": "AI Tracking flatten (reference)",
             "reference_only": "AI Tracking flatten — reference only"}

HAS_REF = bool(N.get("tracking_reference_flatten"))   # flatten_mode "none" / incompatible -> no reference
# fps value only: its source (default / override / metadata) stays in metadata, GUI and log
info = (f"{shot}\n"
        f"plate {SW}x{SH}   frames {F1}-{F2}   fps {fps:g}\n"
        f"undistort {UW}x{UH}\n"
        f"STMap production mode: converged canvas, 32-bit float, read raw")
node("StickyNote", "LENS_INFO", 664, -552, label=info, note_font_size=13)

plate = read("READ_ORIGINAL_PLATE", N["plate"], F1, F2, 518, -549)
ref = None
if HAS_REF:
    backdrop("BD_TRACKING_REFERENCE", "TRACKING REFERENCE", 1155, -679, 300, 282, 0x5f5f3fff)
    ref = read("TRACKING_REFERENCE_FLATTEN", N["tracking_reference_flatten"], N["flatten_first"], N["flatten_last"],
         1205, -550, offset=N["flatten_frame_offset"], missing_black=True,
         label=(REF_LABEL[N.get("flatten_role") or "reference"]
                if N.get("flatten_mode", "reference_ai_tracking") == "reference_ai_tracking"
                else "Companion production flatten (reference)"))

st_u = read("READ_STMAP_UNDISTORT", N["stmap_undistort"], 1, 1, 742, -246, raw=True, hold=True)
crop = node("Crop", "CROP_BLACK_OUTSIDE", 518, -305, [plate], box=[0, 0, SW, SH], crop=True, reformat=False)
und = stmap("APPLY_UNDISTORT", 518, -216, crop, st_u)

st_r = read("READ_STMAP_REDISTORT", N["stmap_redistort"], 1, 1, 1220, -240, raw=True, hold=True)
# image input: the tracking reference (Artist reference topology); without one, the earlier example
# input APPLY_UNDISTORT is kept as it is (no-reference behaviour not redesigned here)
stmap("APPLY_REDISTORT", 1031, -210, ref if ref is not None else und, st_r,
      label="example input -- reconnect to your comp result")

nuke.scriptSave(nk_path)
print("written", nk_path, len(nuke.allNodes()))

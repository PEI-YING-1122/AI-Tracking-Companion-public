"""Write the Artist lens handoff / example setup.  Run inside Nuke:

    Nuke13.2.exe -t nk_writer_artist.py <spec.json> <out.nk>

Native nodes only, absolute production paths from the shot spec.  Layout and node
set follow the Artist reference (export/nuke_reference); it shows how the STMaps
connect and is NOT a comp template: no COMP_INPUT / COMP_OUTPUT / Write / Switch /
QC nodes.

    SOURCE      READ_ORIGINAL_PLATE   TRACKING_REFERENCE_FLATTEN   LENS_INFO
    UNDISTORT   READ_ORIGINAL_PLATE -> CROP_BLACK_OUTSIDE -> APPLY_UNDISTORT <- READ_STMAP_UNDISTORT
    REDISTORT   TRACKING_REFERENCE_FLATTEN (example input) -> APPLY_REDISTORT <- READ_STMAP_REDISTORT
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


backdrop("BD_SOURCE", "SOURCE", -856, -1056, 953, 294, 0x3f4f5fff)
backdrop("BD_UNDISTORT", "UNDISTORT", -856, -731, 438, 300, 0x4f5f3fff)
backdrop("BD_REDISTORT", "REDISTORT", -340, -738, 437, 307, 0x5f3f4fff)

info = (f"{shot}\n"
        f"plate {SW}x{SH}   frames {F1}-{F2}   fps {fps:g} ({L['source']['fps_source']})\n"
        f"undistort {UW}x{UH}\n"
        f"STMap production mode: converged canvas, 32-bit float, read raw\n\n"
        f"This setup demonstrates lens undistort / redistort connections.\n"
        f"Reconnect APPLY_REDISTORT to the comp result as needed.")
node("StickyNote", "LENS_INFO", -682, -1008, label=info, note_font_size=13)

plate = read("READ_ORIGINAL_PLATE", N["plate"], F1, F2, -806, -924)
ref = None
if N.get("tracking_reference_flatten"):   # flatten_mode "none" -> no reference flatten in the setup
    ref = read("TRACKING_REFERENCE_FLATTEN", N["tracking_reference_flatten"], N["flatten_first"], N["flatten_last"],
               -293, -927, offset=N["flatten_frame_offset"], missing_black=True,
               label=("AI Tracking flatten (reference)" if N.get("flatten_mode", "reference_ai_tracking") == "reference_ai_tracking"
                      else "Companion production flatten (reference)"))

st_u = read("READ_STMAP_UNDISTORT", N["stmap_undistort"], 1, 1, -582, -621, raw=True, hold=True)
crop = node("Crop", "CROP_BLACK_OUTSIDE", -806, -680, [plate], box=[0, 0, SW, SH], crop=True, reformat=False)
und = stmap("APPLY_UNDISTORT", -806, -591, crop, st_u)

st_r = read("READ_STMAP_REDISTORT", N["stmap_redistort"], 1, 1, -104, -615, raw=True, hold=True)
stmap("APPLY_REDISTORT", -293, -585, ref if ref is not None else und, st_r,
      label="example input -- reconnect to your comp result")

nuke.scriptSave(nk_path)
print("written", nk_path, len(nuke.allNodes()))

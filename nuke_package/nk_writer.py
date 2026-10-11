"""Write <shot>_lens_setup.nk with native Nuke nodes only.  Run inside Nuke:

    Nuke13.2.exe -t nk_writer.py <shot>_lens.json <out.nk>

_nuke.path_mode:
  "absolute" (production): every Read/Write points at the shot's real asset path,
              resolved per shot by common/path_resolver.py -- nothing is copied.
  "relative" (PoC package): paths relative to the .nk via Root.project_directory.
_nuke.graph:
  "artist_core"  : production path only (no QC nodes, no tracking reference).
  "developer_qc" : production path + the QC graph of TEST 03 / Revision 01.

Spaces (Revision 01):
  production  = original full-res plate -> production undistort STMap
                (converged full-res canvas).  COMP_INPUT, REDISTORT, DELIVERY.
  tracking    = AI Tracking proxy flatten (images_undistorted).  QC area only,
                read as TRACKING_REFERENCE_FLATTEN.
"""
import json
import sys

import nuke

lens_path, nk_path = sys.argv[1:3]
L = json.load(open(lens_path))
N = L["_nuke"]
shot = L["shot"]
SW, SH = L["source"]["resolution"]
UW, UH = L["production_canvas"]["resolution"]
UCX, UCY = L["production_canvas"]["principal_point"]
PW, PH = L["tracking"]["proxy_resolution"]
QW, QH = L["tracking"]["proxy_undistorted_resolution"]
QCX, QCY = L["tracking"]["proxy_undistorted_principal_point"]
off = int(L["tracking"]["frame_offset_tracking_to_source"] or 0)
PATH_MODE = N.get("path_mode", "relative")
GRAPH = N.get("graph", "developer_qc")
F1, F2 = L["source"]["first_frame"], L["source"]["last_frame"]

# save first so relative paths resolve against the script directory while building
nuke.scriptSaveAs(nk_path, overwrite=1)
root = nuke.root()
if PATH_MODE == "relative":
    root["project_directory"].setValue("[python {nuke.script_directory()}]")
root["fps"].setValue(L["source"]["fps"])
root["first_frame"].setValue(F1)
root["last_frame"].setValue(F2)
FMT_PLATE, FMT_PROD = f"{shot}_plate", f"{shot}_production_canvas"
for w, h, name in ((SW, SH, FMT_PLATE), (UW, UH, FMT_PROD),
                   (PW, PH, f"{shot}_tracking_proxy"), (QW, QH, f"{shot}_tracking_flatten")):
    nuke.addFormat(f"{w} {h} 1 {name}")
root["format"].setValue(FMT_PLATE)


def node(cls, name, x, y, inputs=(), **knobs):
    n = getattr(nuke.nodes, cls)()
    n.setName(name)
    for i, inp in enumerate(inputs):
        if inp is not None:
            n.setInput(i, inp)
    for k, v in knobs.items():
        n[k].setValue(v)
    n.setXYpos(x, y)
    return n


def read(name, path, first, last, x, y, raw=False, hold=False, offset=0, missing_black=False, fmt=None):
    n = node("Read", name, x, y)
    n["file"].fromUserText(path)  # sets file + detects range/format from disk (if present)
    n["file"].setValue(path)      # keep the literal relative string
    n["first"].setValue(first)
    n["last"].setValue(last)
    n["origfirst"].setValue(first)
    n["origlast"].setValue(last)
    if fmt:
        n["format"].setValue(fmt)
    if raw:
        n["raw"].setValue(True)   # STMaps are DATA: no colour transform
    if hold:
        n["before"].setValue("hold")
        n["after"].setValue("hold")
    if offset:
        n["frame_mode"].setValue("offset")
        # measured: Nuke Read "offset" mode reads file frame = current frame + value,
        # so tracking frame k shown at source frame k+off needs value -off
        n["frame"].setValue(str(-offset))
    if missing_black:
        n["on_error"].setValue("black")
    return n


def crop_black(name, x, y, inp, w, h):
    return node("Crop", name, x, y, [inp], box=[0, 0, w, h], crop=True, reformat=False)


def stmap(name, x, y, src, st):
    # input0 = source image, input1 = STMap (measured in TEST 02A)
    n = node("STMap", name, x, y, [src, st])
    n["uv"].fromScript("rgb")
    n["filter"].setValue("Keys")  # least resampling bias in TEST 02A (mean 0.006 px)
    return n


def backdrop(label, x, y, w, h, color):
    b = nuke.nodes.BackdropNode(xpos=x, ypos=y, bdwidth=w, bdheight=h, tile_color=color, note_font_size=36)
    b["label"].setValue(label)
    b.setName("BD_" + label.split()[0].replace("/", "_"))
    return b


cam = L["camera"]
info = (f"{shot}  lens setup  (Companion {L['companion_version']})\n"
        f"source {SW}x{SH}  frames {F1}-{F2}  fps {L['source']['fps']:.3f} [fps_source: {L['source']['fps_source']}]\n"
        f"tracking proxy {PW}x{PH} -> tracking flatten {QW}x{QH}  frames {L['tracking']['first_frame']}-{L['tracking']['last_frame']} "
        f"(source {L['tracking']['first_frame_in_source_numbering']}-{L['tracking']['last_frame_in_source_numbering']})\n"
        f"PRODUCTION canvas {UW}x{UH}  pp ({UCX:.4f}, {UCY:.4f})  [converged canvas, not proxy x scale]\n"
        f"model {cam['colmap_model']}  focal {cam['full_res']['focal_mm']:.4f}mm (36mm sensor)  "
        f"fx {cam['full_res']['fx']:.4f} fy {cam['full_res']['fy']:.4f}  plate pp ({cam['full_res']['cx']:.2f}, {cam['full_res']['cy']:.2f})\n"
        f"k1 {cam['distortion']['k1']:.8f} k2 {cam['distortion']['k2']} k3 {cam['distortion']['k3']} "
        f"k4 {cam['distortion']['k4']} p1 {cam['distortion']['p1']} p2 {cam['distortion']['p2']}\n"
        f"redistort_solver {L['redistort_solver']}\n"
        f"STMap: U=(col+0.5)/W  V=1-(row+0.5)/H (top-origin row) == (y_nuke+0.5)/H ; no extra Y flip\n"
        f"metadata: {N.get('lens_json', f'../metadata/{shot}_lens.json')}")

# ---------------------------------------------------------------- SOURCE
backdrop("SOURCE", -900, -760, 760, 480, 0x3f4f5fff)
plate = read("READ_ORIGINAL_PLATE", N["plate"], N["plate_first"], N["plate_last"], -850, -620)
node("StickyNote", "LENS_INFO", -620, -640, label=info, note_font_size=13)

# ---------------------------------------------------------------- UNDISTORT / TRACKING (production undistort)
backdrop("UNDISTORT / TRACKING", -900, -240, 760, 560, 0x4f5f3fff)
st_u = read("READ_STMAP_UNDISTORT", N["stmap_undistort"], 1, 1, -700, -180, raw=True, hold=True)
crop_p = crop_black("CROP_PLATE_BLACK_OUTSIDE", -850, -120, plate, SW, SH)
und = stmap("APPLY_UNDISTORT", -850, -40, crop_p, st_u)
und_live = node("NoOp", "UNDISTORT_LIVE", -850, 40, [und],
                label=f"live production undistort {UW}x{UH}")
prod_flat = read("PRODUCTION_FLATTEN", N["production_flatten"], F1, F2, -500, -180, fmt=FMT_PROD)
prod_flat["label"].setValue(f"pre-rendered production flatten {UW}x{UH}\n(= UNDISTORT_LIVE, also for Maya image plane)")
switch = node("Switch", "COMP_SOURCE_SWITCH", -500, 40, [prod_flat, und_live], which=0,
              label="0 = PRODUCTION_FLATTEN (default)\n1 = UNDISTORT_LIVE")

# ---------------------------------------------------------------- COMP SPACE
backdrop("COMP SPACE", -100, -240, 360, 560, 0x5f4f3fff)
comp_in = node("NoOp", "COMP_INPUT", -50, 40, [switch], label=f"comp starts here ({UW}x{UH} production space)")
comp_out = node("NoOp", "COMP_OUTPUT", -50, 160, [comp_in], label="comp ends here")

# ---------------------------------------------------------------- REDISTORT / DELIVERY
backdrop("REDISTORT / DELIVERY", 300, -240, 560, 560, 0x5f3f4fff)
st_r = read("READ_STMAP_REDISTORT", N["stmap_redistort"], 1, 1, 520, 100, raw=True, hold=True)
crop_c = crop_black("CROP_COMP_BLACK_OUTSIDE", 350, 160, comp_out, UW, UH)
red = stmap("APPLY_REDISTORT", 350, 210, crop_c, st_r)
wr = node("Write", "DELIVERY_OUTPUT", 350, 270, [red], tile_color=0xbf2020ff,
          label="SET PER PROJECT DELIVERY SPEC\n(format / bit depth / colorspace / naming)")
wr["file"].setValue(N["delivery"])
wr["file_type"].setValue("exr")
wr["create_directories"].setValue(True)
node("StickyNote", "DELIVERY_SPEC_NOTE", 520, 200, note_font_size=14,
     label="DELIVERY_OUTPUT is a placeholder.\nIts EXR type / colorspace are Nuke defaults,\n"
           "NOT a delivery spec. Configure per project\nbefore rendering.")

if GRAPH == "developer_qc":
    # ---------------------------------------------------------------- QC (never on the production path)
    backdrop("QC", -900, 400, 1760, 620, 0x3f3f5fff)
    # QC1: production flatten (file) vs live production undistort
    node("Merge2", "QC_DIFFERENCE", -500, 700, [prod_flat, und_live], operation="difference",
         label="QC1 PRODUCTION_FLATTEN vs full-res STMap result")
    # QC1A: tracking proxy -> proxy STMap vs tracking reference flatten (tracking space, unchanged upstream)
    ref_flat = read("TRACKING_REFERENCE_FLATTEN", N["tracking_reference_flatten"], N["track_first"], N["track_last"],
                    -700, 460, offset=off, missing_black=True)
    ref_flat["label"].setValue(f"AI Tracking images_undistorted {QW}x{QH}\ntracking solve reference (QC only)")
    prox = read("READ_TRACKING_PROXY_QC", N["proxy"], N["track_first"], N["track_last"], -850, 460, offset=off, missing_black=True)
    st_q = read("READ_STMAP_UNDISTORT_PROXY_QC", N["stmap_proxy_qc"], 1, 1, -850, 520, raw=True, hold=True)
    crop_q = crop_black("CROP_PROXY_BLACK_OUTSIDE", -850, 580, prox, PW, PH)
    und_q = stmap("APPLY_UNDISTORT_PROXY_QC", -850, 640, crop_q, st_q)
    node("Merge2", "QC_DIFFERENCE_PROXY", -850, 700, [und_q, ref_flat], operation="difference",
         label="QC1A tracking reference flatten vs proxy STMap")
    # QC1B: tracking reference mapped into production space (alignment of the two spaces).
    # proxy edge coords -> production: u = s*u_p + (UCX - s*QCX), v = s*v_p + (UCY - s*QCY)
    s = SW / float(PW)
    ty_img = UCY - s * QCY
    ref_fmt = node("Reformat", "TRACKING_REF_TO_PRODUCTION_FORMAT", -650, 580, [ref_flat], type="to format",
                   format=FMT_PROD, resize="none", center=False, black_outside=True)
    ref_x = node("Transform", "TRACKING_REF_TO_PRODUCTION_SPACE", -650, 620, [ref_fmt], scale=s, center=[0, 0],
                 translate=[UCX - s * QCX, UH - s * QH - ty_img], filter="Keys", black_outside=True)
    ref_c = crop_black("TRACKING_REF_CROP_TO_CANVAS", -650, 660, ref_x, UW, UH)
    node("Merge2", "QC_TRACKING_REF_ALIGNMENT", -650, 700, [und_live, ref_c], operation="difference",
         label="QC1B tracking reference (upscaled) vs production\nalignment only, detail differs")
    # QC2: original plate -> production undistort -> production redistort (independent of the comp branch)
    crop_q2 = crop_black("CROP_UNDIST_BLACK_OUTSIDE_QC", -150, 580, und_live, UW, UH)
    red_q = stmap("APPLY_REDISTORT_QC", -150, 640, crop_q2, st_r)
    node("Merge2", "QC_ROUNDTRIP_DIFFERENCE", -150, 700, [red_q, plate], operation="difference",
         label="QC2 original vs production undistort -> redistort")


nuke.scriptSave(nk_path)
print("written", nk_path, "nodes", len(nuke.allNodes()))

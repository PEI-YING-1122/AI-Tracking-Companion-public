"""v0.2.1 workstation setup and compatibility fixes (needs the local test data; Houdini / Maya / Nuke for the builds).

    python tests/test_v021_fixes.py <out.json> [--no-builds]

PNG      PNG / uppercase PNG / JPEG sequences, unrelated PNGs in the same folder, frame range / count /
         resolution, default 24 fps, Artist override, EXR / JPG / video Checks unchanged,
         clearer "no frames" and "AI Tracking working images" messages
FLATTEN  production / reference / incompatible policy incl. a synthetic near-threshold case and the
         0.01 / 0.05 px boundaries; direct-mode note / warning; shot-config mode still BLOCKED
NUKE     Root name finalised (Nuke 17 style stage path), stage leaks of STMap / plate / Maya
         loader / metadata still FAIL, redistort input always APPLY_UNDISTORT, tracking reference
         independent, Nuke target = lowest detected version, override kept
CONFIG   Houdini / Maya / Nuke / FFmpeg / AI Tracking detection on a synthetic install tree,
         site.json generation, missing tool / invalid path / placeholder / invalid JSON,
         Workstation Setup window, Configure_Companion.bat, first-run "Workstation Setup Required"
         in the GUI and BLOCKED (not FileNotFoundError) in the CLI
DEPLOY   setup.bat local-disk guard: local OK, UNC share and mapped network drive blocked
BUILDS   PNG plate full build (incompatible flatten: no image plane, no Nuke reference),
         reference-compatible full build (image plane, Nuke reference, 9 files published),
         production-compatible Nuke build (wiring, Root name)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for sub in ("common", "nuke_package", "gui"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import cv2  # noqa: E402
import test_paths as tp  # noqa: E402
import auto_detect  # noqa: E402
import build_transaction as bt  # noqa: E402
import companion_meta as cm  # noqa: E402
import companion_run as cr  # noqa: E402
import workstation as ws  # noqa: E402

PY = sys.executable
R = {}
NOT_RUN = {}   # test -> why (private fixture / test data missing); never counted as a pass
try:   # test data + private baseline shot (tests/local_test_config.json); without them: fixture-free parts only
    BL = tp.baseline_shot()
    SQ = BL["shot"]
    SQ_IN = json.load(open(BL["shot_config"]))["vars"]["input_root"]
    MOCK_C_IN = tp.workflow("mock_project_C", "io", "tracking")
    MOCK_C_PLATES = tp.workflow("mock_project_C", "io", "in", "plates", "CC_0030_bg01")
    WF_IN = tp.poc("walking-forest")
    SCRATCH = tp.workflow("work", "v021")
    HAVE_DATA, NO_DATA = True, None
except (tp.TestDataNotConfigured, OSError, KeyError) as e:
    BL = SQ = SQ_IN = MOCK_C_IN = MOCK_C_PLATES = WF_IN = None
    SCRATCH = tempfile.mkdtemp(prefix="v021_public_").replace("\\", "/")
    HAVE_DATA, NO_DATA = False, f"test data / private fixture not configured ({e})"
WORK = SCRATCH + "/work"


def ok(name, cond, **info):
    R[name] = dict(info, ok=bool(cond))
    print(f"{'OK ' if cond else 'BAD'} {name}", flush=True)


def cli(*args, env=None):
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", COMPANION_WORK_ROOT=WORK, **(env or {}))
    r = subprocess.run([PY, os.path.join(ROOT, "companion_run.py"), *args], capture_output=True, text=True, env=e, cwd=ROOT)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("@@RESULT ")]
    res = json.load(open(line[-1].split(" ", 1)[1])) if line else {}
    res["_rc"] = r.returncode
    if not line:
        res["_out"] = (r.stdout + r.stderr)[-2000:]
    return res


def codes(res):
    return [i["code"] for i in res.get("issues", [])]


def text(res):
    return " ".join([i["message"] for i in res.get("issues", [])] + [n["message"] for n in res.get("notes", [])])


# ------------------------------------------------------------------ PNG
def make_plates():
    src = sorted(f for f in os.listdir(MOCK_C_PLATES) if f.endswith(".jpg"))
    d_png, d_up, d_jpeg = (os.path.join(SCRATCH, "plates", k) for k in ("png", "png_upper", "jpeg"))
    for d in (d_png, d_up, d_jpeg):
        os.makedirs(d, exist_ok=True)
    for f in src:
        stem = os.path.splitext(f)[0]
        img = cv2.imread(os.path.join(MOCK_C_PLATES, f))
        cv2.imwrite(os.path.join(d_png, stem + ".png"), img)
        os.link(os.path.join(d_png, stem + ".png"), os.path.join(d_up, stem + ".PNG"))
        os.link(os.path.join(MOCK_C_PLATES, f), os.path.join(d_jpeg, stem + ".jpeg"))
    small = img[:64, :48]
    for n in range(1001, 1011):  # unrelated sequences in the same folder: never mixed in
        cv2.imwrite(os.path.join(d_png, f"other_shot.{n}.png"), small)
        cv2.imwrite(os.path.join(d_png, f"CC_0030_bg01_v002.{n}.png"), small)
    cv2.imwrite(os.path.join(d_png, "CC_0030_bg01_v001.thumb.png"), small)
    first = os.path.splitext(src[0])[0]
    return {"png": f"{d_png}/{first}.png", "png_upper": f"{d_up}/{first}.PNG", "jpeg": f"{d_jpeg}/{first}.jpeg",
            "n": len(src), "w": img.shape[1], "h": img.shape[0], "first": int(first.rsplit(".", 1)[1])}


def test_png(pl):
    n, f1 = pl["n"], pl["first"]
    for key in ("png", "png_upper", "jpeg"):
        res = cli("--input", MOCK_C_IN, "--shot", "CC_0030", "--plate", pl[key], "--export", SCRATCH + "/export_check",
                  "--dry-run")
        c = res.get("check") or {}
        kind = {"png": "png_sequence", "png_upper": "png_sequence", "jpeg": "jpg_sequence"}[key]
        ok(f"PNG_{key}_check", res.get("status") in ("PASS", "WARNING") and c.get("plate", {}).get("kind") == kind
           and c.get("frames", {}).get("source") == [f1, f1 + n - 1] and c.get("frames", {}).get("count") == n
           and c.get("resolution", {}).get("source") == [pl["w"], pl["h"]] and c.get("fps") == 24.0
           and c.get("fps_source") == "default" and "unsupported" not in codes(res),
           status=res.get("status"), plate=c.get("plate"), frames=c.get("frames"), resolution=c.get("resolution"),
           fps=[c.get("fps"), c.get("fps_source")], issues=codes(res), out=res.get("_out"))
    res = cli("--input", MOCK_C_IN, "--shot", "CC_0030", "--plate", pl["png"], "--export", SCRATCH + "/export_check",
              "--fps", "25", "--dry-run")
    c = res.get("check") or {}
    ok("PNG_artist_fps_override", c.get("fps") == 25.0 and c.get("fps_source") == "artist_override",
       fps=[c.get("fps"), c.get("fps_source")])
    # the Artist's sequence only, even with other PNG sequences in the folder
    cand = auto_detect._candidate_from_path(pl["png"])
    ok("PNG_mixed_folder_sequence", cand and len(cand["frames"]) == n and cand["frames"][0] == f1
       and all("other_shot" not in f and "_v002." not in f and "thumb" not in f for f in cand["files"]),
       pattern=cand and cand["pattern"], frames=cand and len(cand["frames"]))
    pat = cand["pattern"]
    meta_files = cm.pattern_files(pat)
    ok("PNG_pattern_files_exact", len(meta_files) == n and [k for k, _ in meta_files] == list(range(f1, f1 + n)),
       count=len(meta_files))
    tif = os.path.join(SCRATCH, "plates", "tif_only")
    os.makedirs(tif, exist_ok=True)
    cv2.imwrite(os.path.join(tif, "x.1001.tif"), cv2.imread(pl["png"]))
    try:
        cm.probe_sequence(tif)
        msg = ""
    except cm.UnsupportedScene as e:
        msg = str(e)
    src = open(os.path.join(ROOT, "common", "companion_meta.py"), encoding="utf-8").read()
    ok("PNG_error_message", "No supported image-sequence frames (EXR/JPG/JPEG/PNG)" in msg
       and "No EXR/JPG frames" not in src, message=msg)
    # AI Tracking working images stay BLOCKED, with the clearer message
    work_img = os.path.join(MOCK_C_IN, "CC_0030_bg01", "images", "frame_000001.jpg").replace("\\", "/")
    res = cli("--input", MOCK_C_IN, "--shot", "CC_0030", "--plate", work_img, "--export", SCRATCH + "/export_check",
              "--dry-run")
    ok("PLATE_working_images_blocked", res.get("status") == "BLOCKED" and "Do not select AI Tracking working images. "
       "Select the original distorted production plate." in text(res), status=res.get("status"), message=text(res))
    # EXR / JPG / video Checks unchanged
    for key, plate, inp, shot, kind, fps_src in (
            ("exr", BL["plate_exr"], SQ_IN, SQ, "exr_sequence", "exr_header"),
            ("jpg", BL["plate_jpg"], SQ_IN, SQ, "jpg_sequence", "default"),
            ("video", video_path(), WF_IN, "WF_0010", "video", "ffprobe")):
        res = cli("--input", inp, "--shot", shot, "--plate", plate, "--export", SCRATCH + f"/export_{key}", "--dry-run")
        c = res.get("check") or {}
        ok(f"PNG_no_regression_{key}", res.get("status") in ("PASS", "WARNING") and c.get("plate", {}).get("kind") == kind
           and c.get("fps_source") == fps_src, status=res.get("status"), kind=c.get("plate", {}).get("kind"),
           fps=[c.get("fps"), c.get("fps_source")], frames=c.get("frames"))


def video_path():
    import site_config
    return os.path.join(site_config.get("upstream_repo"), "demo-test", "walking-forest",
                        "12588331_720_1280_24fps.mp4").replace("\\", "/")


# ------------------------------------------------------------------ FLATTEN
def flat_case(tmp, dx, dy, n_flat=10, reg=10, size=(100, 50), src=(100, 50), prod_size=None):
    d = os.path.join(tmp, f"flat_{n_flat}")
    os.makedirs(d, exist_ok=True)
    for k in range(1, n_flat + 1):
        open(os.path.join(d, f"frame_{k:06d}.jpg"), "w").close()
    meta = {"tracking": {"proxy_width": size[0], "proxy_height": size[1], "registered_frames": reg},
            "source": {"width": src[0], "height": src[1]}}
    ps = prod_size or [120, 60]
    smeta = {"legacy_canvas": [120, 60, 60.25, 30.25], "canvas": [ps[0], ps[1], 60.25 + dx, 30.25 + dy]}
    return meta, smeta, {"inputs": {"tracking_flatten_dir": d}, "options": {"flatten_mode": "reference_ai_tracking"}}


def test_flatten():
    tmp = tempfile.mkdtemp(prefix="v021_flat_")
    cases = {
        "production_tiny": ((0.000127, 0.0000487), {}, "production_compatible"),
        "synthetic_0p011": ((0.011, 0.006), {}, "reference_compatible"),
        "just_below_0p01": ((0.0099, 0.0), {}, "production_compatible"),
        "just_above_0p01": ((0.0100001, 0.0), {}, "reference_compatible"),
        "just_below_0p05": ((0.0499999, -0.0499999), {}, "reference_compatible"),
        "just_above_0p05": ((0.0500001, 0.0), {}, "incompatible"),
        "above_0p05": ((0.0501, 0.0), {}, "incompatible"),
        "canvas_size_differs": ((0.0, 0.0), {"prod_size": [122, 60]}, "incompatible"),
        "frames_missing": ((0.0, 0.0), {"n_flat": 9}, "incompatible"),
        "resolution_differs": ((0.0, 0.0), {"size": (50, 25)}, "incompatible"),
    }
    got = {}
    for name, ((dx, dy), kw, want) in cases.items():
        meta, smeta, Rr = flat_case(tmp, dx, dy, **kw)
        f = cr.flatten_compatibility(meta, smeta, Rr)
        got[name] = {"status": f["status"], "want": want, "role": f["role"], "tolerance_px": f["tolerance_px"],
                     "pp_delta_px": f["pp_delta_px"]}
    ok("FLATTEN_policy_table", all(v["status"] == v["want"] for v in got.values()), cases=got)
    c = got["synthetic_0p011"]
    ok("FLATTEN_synthetic_case_reference", c["status"] == "reference_compatible" and c["role"] == "reference_only"
       and c["tolerance_px"] == cr.PP_TOL_REFERENCE == 0.05 and cr.PP_TOL_PRODUCTION == 0.01, case=c)
    os.environ["COMPANION_TEST_PP_TOL_PRODUCTION"] = "0.5"   # the test hook can only tighten
    loosen = cr.production_pp_tol()
    del os.environ["COMPANION_TEST_PP_TOL_PRODUCTION"]
    ok("FLATTEN_test_hook_cannot_loosen", loosen == cr.PP_TOL_PRODUCTION, value=loosen)

    # direct mode: reference -> used + note (no flatten_not_used); incompatible -> WARNING, not used
    meta, smeta, Rr = flat_case(tmp, 0.011, 0.006)
    Rr["options"]["flatten_fallback_none"] = True
    rec = bt.BuildRecord(None, "t", "t")
    f = cr.resolve_flatten(meta, smeta, Rr, rec)
    notes = [n["message"] for n in rec.extra.get("notes", [])]
    ok("FLATTEN_reference_direct_mode", f and f["status"] == "reference_compatible" and rec.status == "PASS"
       and Rr["options"]["flatten_mode"] == "reference_ai_tracking"
       and any(n.startswith("Tracking Flatten: Reference Only") for n in notes)
       and not any(i["code"] == "flatten_not_used" for i in rec.issues), notes=notes, issues=rec.issues)
    meta, smeta, Rr = flat_case(tmp, 0.08, 0.0)
    Rr["options"]["flatten_fallback_none"] = True
    rec = bt.BuildRecord(None, "t", "t")
    f = cr.resolve_flatten(meta, smeta, Rr, rec)
    ok("FLATTEN_incompatible_direct_mode", f is None and rec.status == "WARNING" and Rr["options"]["flatten_mode"] == "none"
       and any(i["message"].startswith("Tracking flatten is incompatible and was not used.") for i in rec.issues),
       issues=[i["message"] for i in rec.issues])
    meta, smeta, Rr = flat_case(tmp, 0.08, 0.0)
    try:
        cr.resolve_flatten(meta, smeta, Rr, bt.BuildRecord(None, "t", "t"))
        blocked = None
    except bt.BuildStop as e:
        blocked = (e.level, e.code)
    ok("FLATTEN_incompatible_config_mode_blocked", blocked == ("BLOCKED", "flatten_space"), got=blocked)
    meta, smeta, Rr = flat_case(tmp, 0.011, 0.0)
    rec = bt.BuildRecord(None, "t", "t")
    ok("FLATTEN_reference_config_mode_used", (cr.resolve_flatten(meta, smeta, Rr, rec) or {}).get("status")
       == "reference_compatible" and rec.status == "PASS")
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ NUKE (no Nuke needed)
NK17 = """#! C:/Program Files/Nuke17.0v1/nuke-17.0.1.dll -nx
version 17.0 v1
Root {
 inputs 0
 frame 1001
 name "@STAGE@/nuke/sh_lens_setup.nk"
 first_frame 1001
 last_frame 1010
}
Read {
 inputs 0
 file "@STMAP@"
 name READ_STMAP_UNDISTORT
}
Read {
 inputs 0
 file "@PLATE@"
 name READ_ORIGINAL_PLATE
}
"""


def test_nuke_text():
    import build_nuke_package as bnp
    tmp = tempfile.mkdtemp(prefix="v021_nk_")
    stage = tmp.replace("\\", "/") + "/work/builds/20261012-000000-abcdef/stage"
    final = tmp.replace("\\", "/") + "/export dir/nuke/sh_lens_setup.nk"

    def nk(stmap, plate, name_line=True):
        t = NK17.replace("@STAGE@", stage).replace("@STMAP@", stmap).replace("@PLATE@", plate)
        if not name_line:
            t = t.replace(f' name "{stage}/nuke/sh_lens_setup.nk"\n', "")
        p = os.path.join(tmp, f"case_{len(os.listdir(tmp))}.nk")
        open(p, "w", encoding="utf-8", newline="\n").write(t)
        return p
    good_st, good_pl = "X:/export/lens/sh_undistort_stmap.exr", "X:/plates/sh.%04d.exr"
    p = nk(good_st, good_pl)
    before = cr.stage_leaks({"nuke_setup": p}, stage)
    bnp.finalize_root_name(p, final)
    after = open(p, encoding="utf-8").read()
    root = after.split("Root {", 1)[1].split("\n}", 1)[0]
    ok("NUKE_root_name_finalized", before == ["nuke_setup"] and cr.stage_leaks({"nuke_setup": p}, stage) == []
       and f' name "{final}"' in root and root.count(" name ") == 1 and "name READ_STMAP_UNDISTORT" in after
       and good_st in after and good_pl in after, root=root)
    p = nk(good_st, good_pl, name_line=False)
    bnp.finalize_root_name(p, final)
    ok("NUKE_root_name_inserted_when_absent", open(p, encoding="utf-8").read().split("Root {\n", 1)[1].startswith(
        f' inputs 0\n name "{final}"\n'))
    p = nk(stage + "/lens/sh_undistort_stmap.exr", good_pl)
    bnp.finalize_root_name(p, final)
    ok("NUKE_stage_leak_stmap_fails", cr.stage_leaks({"nuke_setup": p}, stage) == ["nuke_setup"])
    p = nk(good_st, stage + "/plate/sh.%04d.exr")
    bnp.finalize_root_name(p, final)
    ok("NUKE_stage_leak_plate_fails", cr.stage_leaks({"nuke_setup": p}, stage) == ["nuke_setup"])
    loader = os.path.join(tmp, "sh_load_maya.py")
    open(loader, "w").write(f'METADATA_ABS = r"{stage}/metadata/sh_metadata.json"\n')
    md = os.path.join(tmp, "sh_metadata.json")
    json.dump({"maya": {"loader": stage + "/maya/sh_load_maya.py"}}, open(md, "w"))
    ok("NUKE_stage_leak_maya_loader_fails", cr.stage_leaks({"maya_loader": loader}, stage) == ["maya_loader"])
    ok("NUKE_stage_leak_metadata_fails", cr.stage_leaks({"metadata": md}, stage.replace("/", "\\")) == ["metadata"])
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ CONFIG
def fake_tree(base):
    def exe(*p):
        path = os.path.join(base, *p)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
        return path.replace("\\", "/")
    pf = os.path.join(base, "Program Files")
    t = {"pf": pf,
         "houdini": [exe(pf, "Side Effects Software", "Houdini 20.0.547", "bin", "hython.exe"),
                     exe(pf, "Side Effects Software", "Houdini 20.5.410", "bin", "hython.exe")],
         "maya": [exe(pf, "Autodesk", "Maya2024", "bin", "mayapy.exe")],
         "nuke17": exe(pf, "Nuke17.0v1", "Nuke17.0.exe"), "nuke16": exe(pf, "Nuke16.0v1", "Nuke16.0.exe"),
         "ffmpeg": exe(base, "Tools", "ffmpeg-7.1", "bin", "ffmpeg.exe"),
         "ffprobe": exe(base, "Tools", "ffmpeg-7.1", "bin", "ffprobe.exe"),
         "home": os.path.join(base, "home")}
    exe(pf, "Nuke17.0v1", "python.exe")                       # not a Nuke executable
    exe(pf, "Autodesk", "3ds Max 2022", "3dsmax.exe")          # not Maya
    ai = os.path.join(t["home"], "Downloads", "AI_Tracking", "colmap-camera-tracking-master")
    for f in ws.UPSTREAM_FILES:
        exe(ai, f)
    deep = os.path.join(t["home"], "Desktop", "a", "b", "c", "d", "colmap-deep")
    for f in ws.UPSTREAM_FILES:
        exe(deep, f)                                           # deeper than the search limit
    t["ai"], t["ai_deep"] = ai.replace("\\", "/"), deep.replace("\\", "/")
    return t


def test_config():
    tmp = tempfile.mkdtemp(prefix="v021_cfg_")
    t = fake_tree(tmp)
    roots = [t["pf"]]
    search = [os.path.join(t["home"], d) for d in ("Downloads", "Desktop", "Documents")] + [os.path.join(tmp, "Tools")]
    found = ws.detect_all(roots, search)
    ok("CONFIG_detect_houdini", [f["path"] for f in found["hython"]] == t["houdini"]
       and ws.default_choice("hython", found["hython"]) == t["houdini"][1], found=found["hython"])
    ok("CONFIG_detect_maya", [f["path"] for f in found["mayapy"]] == t["maya"], found=found["mayapy"])
    ok("CONFIG_detect_multiple_nuke", [f["version"] for f in found["nuke"]] == ["16.0v1", "17.0v1"], found=found["nuke"])
    ok("CONFIG_nuke_lowest_default", ws.default_choice("nuke", found["nuke"]) == t["nuke16"],
       default=ws.default_choice("nuke", found["nuke"]))
    ok("CONFIG_nuke_override_kept", ws.default_choice("nuke", found["nuke"], current=t["nuke17"]) == t["nuke17"])
    ok("CONFIG_detect_ffmpeg_ffprobe", found["ffmpeg"] and found["ffmpeg"][0]["ffmpeg"] == t["ffmpeg"]
       and ws.default_choice("ffprobe", found["ffmpeg"]) == t["ffprobe"], found=found["ffmpeg"])
    ok("CONFIG_detect_ai_tracking_limited", [f["path"] for f in found["upstream_repo"]] == [t["ai"]],
       found=found["upstream_repo"])
    site = os.path.join(tmp, "configs", "site.json")
    os.makedirs(os.path.dirname(site))
    json.dump({"_comment": "old", "work_root": "D:/companion_work", "nuke": "<placeholder>"}, open(site, "w"))
    values = {"hython": t["houdini"][1], "mayapy": t["maya"][0], "nuke": t["nuke16"], "ffmpeg": t["ffmpeg"],
              "ffprobe": t["ffprobe"], "upstream_repo": t["ai"]}
    probs = ws.save(values, site)
    data = json.load(open(site))
    ok("CONFIG_save_valid_site_json", probs == [] and all(data[k] == v for k, v in values.items())
       and data["work_root"] == "D:/companion_work" and ws.status(site)["ok"], problems=probs, data=data)
    sha = hashlib.sha256(open(site, "rb").read()).hexdigest()
    bad = dict(values, nuke=os.path.join(tmp, "Program Files", "Nuke99.0v1", "Nuke99.0.exe"))
    p1 = ws.save(bad, site)
    bad2 = dict(values, nuke=os.path.join(t["pf"], "Nuke17.0v1", "python.exe").replace("\\", "/"))
    p2 = ws.save(bad2, site)
    bad3 = dict(values, upstream_repo="<AI Tracking install>/colmap-camera-tracking-master", ffmpeg="")
    p3 = ws.save(bad3, site)
    unchanged = hashlib.sha256(open(site, "rb").read()).hexdigest() == sha
    ok("CONFIG_missing_tool_not_saved", p1 and p1[0]["message"].startswith("Nuke path not found") and unchanged, problems=p1)
    ok("CONFIG_invalid_path_not_saved", p2 and "is not the Nuke program" in p2[0]["message"] and unchanged, problems=p2)
    ok("CONFIG_placeholder_not_saved", {p["key"] for p in p3} == {"upstream_repo", "ffmpeg"}
       and any("placeholder" in p["message"] for p in p3) and unchanged, problems=p3)
    broken = os.path.join(tmp, "configs", "broken.json")
    open(broken, "w").write('{"nuke": "C:/Program Files/Nuke16.0v1/Nuke16.0.exe,\n "hython": 1}')
    st = ws.status(broken)
    ok("CONFIG_invalid_json_reported", not st["ok"] and "not valid" in st["problems"][0]["message"], problems=st["problems"])
    ok("CONFIG_nuke_version_parse", ws.nuke_version("C:/Program Files/Nuke16.0v1/Nuke16.0.exe") == "16.0v1"
       and ws.nuke_version("C:/x/Nuke17.0.exe") == "17.0")

    # Workstation Setup window: Nuke 16 by default, override to 17, Save writes valid site.json
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import workstation_setup
    site2 = os.path.join(tmp, "configs", "site2.json")
    saved = []
    w = workstation_setup.SetupWindow(site_path=site2, program_roots=roots, search_roots=search, on_saved=saved.append)
    default_nuke = w.value("nuke")
    labels = [w.combos["nuke"].itemText(i) for i in range(w.combos["nuke"].count())]
    w.set_value("nuke", t["nuke17"])
    r1 = w.save()
    d2 = json.load(open(site2)) if os.path.exists(site2) else {}
    ok("CONFIG_setup_window_save", default_nuke == t["nuke16"] and len(labels) == 2 and r1 and saved == [site2]
       and d2.get("nuke") == t["nuke17"] and d2.get("upstream_repo") == t["ai"] and ws.status(site2)["ok"],
       default=default_nuke, labels=labels, saved=d2)
    w.set_value("mayapy", os.path.join(tmp, "nowhere", "mayapy.exe"))
    r2 = w.save()
    ok("CONFIG_setup_window_refuses_invalid", r2 is False and "Maya path not found" in w.message.text()
       and json.load(open(site2)) == d2, message=w.message.text())
    w.close()

    # first run: no / placeholder site.json -> GUI shows Workstation Setup Required + Configure
    import companion_gui as G
    opened = []
    first = {}
    for case, path in (("missing", os.path.join(tmp, "configs", "nothing_here.json")),
                       ("placeholder", os.path.join(ROOT, "configs", "site.example.json"))):
        os.environ["COMPANION_SITE_CONFIG"] = path
        try:
            g = G.MainWindow(open_setup=lambda parent: opened.append(parent))
            g.configure_btn.click()
            first[case] = {"visible": g.setup_box.isVisibleTo(g), "title": g.setup_box.title(), "text": g.setup_text.text()}
            g.close()
        finally:
            del os.environ["COMPANION_SITE_CONFIG"]
    g = G.MainWindow()
    configured = not g.setup_box.isVisibleTo(g)
    nuke_row = g.fields["Nuke Generator"].text()
    g.close()
    ok("CONFIG_first_run_gui_prompt", first["missing"]["visible"] and first["placeholder"]["visible"]
       and first["missing"]["title"] == "Workstation Setup Required"
       and "Workstation configuration not found" in first["missing"]["text"]
       and "Nuke path is still a placeholder" in first["placeholder"]["text"]
       and "AI Tracking path is still a placeholder" in first["placeholder"]["text"]
       and len(opened) == 2 and configured and nuke_row.startswith("ⓘ ") and ws.status()["nuke_version"] in nuke_row,
       first=first, configured_hidden=configured, nuke_row=nuke_row)
    if not HAVE_DATA:
        NOT_RUN["CONFIG_first_run_cli_blocked"] = NOT_RUN["CONFIG_missing_nuke_cli_blocked"] = NO_DATA
    else:
        config_cli_checks(tmp)
    test_config_launcher(tmp)


def config_cli_checks(tmp):
    res = cli("--input", SQ_IN, "--shot", SQ, "--plate", BL["plate_exr"], "--export", SCRATCH + "/export_cfg", "--dry-run",
              env={"COMPANION_SITE_CONFIG": os.path.join(tmp, "configs", "nothing_here.json")})
    ok("CONFIG_first_run_cli_blocked", res.get("status") == "BLOCKED" and codes(res) == ["workstation_setup"]
       and "Workstation Setup Required" in text(res) and "FileNotFoundError" not in text(res),
       status=res.get("status"), issues=res.get("issues"))
    res = cli("--input", SQ_IN, "--shot", SQ, "--plate", BL["plate_exr"], "--export", SCRATCH + "/export_cfg", "--dry-run",
              "--outputs", "nuke", env={"COMPANION_NUKE": os.path.join(tmp, "nowhere", "Nuke16.0.exe")})
    ok("CONFIG_missing_nuke_cli_blocked", res.get("status") == "BLOCKED" and "Nuke path not found" in text(res),
       message=text(res))


def test_config_launcher(tmp):

    # Configure_Companion.bat starts the Workstation Setup window with the Companion's environment
    flag = os.path.join(tmp, "setup_selftest.json")
    env = dict(os.environ, COMPANION_SETUP_SELFTEST=flag)
    env.pop("QT_QPA_PLATFORM", None)
    rc = subprocess.run(["cmd", "/c", os.path.join(ROOT, "Configure_Companion.bat")], env=env).returncode
    t0 = time.time()
    while not os.path.exists(flag) and time.time() - t0 < 60:
        time.sleep(0.5)
    rep = json.load(open(flag)) if os.path.exists(flag) else {}
    ok("CONFIG_configure_bat_launches", rc == 0 and rep.get("visible") is True and "Workstation Setup" in rep.get("title", "")
       and rep.get("python", "").lower().endswith(os.path.join(".venv", "scripts", "pythonw.exe")), rc=rc, report=rep)
    data = open(os.path.join(ROOT, "Configure_Companion.bat"), "rb").read()
    ok("CONFIG_configure_bat_crlf", b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""))
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ DEPLOY
def setup_check(path):
    r = subprocess.run(["cmd", "/c", path, "/check-location", "/nopause"], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def test_deploy():
    local = os.path.join(ROOT, "setup.bat")
    rc, out = setup_check(local)
    ok("DEPLOY_local_disk_ok", rc == 0 and "Local disk: OK" in out, rc=rc, out=out)
    drive = ROOT[0]
    unc = f"\\\\localhost\\{drive}$" + ROOT[2:]
    if os.path.exists(unc):
        rc, out = setup_check(os.path.join(unc, "setup.bat"))
        ok("DEPLOY_unc_share_blocked", rc == 3 and "Companion runtime must be installed on a local disk." in out
           and ws.is_network_path(unc), rc=rc, out=out[-400:])
        free = next((d for d in "QRSTUVWXYZ" if not os.path.exists(f"{d}:\\")), None)
        m = subprocess.run(["net", "use", f"{free}:", f"\\\\localhost\\{drive}$", "/persistent:no"], capture_output=True)
        if m.returncode == 0:
            try:
                rc, out = setup_check(f"{free}:" + ROOT[2:] + "\\setup.bat")
                mapped_py = ws.is_network_path(f"{free}:" + ROOT[2:])
            finally:
                subprocess.run(["net", "use", f"{free}:", "/delete", "/y"], capture_output=True)
            ok("DEPLOY_mapped_drive_blocked", rc == 3 and "must be installed on a local disk" in out and mapped_py,
               drive=free, rc=rc)
        else:
            R["DEPLOY_mapped_drive_blocked"] = {"ok": True, "skipped": "net use not possible on this machine"}
    else:
        R["DEPLOY_unc_share_blocked"] = {"ok": True, "skipped": "no administrative share"}
    ok("DEPLOY_python_local_not_network", not ws.is_network_path(ROOT))


# ------------------------------------------------------------------ BUILDS (Houdini / Maya / Nuke)
def nk_root_name(path):
    root = open(path, encoding="utf-8").read().split("Root {", 1)[1].split("\n}", 1)[0]
    line = [ln for ln in root.split("\n") if ln.startswith(" name ")]
    return line[0][6:].strip().strip('"') if line else None


def verify_of(shot):
    return json.load(open(os.path.join(WORK, shot, f"{shot}_verify.json")))


MODIFY_NK = (tp.root() + "/company/artist_reference/topology_reference.nk") if HAVE_DATA else None   # Artist wiring reference (external test fixture)


LAYOUT_NK = (tp.root() + "/company/artist_reference/layout_reference.nk") if HAVE_DATA else None  # Artist layout reference (final, outside git)
NODE_NAMES = {"BD_SOURCE", "BD_UNDISTORT", "BD_REDISTORT", "LENS_INFO", "READ_ORIGINAL_PLATE", "CROP_BLACK_OUTSIDE",
              "READ_STMAP_UNDISTORT", "APPLY_UNDISTORT", "READ_STMAP_REDISTORT", "APPLY_REDISTORT"}
REF_NODES = {"BD_TRACKING_REFERENCE", "TRACKING_REFERENCE_FLATTEN"}


def lens_info_expected(md):
    s, p, c = md["source"], md["production_canvas"], md["shot_name"]
    return (f"{c}\nplate {s['resolution'][0]}x{s['resolution'][1]}   frames {s['first_frame']}-{s['last_frame']}"
            f"   fps {s['fps']:g}\nundistort {p['resolution'][0]}x{p['resolution'][1]}\n"
            "STMap production mode: converged canvas, 32-bit float, read raw")


def graph_checks(nkp, nk, has_ref, md):
    """connection topology of the PUBLISHED .nk (stack / set / push, as Nuke reads it) and in Nuke;
    layout, node names and LENS_INFO against the Artist references"""
    import nk_topology
    got = nk_topology.connections(nkp, classes=("STMap", "Crop"))
    label = nk_topology.sticky_label(nkp)
    lay, ref_lay = nk_topology.layout(nkp), nk_topology.layout(LAYOUT_NK, strip_suffix=True)
    names = set(lay)
    want_names = NODE_NAMES | (REF_NODES if has_ref else set())
    tag = "ref" if has_ref else "noref"
    ok(f"NUKE_lens_info_text_{tag}", label == lens_info_expected(md), label=label, expected=lens_info_expected(md))
    ok(f"NUKE_fps_source_suffix_removed_{tag}", label is not None and "(" not in label.split("\n")[1]
       and md["source"]["fps_source"] not in label, line=label and label.split("\n")[1], fps_source=md["source"]["fps_source"])
    ok(f"NUKE_layout_matches_artist_reference_{tag}", all(lay[n] == ref_lay[n] for n in want_names)
       and (has_ref or not (names & REF_NODES)),
       diff={n: [lay.get(n), ref_lay.get(n)] for n in want_names if lay.get(n) != ref_lay.get(n)})
    ok(f"NUKE_node_names_unchanged_{tag}", names == want_names, names=sorted(names))
    if not has_ref:  # agreed fallback (decision A): no reference -> APPLY_UNDISTORT feeds APPLY_REDISTORT
        ok("NUKE_no_reference_fallback", got.get("APPLY_REDISTORT") == ["APPLY_UNDISTORT", "READ_STMAP_REDISTORT"]
           and got.get("APPLY_UNDISTORT") == ["CROP_BLACK_OUTSIDE", "READ_STMAP_UNDISTORT"]
           and got.get("CROP_BLACK_OUTSIDE") == ["READ_ORIGINAL_PLATE"], connections=got)
        return
    ok("NUKE_layout_reference_same_connections", nk_topology.connections(LAYOUT_NK, classes=("STMap", "Crop")) and {
        k.rstrip("1"): [x.rstrip("1") if x else x for x in v]
        for k, v in nk_topology.connections(LAYOUT_NK, classes=("STMap", "Crop")).items()} == got)
    ref = nk_topology.connections(MODIFY_NK, classes=("STMap", "Crop"))
    ok("NUKE_undistort_connection", got.get("APPLY_UNDISTORT") == ["CROP_BLACK_OUTSIDE", "READ_STMAP_UNDISTORT"]
       and got.get("CROP_BLACK_OUTSIDE") == ["READ_ORIGINAL_PLATE"]
       and nk.get("apply_undistort_inputs") == ["CROP_BLACK_OUTSIDE", "READ_STMAP_UNDISTORT"], file=got, nuke=nk.get("apply_undistort_inputs"))
    ok("NUKE_redistort_connection", got.get("APPLY_REDISTORT") == ["TRACKING_REFERENCE_FLATTEN", "READ_STMAP_REDISTORT"]
       and nk.get("apply_redistort_inputs") == ["TRACKING_REFERENCE_FLATTEN", "READ_STMAP_REDISTORT"],
       file=got.get("APPLY_REDISTORT"), nuke=nk.get("apply_redistort_inputs"))
    ok("NUKE_redistort_not_from_undistort", got.get("APPLY_REDISTORT", [None])[0] != "APPLY_UNDISTORT"
       and nk.get("apply_redistort_inputs", [None])[0] != "APPLY_UNDISTORT")
    ok("NUKE_topology_equals_artist_reference", got == ref, companion=got, artist_reference=ref)


def test_builds(pl):
    # 1) PNG plate, full build; mock C's tracking is a proxy -> flatten incompatible -> not used
    exp = SCRATCH + "/export_png"
    res = cli("--input", MOCK_C_IN, "--shot", "CC_0030", "--plate", pl["png"], "--export", exp)
    v = verify_of("CC_0030") if res.get("status") in ("PASS", "WARNING") else {}
    md = json.load(open(exp + "/metadata/CC_0030_metadata.json")) if os.path.exists(exp + "/metadata/CC_0030_metadata.json") else {}
    nodes = (v.get("nuke") or {}).get("nodes", [])
    ok("BUILD_png_plate_full", res.get("status") in ("PASS", "WARNING") and len(res.get("published", [])) == 9
       and v.get("summary", {}).get("pass") and md.get("source", {}).get("kind") == "png_sequence"
       and md.get("source", {}).get("fps_source") == "default"
       and (v.get("nuke") or {}).get("reads", {}).get("READ_ORIGINAL_PLATE", {}).get("file", "").endswith(".%04d.png"),
       status=res.get("status"), published=len(res.get("published", [])), issues=codes(res),
       failed=[k for k, x in v.get("summary", {}).get("checks", {}).items() if not x], out=res.get("_out"))
    ok("FLATTEN_incompatible_build", "flatten_incompatible" in codes(res)
       and "Tracking flatten is incompatible and was not used." in text(res)
       and md.get("flatten", {}).get("compatibility_status") == "incompatible" and md.get("flatten", {}).get("role") == "not_used"
       and not (v.get("maya_loader") or {}).get("image_plane") and "TRACKING_REFERENCE_FLATTEN" not in nodes
       and "BD_TRACKING_REFERENCE" not in nodes, flatten=md.get("flatten"), nodes=nodes)
    if os.path.exists(exp + "/nuke/CC_0030_lens_setup.nk"):
        graph_checks(exp + "/nuke/CC_0030_lens_setup.nk", v.get("nuke") or {}, has_ref=False, md=md)

    # 2) reference compatible (production tolerance tightened below this shot's 0.000127 px)
    exp = SCRATCH + "/export_ref"
    res = cli("--input", SQ_IN, "--shot", SQ, "--plate", BL["plate_exr"], "--export", exp,
              env={"COMPANION_TEST_PP_TOL_PRODUCTION": "0.0001"})
    v = verify_of(SQ) if res.get("status") in ("PASS", "WARNING") else {}
    mdp = f"{exp}/metadata/{SQ}_metadata.json"
    md = json.load(open(mdp)) if os.path.exists(mdp) else {}
    fl = md.get("flatten", {})
    nk = v.get("nuke") or {}
    ip = (v.get("maya_loader") or {}).get("image_plane") or {}
    ok("BUILD_reference_publish_9_files", res.get("status") in ("PASS", "WARNING") and len(res.get("published", [])) == 9
       and v.get("summary", {}).get("pass"), status=res.get("status"), issues=res.get("issues"),
       failed=[k for k, x in v.get("summary", {}).get("checks", {}).items() if not x], out=res.get("_out"))
    ok("FLATTEN_reference_metadata", fl.get("mode") == "reference_ai_tracking" and fl.get("compatibility_status") == "reference_compatible"
       and fl.get("role") == "reference_only" and fl.get("tolerance_px") == 0.05 and fl.get("lens_source") is False
       and fl.get("pp_delta_px") and "flatten_not_used" not in codes(res)
       and "Tracking Flatten: Reference Only" in text(res), flatten={k: fl.get(k) for k in (
           "mode", "compatibility_status", "role", "pp_delta_px", "tolerance_px", "lens_source")})
    ok("MAYA_image_plane_reference", bool(ip) and ip.get("node", "").endswith("_IMAGEPLANEShape")
       and all(x["exists"] for x in ip.get("mapping", {}).values())
       and v["summary"]["checks"].get("maya_loader_image_plane") is True, image_plane=ip)
    ok("NUKE_tracking_reference_present", "TRACKING_REFERENCE_FLATTEN" in nk.get("nodes", [])
       and "BD_TRACKING_REFERENCE" in nk.get("nodes", [])
       and nk.get("tracking_reference_label") == "AI Tracking flatten \u2014 reference only"
       and v["summary"]["checks"].get("nuke_reference_feeds_redistort_only") is True,
       label=nk.get("tracking_reference_label"))
    nkp = f"{exp}/nuke/{SQ}_lens_setup.nk"
    graph_checks(nkp, nk, has_ref=True, md=md)
    ok("NUKE_root_name_final_path", os.path.exists(nkp) and nk_root_name(nkp) == nkp
       and "/stage/" not in open(nkp, encoding="utf-8").read(), root_name=os.path.exists(nkp) and nk_root_name(nkp))
    ok("NUKE_generator_recorded", (md.get("nuke") or {}).get("generator", {}).get("version") == ws.status()["nuke_version"],
       generator=(md.get("nuke") or {}).get("generator"))

    # 3) production compatible, Nuke only
    exp = SCRATCH + "/export_prod"
    res = cli("--input", SQ_IN, "--shot", SQ, "--plate", BL["plate_exr"], "--export", exp, "--outputs", "nuke")
    v = verify_of(SQ) if res.get("status") in ("PASS", "WARNING") else {}
    nk = v.get("nuke") or {}
    md = json.load(open(f"{exp}/metadata/{SQ}_metadata.json")) if os.path.exists(f"{exp}/metadata/{SQ}_metadata.json") else {}
    nkp = f"{exp}/nuke/{SQ}_lens_setup.nk"
    ok("FLATTEN_production_build", res.get("status") in ("PASS", "WARNING") and v.get("summary", {}).get("pass")
       and md.get("flatten", {}).get("compatibility_status") == "production_compatible"
       and md.get("flatten", {}).get("role") == "reference"
       and nk.get("tracking_reference_label") == "AI Tracking flatten (reference)"
       and nk.get("apply_redistort_inputs") == ["TRACKING_REFERENCE_FLATTEN", "READ_STMAP_REDISTORT"]
       and nk_root_name(nkp) == nkp, status=res.get("status"), issues=codes(res),
       flatten=md.get("flatten", {}).get("compatibility_status"), label=nk.get("tracking_reference_label"))


def main():
    out = sys.argv[1]
    builds = "--no-builds" not in sys.argv
    shutil.rmtree(SCRATCH, ignore_errors=True)
    os.makedirs(SCRATCH)
    pl = None
    if HAVE_DATA:
        pl = make_plates()
        test_png(pl)
    else:
        NOT_RUN["PNG_* / PLATE_working_images_blocked (plate resolver on test shots)"] = NO_DATA
    test_flatten()
    test_nuke_text()
    test_config()
    test_deploy()
    if builds and HAVE_DATA:
        test_builds(pl)
    elif builds:
        NOT_RUN["BUILD_* / NUKE_* graph / MAYA_* (Houdini / Maya / Nuke builds on test shots)"] = NO_DATA
    R["not_run"] = NOT_RUN
    passed = all(v["ok"] for v in R.values() if isinstance(v, dict) and "ok" in v)
    R["all_ok"] = passed and not NOT_RUN
    json.dump(R, open(out, "w", encoding="utf-8"), indent=1, default=str, ensure_ascii=False)
    for k, why in NOT_RUN.items():
        print(f"NOT RUN {k}: {why}")
    print("ALL OK" if R["all_ok"] else f"PASSED, {len(NOT_RUN)} NOT RUN" if passed else "FAILURES")
    sys.exit(0 if R["all_ok"] else 3 if passed else 1)


if __name__ == "__main__":
    main()

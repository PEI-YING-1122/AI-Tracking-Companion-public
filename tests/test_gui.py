"""GUI validation (headless, QT_QPA_PLATFORM=offscreen): the real MainWindow driving the real CLI
in direct mode (no project config).

    python tests/test_gui.py <out.json>

GUI UX revision 02 list (T-numbers) + kept checks:
  T01 no Project dropdown                    T13 Start (fresh export, BUILD COMPLETE)
  T02 empty Shot Name -> BLOCKED             T14 Stop during preflight      -> Cancelled, export unchanged
  T03 Original Plate required                T15 Stop during stage (lens)   -> Cancelled, export unchanged
  T04 AI Tracking Folder -> export default   T16 Stop during validation     -> Cancelled, export unchanged
  T05 existing export folder not deleted     T17 Stop just before publish   -> Cancelled, export unchanged
  T06 missing export folder is created       T18 Stop disabled during publish (publish completes)
  T07 unrelated export files untouched       T19 existing delivery -> Cancel -> export unchanged
  T08 FPS from video metadata                T20 existing delivery -> Overwrite -> backup + publish
  T09 FPS from EXR header                    T21 Tracking Scene / Camera labels
  T10 JPG without FPS -> 24 Default, Ready   T22 Frames "<first>–<last> (<n> frames)"
  T11 Artist FPS override                    T23 launcher starts the GUI (AI_Tracking_Companion.bat)
  T12 Check (demo)
  K1 fisheye BLOCKED   K2 multi-cams BLOCKED   K3 runtime failure (validation fault) -> FAIL, export unchanged
  K4 button states while running / publishing / idle
  P  GUI vs CLI parity: the GUI's own arguments straight through the CLI give the identical Check result
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "gui"))
import test_paths as tp  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402
import companion_gui as G  # noqa: E402

PY = sys.executable
BASE = tp.baseline("demo_sh0010")
SQ_IN = json.load(open(BASE + "/demo_sh0010.json"))["vars"]["input_root"]
SQ_PLATES = os.path.normpath(os.path.join(SQ_IN, "..", "source", "plate_demo_sh0010")).replace("\\", "/")
SQ_EXR = SQ_PLATES + "/exr/plate_demo_sh0010.1001.exr"
SQ_JPG = SQ_PLATES + "/jpg/plate_demo_sh0010.1001.jpg"
WF_IN = tp.poc("walking-forest")
MOCK_C_IN = tp.workflow("mock_project_C", "io", "tracking")
SCRATCH = tp.workflow("work", "scratch_gui")
FRESH = SCRATCH + "/export_demo"
ENV = {"COMPANION_WORK_ROOT": SCRATCH + "/work"}   # builds of this suite never touch other work folders
SQ = "demo_sh0010"
app = QApplication.instance() or QApplication(sys.argv)


# ------------------------------------------------------------------ helpers
def settle(win, timeout=1800):
    """until the CLI chain (detect -> check, or start) is finished"""
    t = time.time()
    while time.time() - t < timeout:
        QTest.qWait(150)
        if not win.runner.busy() and win.mode is None:
            QTest.qWait(150)
            if not win.runner.busy() and win.mode is None:
                return
    raise TimeoutError("GUI did not settle")


def wait_log(win, text, timeout=1200):
    t = time.time()
    while time.time() - t < timeout:
        QTest.qWait(100)
        if text in win.log.toPlainText():
            return True
        if not win.runner.busy() and win.mode is None:
            return False
    return False


def window(folder, shot="", plate="", export="", maya=True, nuke=True, answer=None, env=None):
    asked, infos = [], []

    def confirm():
        asked.append(True)
        return bool(answer)
    w = G.MainWindow(confirm_overwrite=confirm, extra_env=dict(ENV, **(env or {})),
                     show_info=lambda t, x: infos.append((t, x)))
    w.asked, w.infos = asked, infos
    w.shot.setText(shot)
    w.plate.setText(plate)
    w.export.setText(export)
    w.maya.setChecked(maya)
    w.nuke.setChecked(nuke)
    w.input.setText(folder)
    w._new_folder()  # what choosing the folder does: detect, then Check when shot + plate are filled
    settle(w)
    return w


def check(w):
    w.run_check()
    settle(w)
    return w.last_check or {}


def start(w):
    w.run_build()
    settle(w)
    return w.last_result or {}


def view(w):
    return {"status": w.status.text(), "messages": w.messages.text(), "fields": {k: v.text() for k, v in w.fields.items()},
            "fps": w.fps.text(), "fps_source": w.fps_source.text(), "export": w.export.text(),
            "buttons": {"check": w.check_btn.isEnabled(), "start": w.start_btn.isEnabled(), "stop": w.stop_btn.isEnabled()},
            "result_visible": w.result_box.isVisibleTo(w), "result": w.result_text.text(), "progress": w.progress.text()}


VOLATILE = ("build_id", "elapsed_s", "steps", "created", "build_dir", "log")


def strip(res):
    return {k: v for k, v in res.items() if k not in VOLATILE}


def parity(w):
    args = w._common_args() + ["--dry-run"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **ENV)
    r = subprocess.run([PY, G.CLI, *args], capture_output=True, text=True, env=env, cwd=ROOT)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("@@RESULT ")]
    cli = json.load(open(line[-1].split(" ", 1)[1])) if line else {}
    gui = w.last_check or {}
    diff = sorted(k for k in set(strip(cli)) | set(strip(gui)) if strip(cli).get(k) != strip(gui).get(k))
    return {"cli_rc": r.returncode, "same": not diff and bool(cli), "diff_keys": diff}


def sha_tree(d):
    out = {}
    for b, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(b, f)
            out[os.path.relpath(p, d)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def published(res):
    return sorted({p["path"].replace("\\", "/").split("/")[-2] for p in res.get("published", [])})


def stop_at(where, outputs_nuke_only=False, hold_s="60"):
    """Start an overwrite build that holds at `where`, press Stop there, return (window, result)"""
    before = sha_tree(FRESH)
    w = window(SQ_IN, SQ, SQ_EXR, FRESH, maya=not outputs_nuke_only, answer=True,
               env={"COMPANION_TEST_HOLD": where, "COMPANION_TEST_HOLD_S": hold_s})
    w.run_build()
    reached = wait_log(w, f"@@HOLD {where}")
    states = view(w)["buttons"]
    w.stop()
    settle(w)
    res = w.last_result or {}
    return w, {"reached": reached, "buttons_while_running": states, "status": res.get("status"),
               "gui_status": w.status.text(), "messages": w.messages.text(), "published": published(res),
               "export_unchanged": sha_tree(FRESH) == before,
               "ok": reached and res.get("status") == "CANCELLED" and w.status.text() == "Cancelled"
               and sha_tree(FRESH) == before and not res.get("published")
               and states == {"check": False, "start": False, "stop": True}
               and view(w)["buttons"]["check"] and "Stopped by the Artist" in w.messages.text()}


def make_unsupported(kind):
    """AI Tracking folder like mock C's but with a fisheye / two-camera solve.  Hard links (no copies of
    images); the edited text files are written fresh (never through a link)."""
    src = os.path.join(MOCK_C_IN, "CC_0030_bg01")
    out = os.path.join(SCRATCH, "fixtures", kind)
    scene = os.path.join(out, "CC_0030_bg01")
    shutil.rmtree(out, ignore_errors=True)
    edit = {os.path.normcase(os.path.join(src, "sparse", "cameras.txt")),
            os.path.normcase(os.path.join(src, "sparse", "0", "cameras.txt"))}
    for b, _, fs in os.walk(src):
        rel = os.path.relpath(b, src)
        os.makedirs(os.path.join(scene, rel), exist_ok=True)
        for f in fs:
            s = os.path.join(b, f)
            if os.path.normcase(s) not in edit:
                os.link(s, os.path.join(scene, rel, f))
    if kind == "fisheye":
        cams = "# fixture\n1 OPENCV_FISHEYE 360 480 273.6 273.6 180 240 0.01 0.0 0.0 0.0\n"
    else:
        cams = "# fixture\n1 SIMPLE_RADIAL 360 480 273.6 180 240 -0.08\n2 SIMPLE_RADIAL 360 480 290.0 180 240 -0.05\n"
    for p in (os.path.join(scene, "sparse", "cameras.txt"), os.path.join(scene, "sparse", "0", "cameras.txt")):
        open(p, "w").write(cams)
    tj = json.load(open(os.path.join(MOCK_C_IN, "CC_0030_bg01_transforms.json")))
    if kind == "fisheye":
        tj["is_fisheye"] = True
    else:
        for k in ("fl_x", "fl_y", "cx", "cy", "w", "h", "k1", "k2", "k3", "k4", "p1", "p2"):
            tj.pop(k, None)
    json.dump(tj, open(os.path.join(out, "CC_0030_bg01_transforms.json"), "w"), indent=1)
    return out


def launcher_test():
    flag = os.path.join(SCRATCH, "launcher_selftest.json")
    if os.path.exists(flag):
        os.remove(flag)
    env = dict(os.environ, COMPANION_GUI_SELFTEST=flag)
    env.pop("QT_QPA_PLATFORM", None)  # the real platform, like a double-click
    rc = subprocess.run(["cmd", "/c", os.path.join(ROOT, "AI_Tracking_Companion.bat")], env=env).returncode
    t = time.time()
    while not os.path.exists(flag) and time.time() - t < 60:
        time.sleep(0.5)
    rep = json.load(open(flag)) if os.path.exists(flag) else {}
    return {"rc": rc, "report": rep, "ok": rc == 0 and rep.get("visible") is True
            and rep.get("python", "").lower().endswith(os.path.join(".venv", "scripts", "pythonw.exe"))
            and rep.get("cli_python", "").lower().endswith("python.exe") and rep.get("has_project_field") is False}


# ------------------------------------------------------------------ scenarios
def main():
    out = sys.argv[1]
    shutil.rmtree(SCRATCH, ignore_errors=True)
    os.makedirs(SCRATCH)
    R, P = {}, {}

    # T01 / T04 -------------------------------------------------------------------------------
    w = window(SQ_IN)
    R["T01_no_project_dropdown"] = {"ok": not hasattr(w, "project") and not w.findChildren(QComboBox)}
    R["T04_export_default"] = {"export": w.export.text(), "ok": w.export.text() == SQ_IN.rstrip("/") + "/export"}
    # info icons: text only after a click
    w.plate_info.click()
    w.fps_info.click()
    R["info_icons"] = {"shown": [t for t, _ in w.infos],
                       "ok": [t for t, _ in w.infos] == ["Original Plate", "FPS"]
                       and "For an image sequence, select any frame" in w.infos[0][1]
                       and "default is 24 fps" in w.infos[1][1] and "select any frame" not in view(w)["messages"]}

    # T02 / T03 -------------------------------------------------------------------------------
    w = window(SQ_IN, plate=SQ_EXR, export=FRESH)
    check(w)
    v = view(w)
    R["T02_empty_shot"] = {"view": v, "ok": v["status"] == "BLOCKED" and "Please enter a Shot Name." in v["messages"]
                           and not v["buttons"]["start"]}
    P["T02"] = parity(w)
    w = window(SQ_IN, shot=SQ, export=FRESH)
    check(w)
    v = view(w)
    R["T03_plate_required"] = {"view": v, "ok": v["status"] == "BLOCKED" and "Please select the Original Plate." in v["messages"]
                               and not v["buttons"]["start"]}

    # T12 / T09 / T21 / T22 -------------------------------------------------------------------
    w = window(SQ_IN, SQ, SQ_EXR, FRESH)
    v = view(w)
    f = v["fields"]
    R["T12_check"] = {"view": v, "ok": v["status"] == "Ready" and v["buttons"] == {"check": True, "start": True, "stop": False}}
    R["T09_fps_exr_header"] = {"fps": v["fps"], "src": v["fps_source"], "field": f["FPS"],
                               "ok": v["fps"] == "24" and v["fps_source"] == "Source: EXR Header" and "24 (EXR Header)" in f["FPS"]}
    R["T21_scene_camera_labels"] = {"scene": f["Tracking Scene"], "camera": f["Camera"],
                                    "ok": f["Tracking Scene"].startswith("✓ ") and f["Camera"].startswith("✓ Ready")
                                    and "jpg" not in f["Camera"]}
    R["T22_frames"] = {"frames": f["Frames"], "resolution": f["Resolution"],
                       "internal_in_log": "Tracking frames " in w.log.toPlainText(),
                       "ok": f["Frames"].startswith("✓ ") and f["Frames"].endswith(" frames)") and "tracking" not in f["Frames"]
                       and f["Resolution"].startswith("✓ ") and " → " in f["Resolution"]
                       and "Tracking frames " in w.log.toPlainText()}
    P["T12"] = parity(w)

    # T06 / T13 Start into a missing export folder ----------------------------------------------
    existed = os.path.exists(FRESH)
    res = start(w)
    v = view(w)
    R["T06_export_created"] = {"existed_before": existed, "exists_after": os.path.isdir(FRESH),
                               "ok": not existed and os.path.isdir(FRESH)}
    R["T13_start"] = {"view": v, "asked": len(w.asked), "status": res.get("status"), "published": published(res),
                      "ok": res.get("status") in ("PASS", "WARNING") and not w.asked and v["status"] == "BUILD COMPLETE"
                      and v["result_visible"] and f"Export Folder: {FRESH}" in v["result"]
                      and all(f"{g}: built" in v["result"] for g in ("Maya", "Nuke", "Lens", "Metadata"))
                      and "Done" in v["progress"] and v["buttons"]["check"] and not v["buttons"]["start"]}

    # unrelated files in the (now existing) export folder ----------------------------------------
    unrelated = {"notes.txt": "artist notes\n", "maya/other_shot_camera.ma": "// not ours\n",
                 "lens/README.txt": "keep\n", "comp/v001/sh.nk": "# not ours\n"}
    for rel, txt in unrelated.items():
        os.makedirs(os.path.dirname(os.path.join(FRESH, rel)), exist_ok=True)
        open(os.path.join(FRESH, rel), "w").write(txt)
    unrelated_sha = {rel: hashlib.sha256(open(os.path.join(FRESH, rel), "rb").read()).hexdigest() for rel in unrelated}
    marker_ino = os.stat(os.path.join(FRESH, "notes.txt")).st_ino

    # T19 existing delivery -> Cancel --------------------------------------------------------------
    w = window(SQ_IN, SQ, SQ_EXR, FRESH, answer=False)
    before, nb = sha_tree(FRESH), len(os.listdir(os.path.join(SCRATCH, "work", SQ, "builds")))
    shown = view(w)
    w.run_build()
    settle(w)
    R["T19_existing_cancel"] = {"asked": len(w.asked), "status": w.status.text(), "export_field": shown["fields"]["Export"],
                                "status_after_check": shown["status"],
                                "ok": w.asked == [True] and w.status.text() == "Cancelled" and sha_tree(FRESH) == before
                                and len(os.listdir(os.path.join(SCRATCH, "work", SQ, "builds"))) == nb
                                and "Existing Companion delivery" in shown["fields"]["Export"] and shown["status"] == "Ready"}

    # T14–T17 Stop -----------------------------------------------------------------------------------
    _, R["T14_stop_preflight"] = stop_at("preflight")
    _, R["T15_stop_stage_lens"] = stop_at("lens")
    _, R["T16_stop_validation"] = stop_at("validate", outputs_nuke_only=True)
    _, R["T17_stop_before_publish"] = stop_at("before_publish", outputs_nuke_only=True)

    # T18 Stop disabled during publish --------------------------------------------------------------
    w = window(SQ_IN, SQ, SQ_EXR, FRESH, maya=False, answer=True,
               env={"COMPANION_TEST_HOLD": "publish", "COMPANION_TEST_HOLD_S": "4"})
    w.run_build()
    reached = wait_log(w, "@@HOLD publish")
    during = view(w)
    w.stop()  # must be ignored
    no_flag = not (w.cancel_file and os.path.exists(w.cancel_file))
    settle(w)
    res = w.last_result or {}
    R["T18_stop_disabled_in_publish"] = {
        "reached": reached, "buttons_during_publish": during["buttons"], "status_during": during["status"],
        "status": res.get("status"), "published": published(res),
        "ok": reached and during["buttons"] == {"check": False, "start": False, "stop": False}
        and during["status"] == "Finishing publish transaction..." and no_flag
        and res.get("status") in ("PASS", "WARNING") and published(res) == ["lens", "metadata", "nuke"]}
    R["K4_button_states"] = {"idle_after_check": R["T12_check"]["view"]["buttons"],
                             "running": R["T14_stop_preflight"]["buttons_while_running"],
                             "publishing": during["buttons"], "after_finish": view(w)["buttons"],
                             "ok": R["T12_check"]["view"]["buttons"] == {"check": True, "start": True, "stop": False}
                             and R["T14_stop_preflight"]["buttons_while_running"] == {"check": False, "start": False, "stop": True}
                             and during["buttons"] == {"check": False, "start": False, "stop": False}
                             and view(w)["buttons"] == {"check": True, "start": False, "stop": False}}

    # T20 existing delivery -> Overwrite (+ T05 / T07) ----------------------------------------------
    w = window(SQ_IN, SQ, SQ_EXR, FRESH, answer=True)
    res = start(w)
    pub = [s for s in res.get("steps", []) if s.get("step") == "publish"]
    R["T20_existing_overwrite"] = {"asked": len(w.asked), "status": res.get("status"), "publish": pub,
                                   "ok": w.asked == [True] and res.get("status") in ("PASS", "WARNING")
                                   and bool(pub and pub[0].get("backed_up")) and published(res) == ["lens", "maya", "metadata", "nuke"]}
    now = {rel: (hashlib.sha256(open(os.path.join(FRESH, rel), "rb").read()).hexdigest()
                 if os.path.exists(os.path.join(FRESH, rel)) else None) for rel in unrelated}
    R["T05_existing_export_kept"] = {"same_folder": os.stat(os.path.join(FRESH, "notes.txt")).st_ino == marker_ino,
                                     "ok": os.stat(os.path.join(FRESH, "notes.txt")).st_ino == marker_ino}
    R["T07_unrelated_files_untouched"] = {"files": now, "ok": now == unrelated_sha}

    # K3 runtime failure ---------------------------------------------------------------------------
    before = sha_tree(FRESH)
    w = window(SQ_IN, SQ, SQ_EXR, FRESH, maya=False, answer=True, env={"COMPANION_FAULT_VALIDATE": "1"})
    res = start(w)
    R["K3_runtime_failure"] = {"status": res.get("status"), "gui": w.status.text(),
                               "ok": res.get("status") == "FAIL" and w.status.text() == "FAIL" and sha_tree(FRESH) == before
                               and not view(w)["result_visible"]}

    # T10 / T11 JPG plate without fps, then Artist override ------------------------------------------
    w = window(SQ_IN, SQ, SQ_JPG, SCRATCH + "/export_jpg")
    v = view(w)
    R["T10_jpg_default_fps"] = {"view": v, "ok": v["status"] == "Ready" and v["fps"] == "24" and v["fps_source"] == "Source: Default"
                                and "ⓘ FPS: 24 (Default)" in v["messages"] and v["buttons"]["start"]}
    P["T10"] = parity(w)
    w.fps.setText("25")
    w._fps_edited()  # what leaving the field does
    settle(w)
    v = view(w)
    c = (w.last_check or {}).get("check") or {}
    R["T11_fps_override"] = {"view": v, "check_fps": c.get("fps"), "check_src": c.get("fps_source"),
                             "ok": c.get("fps") == 25.0 and c.get("fps_source") == "artist_override" and v["fps"] == "25"
                             and v["fps_source"] == "Source: Artist Override" and "--fps" in w.check_args and v["buttons"]["start"]}
    P["T11"] = parity(w)

    # T08 video plate ------------------------------------------------------------------------------
    mp4 = "E:/AI_Tracking/colmap-camera-tracking-master/demo-test/walking-forest/12588331_720_1280_24fps.mp4"
    try:
        import site_config
        mp4 = os.path.join(site_config.get("upstream_repo"), "demo-test", "walking-forest",
                           "12588331_720_1280_24fps.mp4").replace("\\", "/")
    except Exception:  # noqa: BLE001
        pass
    w = window(WF_IN, "WF_0010", mp4, SCRATCH + "/export_wf")
    v = view(w)
    c = (w.last_check or {}).get("check") or {}
    R["T08_fps_video"] = {"view": v, "ok": c.get("fps_source") == "ffprobe" and v["fps"] == "23.976"
                          and v["fps_source"] == "Source: Video Metadata" and v["buttons"]["start"]}
    P["T08"] = parity(w)

    # K1 / K2 unsupported ----------------------------------------------------------------------------
    cdir = tp.workflow("mock_project_C", "io", "in", "plates", "CC_0030_bg01")
    cplate = cdir + "/" + sorted(f for f in os.listdir(cdir) if f.endswith(".jpg"))[0]
    for key, kind in (("K1_fisheye", "fisheye"), ("K2_multicams", "multicams")):
        exp = SCRATCH + f"/export_{kind}"
        w = window(make_unsupported(kind), "CC_0030", cplate, exp)
        v = view(w)
        R[key] = {"view": v, "ok": v["status"] == "BLOCKED" and not v["buttons"]["start"] and "Unsupported" in v["messages"]
                  and not os.path.exists(exp)}
        P[key] = parity(w)

    # T23 launcher ------------------------------------------------------------------------------------
    R["T23_launcher"] = launcher_test()

    R["P_gui_cli_parity"] = {"checks": P, "ok": all(p["same"] for p in P.values())}
    R["all_ok"] = all(v["ok"] for v in R.values() if isinstance(v, dict))
    json.dump(R, open(out, "w", encoding="utf-8"), indent=1, default=str, ensure_ascii=False)
    for k, v in R.items():
        if isinstance(v, dict):
            print(f"{'OK ' if v['ok'] else 'BAD'} {k}")
    print("ALL OK" if R["all_ok"] else "FAILURES")
    shutil.rmtree(FRESH, ignore_errors=True)
    sys.exit(0 if R["all_ok"] else 1)


if __name__ == "__main__":
    main()

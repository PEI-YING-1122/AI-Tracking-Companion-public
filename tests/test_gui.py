"""GUI validation (headless, QT_QPA_PLATFORM=offscreen): the real MainWindow driving the real CLI.

    python tests/test_gui.py <out.json>

Scenarios (numbering = GUI implementation validation list):
   1 demo Check                      detect -> shot / export filled -> Check PASS / WARNING, fields shown
   2 Normal Build                      fresh export: no question asked, BUILD COMPLETE, result summary
   3 Existing export -> Cancel         question answered No: CANCELLED, export untouched, nothing built
   4 Existing export -> Overwrite      question answered Yes: --overwrite, previous delivery backed up
   5 Backup retention                  after more overwrites only 2 backups of this export remain
   6 Missing plate                     BLOCKED, Source Plate field shown, Build disabled
   7 Multiple plate candidates         BLOCKED, candidates offered; pick one -> re-Check passes;
                                       override stored in the shot config and reused by a new window
   8 FPS warning fallback              WARNING "FPS source metadata unavailable. Using project setting: 25 fps."
   9 Fisheye                           BLOCKED (Unsupported)
  10 Multi-cams                        BLOCKED (Unsupported)
  11 Maya-only build                   maya + metadata published, rest kept
  12 Nuke-only build                   nuke + lens (dependency) + metadata published
  13 Full build                        everything published
  14 Runtime failure                   FAIL; export byte-identical (validation fault and mid-publish fault)
  15 GUI vs CLI parity                 for every Check: GUI arguments run directly through the CLI give the
                                       same status / issues / check report the GUI displayed
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
from PySide6.QtWidgets import QApplication  # noqa: E402
import companion_gui as G  # noqa: E402

PY = sys.executable
BASE = tp.baseline("demo_sh0010")
SQ_IN = json.load(open(BASE + "/demo_sh0010.json"))["vars"]["input_root"]
PROJ = BASE + "/projects/demo_project.project.json"
AMB = BASE + "/projects/demo_project.AMBIGUOUS.project.json"
MOCK_C = tp.workflow("projects", "mock_C.project.json")
MOCK_C_IN = tp.workflow("mock_project_C", "io", "tracking")
SCRATCH = tp.workflow("work", "scratch_gui")
FRESH = SCRATCH + "/export_demo"
app = QApplication.instance() or QApplication(sys.argv)


# ------------------------------------------------------------------ helpers
def settle(win, timeout=1800):
    """until the CLI chain (detect -> check, or build) is finished"""
    t = time.time()
    while time.time() - t < timeout:
        QTest.qWait(150)
        if not win.runner.busy() and win.mode is None:
            QTest.qWait(150)
            if not win.runner.busy() and win.mode is None:
                return
    raise TimeoutError("GUI did not settle")


def window(project, folder, shot="", export="", maya=True, nuke=True, answer=None, env=None):
    asked = []

    def confirm():
        asked.append(True)
        return bool(answer)
    w = G.MainWindow(confirm_overwrite=confirm, extra_env=env)
    w.asked = asked
    w.project.addItem(os.path.basename(project), project)
    w.project.setCurrentIndex(w.project.count() - 1)
    w.shot.setText(shot)
    w.export.setText(export)
    w.maya.setChecked(maya)
    w.nuke.setChecked(nuke)
    w.input.setText(folder)
    w.run_detect()  # what choosing the folder does
    settle(w)
    if w.mode is None and w.last_check is None and w.shot.text():
        w.run_check()
        settle(w)
    return w


def check(w):
    w.run_check()
    settle(w)
    return w.last_check or {}


def build(w):
    w.run_build()
    settle(w)
    return w.last_result or {}


def view(w):
    return {"status": w.status.text(), "messages": w.messages.text(), "build_enabled": w.build_btn.isEnabled(),
            "plate_row": w.plate_row.isVisibleTo(w), "fields": {k: v.text() for k, v in w.fields.items()},
            "result_visible": w.result_box.isVisibleTo(w), "result": w.result_text.text(), "progress": w.progress.text()}


VOLATILE = ("build_id", "elapsed_s", "steps", "created", "build_dir", "log")


def strip(res):
    return {k: v for k, v in res.items() if k not in VOLATILE}


def parity(w):
    """15: the GUI's own arguments straight through the CLI -> identical Check report"""
    args = w._common_args() + ["--dry-run"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([PY, G.CLI, *args], capture_output=True, text=True, env=env, cwd=ROOT)
    line = [l for l in r.stdout.splitlines() if l.startswith("@@RESULT ")]
    cli = json.load(open(line[-1].split(" ", 1)[1])) if line else {}
    gui = w.last_check or {}
    return {"cli_rc": r.returncode, "same": strip(cli) == strip(gui),
            "diff_keys": sorted(k for k in set(strip(cli)) | set(strip(gui)) if strip(cli).get(k) != strip(gui).get(k))}


def sha_tree(d):
    out = {}
    for b, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(b, f)
            out[os.path.relpath(p, d)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def backups_of(export_root, work_dir):
    builds = os.path.join(work_dir, "builds")
    n = os.path.normcase(os.path.abspath(export_root))
    out = []
    for d in sorted(os.listdir(builds)):
        b = os.path.join(builds, d, "backup")
        sc = os.path.join(builds, d, "shot_config.json")
        if os.path.isdir(b) and any(os.scandir(b)) and os.path.exists(sc) and \
                os.path.normcase(os.path.abspath(json.load(open(sc)).get("export_root", ""))) == n:
            out.append(d)
    return out


def published(res):
    return sorted({p["path"].replace("\\", "/").split("/")[-2] for p in res.get("published", [])})


def make_unsupported(kind):
    """AI Tracking folder like mock C's but with a fisheye / two-camera solve.  Files are hard links
    (no copies of images); the edited text files are written fresh (never through a link)."""
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


def scratch_project(name, **over):
    p = json.load(open(MOCK_C))
    p["vars"]["root"] = tp.workflow("mock_project_C", "io")
    p.update(work_root=SCRATCH + "/work", export_root=SCRATCH + "/export_{shot}_" + name, **over)
    path = os.path.join(SCRATCH, f"{name}.project.json")
    json.dump(p, open(path, "w"), indent=1)
    return path


# ------------------------------------------------------------------ scenarios
def main():
    out = sys.argv[1]
    shutil.rmtree(SCRATCH, ignore_errors=True)
    os.makedirs(SCRATCH)
    R, P = {}, {}
    sq = "demo_sh0010"
    # builds go to a scratch export AND a scratch work root: the baseline shot's work folder
    # (read by the baseline compare) is never touched by this suite
    proj_gui = json.load(open(PROJ))
    proj_gui["work_root"] = SCRATCH + "/work"
    PROJ_GUI = os.path.join(SCRATCH, "demo_gui.project.json")
    json.dump(proj_gui, open(PROJ_GUI, "w"), indent=1)

    # 1 -----------------------------------------------------------------------------------
    w = window(PROJ, SQ_IN)
    v = view(w)
    c = (w.last_check or {}).get("check", {})
    R["01_demo_check"] = {"view": v, "detect_shot": w.shot.text(), "detect_export": w.export.text(),
                            "ok": w.shot.text() == sq and v["status"].startswith("Ready") and v["build_enabled"]
                            and c.get("camera_model") == "SIMPLE_RADIAL" and v["fields"]["Camera Model"] == "SIMPLE_RADIAL" and v["fields"]["Plate"].startswith(SQ_IN.split("/")[0])
                            and "Existing Delivery Found" in v["fields"]["Existing Delivery"] and not v["plate_row"]}
    P["01"] = parity(w)
    detected_export = w.export.text()

    # 2 normal build into a fresh export --------------------------------------------------
    w = window(PROJ_GUI, SQ_IN, shot=sq, export=FRESH)
    P["02"] = parity(w)
    res = build(w)
    v = view(w)
    R["02_normal_build"] = {"view": v, "asked": len(w.asked), "status": res.get("status"), "published": published(res),
                            "ok": res.get("status") in ("PASS", "WARNING") and not w.asked and v["status"] == "BUILD COMPLETE"
                            and v["result_visible"] and f"Export Folder: {FRESH}" in v["result"] and "Maya: built" in v["result"]
                            and "Nuke: built" in v["result"] and "Lens: built" in v["result"] and "Metadata: built" in v["result"]
                            and "Done" in v["progress"]}
    work_dir = os.path.dirname(os.path.dirname(os.path.dirname(w.runner.result_path)))

    # 3 cancel ----------------------------------------------------------------------------
    w = window(PROJ_GUI, SQ_IN, shot=sq, export=FRESH, answer=False)
    before, nb = sha_tree(FRESH), len(os.listdir(os.path.join(work_dir, "builds")))  # after the Check
    ex_shown = view(w)["fields"]["Existing Delivery"]
    w.run_build()
    settle(w)
    R["03_existing_cancel"] = {"asked": len(w.asked), "status": w.status.text(), "existing_shown": ex_shown,
                               "export_unchanged": sha_tree(FRESH) == before,
                               "builds_added": len(os.listdir(os.path.join(work_dir, "builds"))) - nb,
                               "ok": w.asked == [True] and w.status.text() == "Cancelled" and sha_tree(FRESH) == before
                               and "Existing Delivery Found" in ex_shown}
    R["03_existing_cancel"]["ok"] &= R["03_existing_cancel"]["builds_added"] == 0

    # 4 overwrite -------------------------------------------------------------------------
    w = window(PROJ_GUI, SQ_IN, shot=sq, export=FRESH, answer=True)
    res = build(w)
    bk = [s for s in res.get("steps", []) if s.get("step") == "publish"]
    R["04_existing_overwrite"] = {"asked": len(w.asked), "status": res.get("status"), "publish": bk,
                                  "ok": w.asked == [True] and res.get("status") in ("PASS", "WARNING")
                                  and bool(bk and bk[0].get("backed_up"))}

    # 11 maya only (overwrite) --------------------------------------------------------------
    w = window(PROJ_GUI, SQ_IN, shot=sq, export=FRESH, nuke=False, answer=True)
    P["11"] = parity(w)
    res = build(w)
    R["11_maya_only"] = {"status": res.get("status"), "published": published(res), "result": view(w)["result"],
                         "ok": res.get("status") in ("PASS", "WARNING") and published(res) == ["maya", "metadata"]
                         and "Nuke: kept from build" in view(w)["result"]}

    # 12 nuke only ------------------------------------------------------------------------
    w = window(PROJ_GUI, SQ_IN, shot=sq, export=FRESH, maya=False, answer=True)
    P["12"] = parity(w)
    res = build(w)
    R["12_nuke_only"] = {"status": res.get("status"), "published": published(res), "result": view(w)["result"],
                         "ok": res.get("status") in ("PASS", "WARNING") and published(res) == ["lens", "metadata", "nuke"]
                         and "Maya: kept from build" in view(w)["result"]}
    ret12 = res.get("backup_retention")

    # 13 full -----------------------------------------------------------------------------
    w = window(PROJ_GUI, SQ_IN, shot=sq, export=FRESH, answer=True)
    res = build(w)
    R["13_full"] = {"status": res.get("status"), "published": published(res),
                    "ok": res.get("status") in ("PASS", "WARNING") and published(res) == ["lens", "maya", "metadata", "nuke"]}

    # 5 retention (overwrites 4, 11, 12, 13 each made a backup) ----------------------------
    kept = backups_of(FRESH, work_dir)
    ret = res.get("backup_retention") or {}
    R["05_backup_retention"] = {"backups_of_this_export": kept, "after_12": ret12, "after_13": ret,
                                "ok": len(kept) == 2 and ret.get("keep") == 2 and len(ret.get("pruned", [])) >= 1
                                and kept == sorted(ret.get("kept", []))}

    # 14 runtime failure: validation fault, then a fault in the middle of publishing -------
    r14 = {}
    for name, env in (("validate_fault", {"COMPANION_FAULT_VALIDATE": "1"}), ("publish_fault", {"COMPANION_FAULT_PUBLISH_AFTER": "4"})):
        before = sha_tree(FRESH)
        w = window(PROJ_GUI, SQ_IN, shot=sq, export=FRESH, answer=True, env=env)
        res = build(w)
        r14[name] = {"status": res.get("status"), "gui_status": w.status.text(), "export_unchanged": sha_tree(FRESH) == before,
                     "rollback": res.get("rollback"), "ok": res.get("status") == "FAIL" and w.status.text() == "FAIL"
                     and sha_tree(FRESH) == before and not view(w)["result_visible"]}
    R["14_runtime_failure"] = dict(r14, ok=all(v["ok"] for v in r14.values()))

    # 6 missing plate ---------------------------------------------------------------------
    nothing = os.path.join(SCRATCH, "nothing.project.json")
    json.dump({"name": "nothing", "plate_search": ["E:/nowhere/*{shot}*/*.####.exr"], "work_root": SCRATCH + "/work",
               "export_root": SCRATCH + "/export_{shot}_nothing"}, open(nothing, "w"))
    w = window(nothing, SQ_IN, shot="demo_gui_F")
    v = view(w)
    R["06_missing_plate"] = {"view": v, "ok": v["status"] == "BLOCKED" and v["plate_row"] and not v["build_enabled"]
                             and "No source plate found. Please select source plate." in v["messages"]}
    P["06"] = parity(w)

    # 7 multiple candidates -> pick -> stored -> reused -------------------------------------
    shot7 = sq  # the AMBIGUOUS project's plate rules match this shot's EXR and JPG plates
    shutil.rmtree(tp.workflow("work", "scratch_projtest", shot7), ignore_errors=True)  # no stored override yet
    w = window(AMB, SQ_IN, shot=shot7)
    v = view(w)
    cands = [w.plate_candidates.itemData(i) for i in range(w.plate_candidates.count()) if w.plate_candidates.itemData(i)]
    P["07"] = parity(w)
    exr = next((c for c in cands if c.endswith(".exr")), None)
    picked = {}
    if exr:
        w.plate_candidates.setCurrentIndex(cands.index(exr) + 1)  # triggers a re-Check with --plate
        settle(w)
        picked = view(w)
        P["07_picked"] = parity(w)
    w2 = window(AMB, SQ_IN, shot=shot7)
    reuse = view(w2)
    st = ((w2.last_check or {}).get("check") or {}).get("plate", {})
    R["07_multiple_candidates"] = {"first": v, "candidates": cands, "after_pick": picked, "new_window": reuse, "plate": st,
                                   "ok": v["status"] == "BLOCKED" and v["plate_row"] and len(cands) >= 2 and not v["build_enabled"]
                                   and "Multiple valid plate candidates found. Please select source plate." in v["messages"]
                                   and picked.get("build_enabled") and st.get("status") == "override" and reuse["build_enabled"]
                                   and reuse["plate_row"]}

    # 8 fps fallback ----------------------------------------------------------------------
    w = window(scratch_project("fps"), MOCK_C_IN, shot="CC_0030")
    v = view(w)
    R["08_fps_warning"] = {"view": v, "ok": v["status"] == "Ready (warnings)" and v["build_enabled"]
                           and "FPS source metadata unavailable. Using project setting: 25 fps." in v["messages"]}
    P["08"] = parity(w)

    # 9 / 10 unsupported ------------------------------------------------------------------
    for key, kind in (("09_fisheye", "fisheye"), ("10_multicams", "multicams")):
        w = window(scratch_project(kind), make_unsupported(kind), shot="CC_0030")
        v = view(w)
        R[key] = {"view": v, "ok": v["status"] == "BLOCKED" and not v["build_enabled"] and "Unsupported" in v["messages"]
                  and not os.path.exists(SCRATCH + f"/export_CC_0030_{kind}")}
        P[key[:2]] = parity(w)

    # 15 parity ---------------------------------------------------------------------------
    R["15_gui_cli_parity"] = {"checks": P, "ok": all(p["same"] for p in P.values())}

    R["detected_export_demo"] = {"value": detected_export, "ok": True}
    R["all_ok"] = all(v["ok"] for v in R.values() if isinstance(v, dict))
    json.dump(R, open(out, "w"), indent=1, default=str)
    for k, v in R.items():
        if isinstance(v, dict):
            print(f"{'OK ' if v['ok'] else 'BAD'} {k}")
    print("ALL OK" if R["all_ok"] else "FAILURES")
    shutil.rmtree(FRESH, ignore_errors=True)
    sys.exit(0 if R["all_ok"] else 1)


if __name__ == "__main__":
    main()

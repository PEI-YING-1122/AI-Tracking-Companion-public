"""v0.2.1 TEST2 fixes: Nuke Root name finalisation (regression case) and the supported Nuke
range / target selection (regression case).

    python tests/test_v021_test2.py <out.json>

ROOT     Nuke 17 style Root blocks: duplicate name (final + stage, the stage one after a multi-line
         knob that closes with a column-0 "}"), stage-only (several spellings), final-only
         (idempotent), other nodes' names untouched, the result opens in real Nuke with one Root
         name; stage paths in Read / STMap / Maya loader / metadata still FAIL stage_path_leak
VERSION  supported range 13.0-17.x: 12.2 only -> none, 12.2+17 -> 17, 13+17 -> 13, 14+16+17 -> 14,
         manual Nuke 12 refused, manual supported accepted, 18 refused, a saved Nuke 12 is not kept
SETUP    Workstation Setup saves only a supported Nuke; "No supported Nuke found"; short range note
GUI      Nuke Generator row = the configured version (fake 17.0v1) and the real Check result;
         Nuke 12 in site config -> Workstation Setup Required; CLI BLOCKED before any SyntaxError
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for sub in ("common", "nuke_package", "gui"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import test_paths as tp  # noqa: E402
import build_nuke_package as bnp  # noqa: E402
import companion_run as cr  # noqa: E402
import site_config  # noqa: E402
import workstation as ws  # noqa: E402

PY = sys.executable
NOT_RUN = {}   # test -> why (private fixture missing); never counted as a pass
try:   # private baseline shot (tests/local_test_config.json): only the two CLI / GUI Check cases need it
    BL = tp.baseline_shot()
    SQ = BL["shot"]
    SQ_IN = json.load(open(BL["shot_config"]))["vars"]["input_root"]
    NO_DATA = None
except (tp.TestDataNotConfigured, OSError, KeyError) as e:
    BL = SQ = SQ_IN = None
    NO_DATA = f"private baseline shot not configured ({e})"
R = {}
SUPPORTED_MSG = "Supported Nuke versions: 13.0\u201317.x."


def ok(name, cond, **info):
    R[name] = dict(info, ok=bool(cond))
    print(f"{'OK ' if cond else 'BAD'} {name}", flush=True)


# ------------------------------------------------------------------ ROOT
REST = """BackdropNode {
 inputs 0
 name BD_SOURCE
 label SOURCE
}
Read {
 inputs 0
 file "@STMAP@"
 raw true
 name READ_STMAP_UNDISTORT
}
Read {
 inputs 0
 file "@PLATE@"
 name READ_ORIGINAL_PLATE
}
STMap {
 inputs 2
 uv rgb
 name APPLY_REDISTORT
}
"""


def root_variant(kind, final, stage):
    head = "#! C:/Program Files/Nuke17.0v1/nuke-17.0.1.dll -nx\nversion 17.0 v1\n"
    luts = (" luts {linear {}\n  sRGB {curve L 0 1}\n  rec709 {}\n  \"esc \\{brace\" {}\n}\n")  # closes at column 0
    if kind == "duplicate":         # regression case: final added, stage kept after a multi-line knob
        root = f"Root {{\n inputs 0\n name {final}\n frame 1001\n{luts} name {stage}\n first_frame 1001\n}}\n"
    elif kind == "duplicate_plain":
        root = f"Root {{\n inputs 0\n name {final}\n name {stage}\n last_frame 1010\n}}\n"
    elif kind == "stage_only":
        root = f"Root {{\n inputs 0\n frame 1001\n{luts} name \"{stage}\"\n first_frame 1001\n}}\n"
    elif kind == "stage_only_tab":
        root = f"Root {{\n\tinputs 0\n\tname {{{stage}}}\n\tfirst_frame 1001\n}}\n"
    elif kind == "stage_only_crlf":
        root = f"Root {{\r\n inputs 0\r\n name {stage}\r\n first_frame 1001\r\n}}\r\n"
    elif kind == "final_only":
        root = f"Root {{\n inputs 0\n name {final}\n first_frame 1001\n}}\n"
    elif kind == "no_name":
        root = "Root {\n inputs 0\n first_frame 1001\n}\n"
    return head + root


def test_root():
    tmp = tempfile.mkdtemp(prefix="v021_test2_root_").replace("\\", "/")
    stage = tmp + "/work/sh/builds/20261013-000000-abcdef/stage"
    final = tmp + "/H/output/export/nuke/demo_sh0020_lens_setup.nk"
    stage_nk = stage + "/nuke/demo_sh0020_lens_setup.nk"
    good = REST.replace("@STMAP@", "H:/output/export/lens/demo_sh0020_undistort_stmap.exr") \
        .replace("@PLATE@", "H:/plates/demo_sh0020_%04d.png")
    res = {}
    for kind in ("duplicate", "duplicate_plain", "stage_only", "stage_only_tab", "stage_only_crlf", "final_only", "no_name"):
        p = f"{tmp}/{kind}.nk"
        open(p, "w", encoding="utf-8", newline="").write(root_variant(kind, final, stage_nk) + good)
        before = bnp.root_names(p)
        leak_before = cr.stage_leaks({"nuke_setup": p}, stage)
        bnp.finalize_root_name(p, final)
        once = open(p, encoding="utf-8").read()
        bnp.finalize_root_name(p, final)
        twice = open(p, encoding="utf-8").read()
        ln = once.split("\n")
        end = bnp._root_block(ln)[1]
        rest_kept = "\n".join(ln[end + 1:]) == good   # every node after the Root byte-identical
        res[kind] = {"before": before, "after": bnp.root_names(p), "leak_before": leak_before,
                     "leak_after": cr.stage_leaks({"nuke_setup": p}, stage), "idempotent": once == twice,
                     "rest_untouched": rest_kept, "node_names": [ln.strip() for ln in once.split("\n")
                                                                 if ln.strip().startswith("name ") and "BD_" in ln
                                                                 or "READ_" in ln and ln.strip().startswith("name")
                                                                 or "APPLY_" in ln]}
    good_case = lambda r: r["after"] == [final] and r["leak_after"] == [] and r["idempotent"] and r["rest_untouched"]  # noqa: E731
    ok("ROOT_A_duplicate_root_name", good_case(res["duplicate"]) and res["duplicate"]["before"] == [final, stage_nk]
       and res["duplicate"]["leak_before"] == ["nuke_setup"] and good_case(res["duplicate_plain"]),
       duplicate=res["duplicate"], duplicate_plain=res["duplicate_plain"])
    ok("ROOT_B_stage_only", all(good_case(res[k]) and res[k]["before"] == [stage_nk]
                                for k in ("stage_only", "stage_only_tab", "stage_only_crlf")),
       cases={k: res[k] for k in ("stage_only", "stage_only_tab", "stage_only_crlf")})
    ok("ROOT_C_final_only_not_duplicated", good_case(res["final_only"]) and res["final_only"]["before"] == [final]
       and good_case(res["no_name"]), final_only=res["final_only"], no_name=res["no_name"])
    ok("ROOT_other_node_names_untouched", all(r["rest_untouched"] for r in res.values())
       and res["duplicate"]["node_names"] == ["name BD_SOURCE", "name READ_STMAP_UNDISTORT", "name READ_ORIGINAL_PLATE",
                                              "name APPLY_REDISTORT"], names=res["duplicate"]["node_names"])

    # D: external stage dependencies keep failing (validator unchanged)
    def leak_case(stmap, plate):
        p = f"{tmp}/leak_{len(os.listdir(tmp))}.nk"
        open(p, "w", encoding="utf-8", newline="\n").write(
            root_variant("duplicate", final, stage_nk) + REST.replace("@STMAP@", stmap).replace("@PLATE@", plate))
        bnp.finalize_root_name(p, final)
        return cr.stage_leaks({"nuke_setup": p}, stage)
    loader = f"{tmp}/demo_sh0020_load_maya.py"
    open(loader, "w").write(f'METADATA_ABS = r"{stage}/metadata/demo_sh0020_metadata.json"\n')
    md = f"{tmp}/demo_sh0020_metadata.json"
    json.dump({"stmap": {"undistort": stage + "/lens/demo_sh0020_undistort_stmap.exr"}}, open(md, "w"))
    d = {"stmap": leak_case(stage + "/lens/demo_sh0020_undistort_stmap.exr", "H:/plates/demo_sh0020_%04d.png"),
         "plate": leak_case("H:/output/export/lens/x.exr", stage + "/plate/demo_sh0020_%04d.png"),
         "maya_loader": cr.stage_leaks({"maya_loader": loader}, stage),
         "metadata": cr.stage_leaks({"metadata": md}, stage)}
    src = open(os.path.join(ROOT, "companion_run.py"), encoding="utf-8").read()
    ok("ROOT_D_external_stage_dependency_fails", d == {"stmap": ["nuke_setup"], "plate": ["nuke_setup"],
                                                       "maya_loader": ["maya_loader"], "metadata": ["metadata"]}
       and 'raise bt.BuildStop(bt.FAIL, "stage_path_leak"' in src, leaks=d)

    # the finalised Nuke 17 style script still opens in real Nuke: exactly one Root name, nodes intact
    p = f"{tmp}/nuke_open.nk"
    open(p, "w", encoding="utf-8", newline="\n").write(root_variant("duplicate", final, stage_nk) + good)
    bnp.finalize_root_name(p, final)
    probe = f"{tmp}/probe.py"
    open(probe, "w").write(
        "import json, sys, nuke\n"
        "nuke.scriptOpen(sys.argv[1])\n"
        "json.dump({'nodes': sorted(n.name() for n in nuke.allNodes()), 'first': nuke.root()['first_frame'].value()},"
        " open(sys.argv[2], 'w'))\n")
    out = f"{tmp}/probe.json"
    r = subprocess.run([site_config.get("nuke"), "-t", probe, p, out], capture_output=True, text=True)
    got = json.load(open(out)) if os.path.exists(out) else {}
    ok("ROOT_finalised_script_opens_in_nuke", r.returncode == 0 and got.get("nodes") == sorted(
        ["BD_SOURCE", "READ_STMAP_UNDISTORT", "READ_ORIGINAL_PLATE", "APPLY_REDISTORT"]) and got.get("first") == 1001
       and bnp.root_names(p) == [final], nuke=site_config.get("nuke"), got=got, rc=r.returncode,
       err=(r.stdout + r.stderr)[-600:] if r.returncode else "")
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ VERSION / SETUP
def fake_nukes(base, versions):
    pf = os.path.join(base, "Program Files")
    paths = {}
    for v in versions:                         # e.g. "12.2v5" -> Nuke12.2v5/Nuke12.2.exe
        exe = os.path.join(pf, f"Nuke{v}", f"Nuke{v.split('v')[0]}.exe")
        os.makedirs(os.path.dirname(exe), exist_ok=True)
        open(exe, "wb").close()
        paths[v] = exe.replace("\\", "/")
    return pf, paths


def test_versions():
    tmp = tempfile.mkdtemp(prefix="v021_test2_nuke_")
    cases = {"12.2_only": (["12.2v5"], None), "12.2_17": (["12.2v5", "17.0v1"], "17.0v1"),
             "13_17": (["13.2v3", "17.0v1"], "13.2v3"), "14_16_17": (["14.0v5", "16.0v1", "17.0v1"], "14.0v5"),
             "12_18_only": (["12.2v5", "18.0v1"], None)}
    got = {}
    for name, (vers, want) in cases.items():
        pf, paths = fake_nukes(os.path.join(tmp, name), vers)
        found = ws.detect_nuke([pf])
        pick = ws.default_choice("nuke", found)
        got[name] = {"found": [(f["version"], f["supported"]) for f in found], "pick": ws.nuke_version(pick) if pick else None,
                     "want": want}
    ok("VERSION_auto_select", all(g["pick"] == g["want"] for g in got.values()), cases=got)
    ok("VERSION_12_only_unsupported", got["12.2_only"]["pick"] is None and got["12.2_only"]["found"] == [("12.2v5", False)])
    pf, paths = fake_nukes(os.path.join(tmp, "manual"), ["12.2v5", "13.0v1", "16.0v1", "17.0v1", "18.0v1"])
    msg12 = ws.problem("nuke", paths["12.2v5"])
    ok("VERSION_manual_nuke12_blocked", msg12 == f"Unsupported Nuke version 12.2v5. {SUPPORTED_MSG}", message=msg12)
    ok("VERSION_manual_supported_pass", all(ws.problem("nuke", paths[v]) is None for v in ("13.0v1", "16.0v1", "17.0v1"))
       and ws.problem("nuke", paths["18.0v1"]) == f"Unsupported Nuke version 18.0v1. {SUPPORTED_MSG}")
    found = ws.detect_nuke([pf])
    ok("VERSION_saved_nuke12_not_kept", ws.default_choice("nuke", found, current=paths["12.2v5"]) == paths["13.0v1"]
       and ws.default_choice("nuke", found, current=paths["17.0v1"]) == paths["17.0v1"])

    # Workstation Setup: save only with a supported Nuke
    base = os.path.join(tmp, "setup")
    pf, paths = fake_nukes(base, ["12.2v5", "17.0v1"])

    def exe(*p):
        q = os.path.join(base, *p)
        os.makedirs(os.path.dirname(q), exist_ok=True)
        open(q, "wb").close()
        return q.replace("\\", "/")
    others = {"hython": exe("Program Files", "Side Effects Software", "Houdini 20.0.547", "bin", "hython.exe"),
              "mayapy": exe("Program Files", "Autodesk", "Maya2024", "bin", "mayapy.exe"),
              "ffmpeg": exe("Tools", "ffmpeg", "bin", "ffmpeg.exe"), "ffprobe": exe("Tools", "ffmpeg", "bin", "ffprobe.exe")}
    ai = os.path.join(base, "home", "Downloads", "AI_Tracking", "colmap-camera-tracking-master")
    for f in ws.UPSTREAM_FILES:
        exe(ai, f)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import workstation_setup
    site = os.path.join(base, "configs", "site.json")
    w = workstation_setup.SetupWindow(site_path=site, program_roots=[pf], search_roots=[os.path.join(base, "home", "Downloads"),
                                                                                        os.path.join(base, "Tools")])
    auto = w.value("nuke")
    labels = [w.combos["nuke"].itemText(i) for i in range(w.combos["nuke"].count())]
    note = w.nuke_note.text()
    w.set_value("nuke", paths["12.2v5"])
    status12 = w.status["nuke"].text()
    saved12 = w.save()
    exists12 = os.path.exists(site)
    msg12 = w.message.text()
    w.set_value("nuke", paths["17.0v1"])
    saved17 = w.save()
    data = json.load(open(site)) if os.path.exists(site) else {}
    w.close()
    ok("SETUP_save_only_supported_nuke", auto == paths["17.0v1"] and not saved12 and not exists12
       and "Unsupported Nuke version 12.2v5" in status12 and SUPPORTED_MSG in msg12 and saved17
       and data.get("nuke") == paths["17.0v1"] and ws.status(site)["ok"] and ws.status(site)["nuke_version"] == "17.0v1",
       auto=auto, labels=labels, status12=status12, message12=msg12, saved=data.get("nuke"))
    ok("SETUP_range_note_short", note == "Nuke Target \u2014 Supported: Nuke 13\u201317"
       and any(lb.startswith("Nuke 12.2v5 (unsupported)") for lb in labels), note=note, labels=labels)
    only12 = os.path.join(tmp, "only12")
    pf12, _ = fake_nukes(only12, ["12.2v5"])
    w = workstation_setup.SetupWindow(site_path=os.path.join(only12, "site.json"), program_roots=[pf12], search_roots=[])
    st = w.status["nuke"].text()
    blocked = w.save() is False and not os.path.exists(os.path.join(only12, "site.json"))
    w.close()
    ok("SETUP_no_supported_nuke_blocked", w.value("nuke") == "" and st.startswith("✗ No supported Nuke found (12.2v5 installed)")
       and SUPPORTED_MSG in st and blocked, status=st)

    # GUI + CLI with the configured Nuke
    import companion_gui as G
    view = {}
    for key, path in (("nuke17", paths["17.0v1"]), ("nuke12", paths["12.2v5"])):
        os.environ["COMPANION_NUKE"] = path
        try:
            g = G.MainWindow(open_setup=lambda _p: None)
            view[key] = {"generator": g.fields["Nuke Generator"].text(), "setup_visible": g.setup_box.isVisibleTo(g),
                         "setup_text": g.setup_text.text()}
            g.close()
        finally:
            del os.environ["COMPANION_NUKE"]
    ok("GUI_nuke_generator_configured_version", view["nuke17"]["generator"] == "ⓘ 17.0v1" and not view["nuke17"]["setup_visible"]
       and view["nuke12"]["generator"] == "-" and view["nuke12"]["setup_visible"]
       and "Unsupported Nuke version 12.2v5" in view["nuke12"]["setup_text"], view=view)
    if NO_DATA:
        NOT_RUN["CLI_nuke12_blocked_before_build"] = NOT_RUN["GUI_nuke_generator_after_check"] = NO_DATA
        shutil.rmtree(tmp, ignore_errors=True)
        return
    e = dict(os.environ, COMPANION_NUKE=paths["12.2v5"], PYTHONDONTWRITEBYTECODE="1",
             COMPANION_WORK_ROOT=os.path.join(tmp, "work"))
    r = subprocess.run([PY, os.path.join(ROOT, "companion_run.py"), "--input", SQ_IN, "--shot", SQ, "--plate", BL["plate_exr"],
                        "--export", os.path.join(tmp, "export"), "--dry-run"], capture_output=True, text=True, env=e, cwd=ROOT)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("@@RESULT ")]
    res = json.load(open(line[-1].split(" ", 1)[1])) if line else {}
    msgs = " ".join(i["message"] for i in res.get("issues", []))
    ok("CLI_nuke12_blocked_before_build", r.returncode == 2 and [i["code"] for i in res.get("issues", [])] == ["workstation_setup"]
       and "Unsupported Nuke version 12.2v5" in msgs and "SyntaxError" not in r.stdout + r.stderr, rc=r.returncode, message=msgs)

    # real Check through the GUI: the row shows the Nuke the CLI reports (this machine's site.json)
    g = G.MainWindow(open_setup=lambda _p: None, extra_env={"COMPANION_WORK_ROOT": os.path.join(tmp, "work")})
    g.input.setText(SQ_IN)
    g.shot.setText(SQ)
    g.plate.setText(BL["plate_exr"])
    g.export.setText(os.path.join(tmp, "export").replace("\\", "/"))
    from PySide6.QtTest import QTest
    g.run_check()
    t0 = time.time()
    while (g.runner.busy() or g.mode is not None) and time.time() - t0 < 300:
        QTest.qWait(150)
    chk = (g.last_check or {}).get("check") or {}
    real = ws.status()["nuke_version"]
    ok("GUI_nuke_generator_after_check", g.fields["Nuke Generator"].text() == f"ⓘ {real}"
       and (chk.get("nuke_generator") or {}).get("version") == real and "Nuke Generator: " + real in g.log.toPlainText(),
       row=g.fields["Nuke Generator"].text(), check=chk.get("nuke_generator"))
    g.close()
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    out = sys.argv[1]
    test_root()
    test_versions()
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

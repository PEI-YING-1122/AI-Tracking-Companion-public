"""Project mode (auto detect + project config + overrides) tests.

    python tests/test_project_mode.py <out.json>

Uses the project configs under the test data root (baseline/ and workflow/projects/).
  A  demo_sh0010 full build from --project/--input/--shot  -> PASS, plate auto = EXR (rule 0),
     provenance complete, published lens / point data identical to the shot-config build
  B  one rule matches EXR + JPG                             -> BLOCKED plate_ambiguous (content check ran)
  C  --plate override                                       -> accepted, recorded in the shot config
  D  same shot again without --plate                        -> recorded override reused (status override)
  E  override pointing into the AI Tracking scene           -> BLOCKED plate_override_invalid
  F  rules that match nothing                               -> BLOCKED plate_none
  G  folder with two AI Tracking scenes                     -> BLOCKED scene (asks for --scene)
  H  mock C (JPG sequence, project fps 25)                  -> PASS, plate auto, fps_source project_config
  I  mock B (failed AI Tracking solve)                      -> BLOCKED unsupported
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
sys.path.insert(0, HERE)
import test_paths as tp  # noqa: E402

BASE = tp.baseline("demo_sh0010")
_SQ = json.load(open(BASE + "/demo_sh0010.json"))["vars"]   # the baseline shot's real project paths
SQ_IN = _SQ["input_root"]
SQ_EXPORT = _SQ["export_root"]
SQ_PLATE_DIR = _SQ["plate_dir"]
TEST_WORK = tp.workflow("work", "scratch_projtest")


def sha(p):
    """content identity; .npz compared by arrays (zip members carry a write time)"""
    if not os.path.exists(p):
        return None
    if p.endswith(".npz"):
        import numpy as np
        d = np.load(p)
        h = hashlib.sha256()
        for k in sorted(d.files):
            h.update(k.encode()); h.update(d[k].tobytes())
        return h.hexdigest()
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([PY, os.path.join(ROOT, "companion_run.py"), *args], capture_output=True, text=True, env=env)
    line = [l for l in r.stdout.splitlines() if "RESULT" in l]
    path = line[-1].split("-> ")[-1].strip() if line else None
    res = json.load(open(path)) if path and os.path.exists(path) else {}
    return r.returncode, res, path


def codes(res):
    return [i["code"] for i in res.get("issues", [])]


def main():
    out = sys.argv[1]
    if os.path.exists(TEST_WORK):
        shutil.rmtree(TEST_WORK)
    R = {}
    sq = "demo_sh0010"
    proj = BASE + "/projects/demo_project.project.json"
    amb = BASE + "/projects/demo_project.AMBIGUOUS.project.json"
    watch = [f"{SQ_EXPORT}/lens/{sq}_undistort_stmap.exr", f"{SQ_EXPORT}/lens/{sq}_redistort_stmap.exr",
             f"{SQ_EXPORT}/maya/{sq}_points.npz", f"{SQ_EXPORT}/nuke/{sq}_lens_setup.nk"]
    before = {p: sha(p) for p in watch}

    # A
    rc, res, path = run("--project", proj, "--input", SQ_IN, "--shot", sq, "--overwrite")
    cfg = json.load(open(os.path.join(BASE, "work", sq, f"{sq}.shot.json")))
    prov_p = os.path.join(os.path.dirname(path), "shot_config.json") if path else ""
    prov = json.load(open(prov_p)) if os.path.exists(prov_p) else {}
    need = ["shot_name", "input_root", "export_root", "resolved_plate", "resolved_flatten", "hip", "source_resolution",
            "source_frame_range", "tracking_frame_range", "fps", "fps_source", "camera_model", "production_canvas",
            "artist_overrides", "companion_version", "build_id"]
    after = {p: sha(p) for p in watch}
    R["A_demo_project_mode"] = {
        "rc": rc, "status": res.get("status"), "plate_status": cfg["auto_detect"]["plate"]["status"],
        "plate": cfg["inputs"]["source_plate"], "plate_rule": cfg["auto_detect"]["plate"]["rule"],
        "content_check": cfg["auto_detect"]["plate"].get("content_check"),
        "shot_name_suggestion": cfg["auto_detect"]["shot_name_suggestion"],
        "provenance_missing": [k for k in need if k not in prov], "fps_source": prov.get("fps_source"),
        "same_content_as_shot_config_build": {os.path.basename(p): before[p] == after[p] for p in watch},
        "ok": rc == 0 and cfg["auto_detect"]["plate"]["status"] == "auto" and cfg["inputs"]["source_plate"].endswith(".%04d.exr")
        and not [k for k in need if k not in prov] and all(before[p] == after[p] for p in watch[:3])}

    # B
    rc, res, _ = run("--project", amb, "--input", SQ_IN, "--shot", sq, "--dry-run")
    det = next((i["detail"] for i in res.get("issues", []) if i["code"] == "plate_ambiguous"), [])
    R["B_ambiguous"] = {"rc": rc, "status": res.get("status"), "issues": codes(res),
                        "candidates": [{k: c.get(k) for k in ("pattern", "ok", "ncc")} for c in det],
                        "ok": rc == 2 and "plate_ambiguous" in codes(res) and all("ncc" in c for c in det)}
    # C
    jpg = os.path.dirname(SQ_PLATE_DIR).replace("\\", "/") + "/jpg/plate_demo_sh0010.####.jpg"
    rc, res, _ = run("--project", amb, "--input", SQ_IN, "--shot", sq, "--plate", jpg, "--dry-run")
    cfg = json.load(open(os.path.join(TEST_WORK, sq, f"{sq}.shot.json")))
    R["C_override"] = {"rc": rc, "status": res.get("status"), "recorded_override": cfg["overrides"].get("source_plate"),
                       "plate_status": cfg["auto_detect"]["plate"]["status"],
                       "ok": rc == 0 and cfg["overrides"].get("source_plate") == jpg and cfg["auto_detect"]["plate"]["status"] == "override"}
    # D
    rc, res, _ = run("--project", amb, "--input", SQ_IN, "--shot", sq, "--dry-run")
    cfg = json.load(open(os.path.join(TEST_WORK, sq, f"{sq}.shot.json")))
    R["D_override_reused"] = {"rc": rc, "plate_status": cfg["auto_detect"]["plate"]["status"],
                              "plate": cfg["inputs"]["source_plate"],
                              "ok": rc == 0 and cfg["auto_detect"]["plate"]["status"] == "override"
                              and cfg["inputs"]["source_plate"].endswith(".%04d.jpg")}
    # E
    rc, res, _ = run("--project", amb, "--input", SQ_IN, "--shot", "demo_sh0010_E", "--plate", SQ_IN + "/jpg/images", "--dry-run")
    R["E_invalid_override"] = {"rc": rc, "issues": codes(res), "ok": rc == 2 and "plate_override_invalid" in codes(res)}
    # F
    nothing = os.path.join(TEST_WORK, "nothing.project.json")
    os.makedirs(TEST_WORK, exist_ok=True)
    json.dump({"plate_search": ["E:/nowhere/*{shot}*/*.####.exr"], "work_root": TEST_WORK}, open(nothing, "w"))
    rc, res, _ = run("--project", nothing, "--input", SQ_IN, "--shot", "demo_sh0010_F", "--dry-run")
    R["F_no_candidate"] = {"rc": rc, "issues": codes(res), "ok": rc == 2 and "plate_none" in codes(res)}
    # G
    multi = os.path.join(TEST_WORK, "multi_scene")
    for s in ("shotA", "shotB"):
        os.makedirs(os.path.join(multi, s, "sparse", "0"), exist_ok=True)
        open(os.path.join(multi, s, "sparse", "0", "cameras.bin"), "wb").close()
        open(os.path.join(multi, f"{s}_transforms.json"), "w").write("{}")
    rc, res, _ = run("--project", nothing, "--input", multi, "--shot", "multi_G", "--dry-run")
    R["G_two_scenes"] = {"rc": rc, "issues": codes(res), "detail": next((i["detail"] for i in res.get("issues", []) if i["code"] == "scene"), None),
                         "ok": rc == 2 and "scene" in codes(res)}
    # H
    rc, res, path = run("--project", tp.workflow("projects", "mock_C.project.json"),
                        "--input", tp.workflow("mock_project_C", "io", "tracking"), "--shot", "CC_0030", "--overwrite")
    prov_p = os.path.join(os.path.dirname(path), "shot_config.json") if path else ""
    prov = json.load(open(prov_p)) if os.path.exists(prov_p) else {}
    R["H_mock_C"] = {"rc": rc, "status": res.get("status"), "plate": prov.get("resolved_plate"), "fps": prov.get("fps"),
                     "fps_source": prov.get("fps_source"), "warnings": [i["code"] for i in res.get("issues", []) if i["level"] == "WARNING"],
                     "ok": rc == 0 and prov.get("fps_source") == "project_config" and (prov.get("resolved_plate") or "").endswith(".%04d.jpg")}
    # I
    rc, res, _ = run("--project", tp.workflow("projects", "mock_B.project.json"),
                     "--input", tp.workflow("mock_project_B", "TRACK", "ai_out"), "--shot", "RB_0020", "--overwrite")
    R["I_mock_B_failed_solve"] = {"rc": rc, "issues": codes(res), "ok": rc == 2 and "unsupported" in codes(res)}

    R["all_ok"] = all(v["ok"] for v in R.values() if isinstance(v, dict))
    json.dump(R, open(out, "w"), indent=1, default=str)
    for k, v in R.items():
        if isinstance(v, dict):
            print(f"{'OK ' if v['ok'] else 'BAD'} {k}: rc={v['rc']} {v.get('status', '')} {v.get('issues', '')}")
    print("ALL OK" if R["all_ok"] else "FAILURES")
    sys.exit(0 if R["all_ok"] else 1)


if __name__ == "__main__":
    main()

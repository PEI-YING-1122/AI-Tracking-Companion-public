"""Partial build regression (--outputs), transactional rules unchanged.

    python tests/test_partial_build.py <shot_config.json> <out.json>

Scenarios on one shot (each checked with sha256 snapshots of the export):
  0 full build (setup)          every module from build b0
  1 Maya only                   publishes maya + metadata; lens / nuke untouched (still b0)
  2 Lens only                   publishes lens + metadata; maya / nuke untouched
  3 Nuke only                   Lens added automatically (WARNING); maya untouched
  4 Maya + Nuke                 maya + lens + nuke + metadata
  5 Full                        everything
  6 different published solution (fingerprint tampered) + Maya only -> BLOCKED, export untouched
  7 Maya only into a fresh export -> maya + metadata only; no lens / nuke appear
Always: metadata exists; metadata.modules says which build produced each module that
is present; every module is all-new or all-old (never mixed); nothing unselected is published.
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "common"))
import path_resolver  # noqa: E402

PY = sys.executable
MODULE_KEYS = {"lens": ("lens_undistort", "lens_redistort"),
               "maya": ("maya_loader", "maya_cam_abc", "maya_cam_fbx", "maya_sidecar", "maya_points_npz"),
               "nuke": ("nuke_setup",), "metadata": ("metadata",)}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def state(R):
    return {k: sha(R["planned"][k]) for keys in MODULE_KEYS.values() for k in keys}


def run(cfg, *args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([PY, os.path.join(ROOT, "companion_run.py"), cfg, *args], capture_output=True, text=True, env=env)
    line = [l for l in r.stdout.splitlines() if l.startswith("@@RESULT ")]
    p = line[-1].split(" ", 1)[1].strip() if line else None
    return r.returncode, (json.load(open(p)) if p and os.path.exists(p) else {})


def published_keys(R, res):
    inv = {v: k for k, v in R["planned"].items()}
    return sorted(inv.get(p["path"].replace("\\", "/"), p["path"]) for p in res.get("published", []))


def modules(R):
    p = R["planned"]["metadata"]
    return json.load(open(p)).get("modules", {}) if os.path.exists(p) else {}


def expect_keys(mods):
    return sorted(k for m in mods for k in MODULE_KEYS[m])


def check(R, before, after, res, selected, prev_mods):
    """selected: modules this build must publish (metadata always)."""
    bid = res.get("build_id")
    sel = set(selected) | {"metadata"}
    mods = modules(R)
    unchanged_ok = all(after[k] == before[k] for m in MODULE_KEYS if m not in sel for k in MODULE_KEYS[m])
    pub_ok = published_keys(R, res) == expect_keys(sel)
    mod_ok = all(mods.get(m, {}).get("build_id") == bid for m in sel - {"metadata"}) and \
        all(mods.get(m, {}).get("build_id") == prev_mods.get(m, {}).get("build_id")
            for m in ("lens", "maya", "nuke") if m not in sel and m in prev_mods) and \
        all(m not in mods for m in ("lens", "maya", "nuke") if m not in sel and m not in prev_mods)
    present_ok = all((after[k] is not None) == (m in sel or m in prev_mods) for m in MODULE_KEYS for k in MODULE_KEYS[m])
    return {"rc": None, "status": res.get("status"), "published": published_keys(R, res),
            "unselected_untouched": unchanged_ok, "published_exactly_selected": pub_ok,
            "modules_provenance_ok": mod_ok, "files_present_match_modules": present_ok,
            "metadata_exists": after["metadata"] is not None, "modules": {m: v.get("build_id") for m, v in mods.items()},
            "ok": res.get("status") in ("PASS", "WARNING") and unchanged_ok and pub_ok and mod_ok and present_ok}


def main():
    cfg, out = sys.argv[1:3]
    R = path_resolver.resolve(cfg, overwrite=True)
    res_all = {}
    rc, res = run(cfg, "--overwrite")
    assert rc == 0, res.get("issues")
    scenarios = [("1_maya_only", ["maya"], ["maya"]), ("2_lens_only", ["lens"], ["lens"]),
                 ("3_nuke_only", ["nuke"], ["nuke", "lens"]), ("4_maya_nuke", ["maya", "nuke"], ["maya", "nuke", "lens"]),
                 ("5_full", ["lens", "maya", "nuke"], ["lens", "maya", "nuke"])]
    for name, outs, expect in scenarios:
        before, prev = state(R), modules(R)
        rc, res = run(cfg, "--overwrite", "--outputs", *outs)
        r = check(R, before, state(R), res, expect, prev)
        r["rc"] = rc
        if name == "3_nuke_only":
            r["lens_auto_warning"] = any(i["code"] == "dependency" for i in res.get("issues", []))
            r["ok"] = r["ok"] and r["lens_auto_warning"]
        res_all[name] = r

    # 6 tampered fingerprint -> BLOCKED
    md_path = R["planned"]["metadata"]
    md = json.load(open(md_path))
    saved = open(md_path, "rb").read()
    md["fingerprint"] = "0000000000000000"
    json.dump(md, open(md_path, "w"), indent=1)
    before = state(R)
    rc, res = run(cfg, "--overwrite", "--outputs", "maya")
    after = state(R)
    open(md_path, "wb").write(saved)
    res_all["6_fingerprint_mismatch"] = {"rc": rc, "status": res.get("status"),
                                         "issues": [i["code"] for i in res.get("issues", [])],
                                         "export_unchanged": before == after,
                                         "ok": rc == 2 and "fingerprint" in [i["code"] for i in res.get("issues", [])] and before == after}

    # 7 Maya only into a fresh export
    c = json.load(open(cfg))
    c2 = copy.deepcopy(c)
    c2["outputs"]["export_root"] = c["outputs"]["export_root"].rstrip("/") + "_partial_fresh"
    fresh_cfg = os.path.join(os.path.dirname(os.path.abspath(cfg)), "_partial_fresh.json")
    json.dump(c2, open(fresh_cfg, "w"), indent=1)
    R2 = path_resolver.resolve(fresh_cfg, overwrite=True)
    shutil.rmtree(R2["outputs"]["export_root"], ignore_errors=True)
    before = state(R2)
    rc, res = run(fresh_cfg, "--outputs", "maya")
    r = check(R2, before, state(R2), res, ["maya"], {})
    r["rc"] = rc
    r["lens_nuke_absent"] = all(state(R2)[k] is None for m in ("lens", "nuke") for k in MODULE_KEYS[m])
    r["ok"] = r["ok"] and r["lens_nuke_absent"]
    res_all["7_fresh_maya_only"] = r
    shutil.rmtree(R2["outputs"]["export_root"], ignore_errors=True)
    os.remove(fresh_cfg)

    res_all["all_ok"] = all(v["ok"] for v in res_all.values() if isinstance(v, dict))
    json.dump(res_all, open(out, "w"), indent=1, default=str)
    for k, v in res_all.items():
        if isinstance(v, dict):
            print(f"{'OK ' if v['ok'] else 'BAD'} {k}: rc={v['rc']} {v.get('status')} published={v.get('published', '')}")
    print("ALL OK" if res_all["all_ok"] else "FAILURES")
    sys.exit(0 if res_all["all_ok"] else 1)


if __name__ == "__main__":
    main()

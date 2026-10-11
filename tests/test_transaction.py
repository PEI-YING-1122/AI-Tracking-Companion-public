"""Transactional builder tests: stage -> validate -> publish, cancel, backup, rollback.

    python tests/test_transaction.py <shot_config.json> <blocked_config.json> <out.json>

Runs companion_run.py as a subprocess for each scenario and checks the export with
sha256 state snapshots (never trusting the tool's own report):

  1 cancel          delivery exists, no --overwrite         -> CANCELLED (5), export untouched
  2 overwrite       --overwrite                             -> PASS (0), backup of the old set,
                                                               every published file from this build
  3 validate fault  injected validation failure             -> FAIL (1), export untouched
  4 publish fault   failure after 4 files are published     -> FAIL (1), rollback restores the old set exactly
  5 fresh export    export root does not exist              -> PASS (0) without --overwrite
  6 blocked         unsupported / failed solve              -> BLOCKED (2), nothing built or published
"""
import copy
import glob
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


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def export_state(R):
    files = [p for k, p in R["planned"].items() if k != "manifest"]
    return {p: (sha(p) if os.path.exists(p) else None) for p in files}


def run(cfg, *args, env=None):
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    e.pop("COMPANION_FAULT_VALIDATE", None)
    e.pop("COMPANION_FAULT_PUBLISH_AFTER", None)
    e.update(env or {})
    r = subprocess.run([PY, os.path.join(ROOT, "companion_run.py"), cfg, *args], capture_output=True, text=True, env=e)
    line = [l for l in r.stdout.splitlines() if "RESULT" in l]
    res_path = line[-1].split("-> ")[-1].strip() if line else None
    res = json.load(open(res_path)) if res_path and os.path.exists(res_path) else {}
    return r.returncode, res


def metadata_build_id(R):
    p = R["planned"]["metadata"]
    return json.load(open(p)).get("build_id") if os.path.exists(p) else None


def main():
    cfg, blocked_cfg, out = sys.argv[1:4]
    R = path_resolver.resolve(cfg, overwrite=True)
    res = {}

    # make sure a delivery exists to start from
    rc, r = run(cfg, "--overwrite")
    assert rc == 0, f"setup build failed: {r.get('issues')}"
    base = export_state(R)

    rc, r = run(cfg)
    res["1_cancel"] = {"rc": rc, "status": r.get("status"), "export_unchanged": export_state(R) == base,
                       "built_nothing": not os.path.exists(os.path.join(r.get("build_dir", "") or "", "stage")),
                       "ok": rc == 5 and r.get("status") == "CANCELLED" and export_state(R) == base}

    rc, r = run(cfg, "--overwrite")
    new = export_state(R)
    bdir = os.path.dirname(r.get("published", [{}])[0].get("path", "")) if r.get("published") else ""
    build_dir = glob.glob(os.path.join(R["outputs"]["work_dir"], "builds", r.get("build_id", "-"), ""))
    backup = os.path.join(build_dir[0], "backup") if build_dir else ""
    backed = [os.path.join(b, f) for b, _, fs in os.walk(backup) for f in fs] if backup else []
    backup_matches_old = sorted(sha(f) for f in backed) == sorted(v for v in base.values() if v)
    res["2_overwrite"] = {"rc": rc, "status": r.get("status"), "published": len(r.get("published", [])),
                          "backup_files": len(backed), "backup_equals_previous_delivery": backup_matches_old,
                          "metadata_build_id_is_this_build": metadata_build_id(R) == r.get("build_id"),
                          "stage_removed_after_publish": build_dir and not os.path.exists(os.path.join(build_dir[0], "stage")),
                          "ok": rc == 0 and backup_matches_old and metadata_build_id(R) == r.get("build_id")}
    base = new

    rc, r = run(cfg, "--overwrite", env={"COMPANION_FAULT_VALIDATE": "1"})
    res["3_validate_fault"] = {"rc": rc, "status": r.get("status"), "issues": [i["code"] for i in r.get("issues", [])],
                               "published": len(r.get("published", [])), "export_unchanged": export_state(R) == base,
                               "ok": rc == 1 and export_state(R) == base and not r.get("published")}

    rc, r = run(cfg, "--overwrite", env={"COMPANION_FAULT_PUBLISH_AFTER": "4"})
    rb = r.get("rollback", {})
    res["4_publish_fault"] = {"rc": rc, "status": r.get("status"), "rollback": rb,
                              "export_identical_to_before": export_state(R) == base,
                              "no_tmp_files": not glob.glob(os.path.join(R["outputs"]["export_root"], "*", "*.companion_tmp")),
                              "ok": rc == 1 and rb.get("restored_exactly") is True and export_state(R) == base
                              and rb.get("files_touched") == 4}

    # 5 fresh export root (does not exist yet) -> direct publish
    c = json.load(open(cfg))
    fresh_cfg = os.path.join(os.path.dirname(os.path.abspath(cfg)), "_tx_fresh_export.json")
    c2 = copy.deepcopy(c)
    c2["outputs"]["export_root"] = c["outputs"]["export_root"].rstrip("/") + "_tx_fresh"
    json.dump(c2, open(fresh_cfg, "w"), indent=1)
    R2 = path_resolver.resolve(fresh_cfg, overwrite=True)
    if os.path.exists(R2["outputs"]["export_root"]):
        shutil.rmtree(R2["outputs"]["export_root"])
    rc, r = run(fresh_cfg)
    res["5_fresh_export"] = {"rc": rc, "status": r.get("status"), "published": len(r.get("published", [])),
                             "all_present": all(v for v in export_state(R2).values()),
                             "ok": rc == 0 and all(v for v in export_state(R2).values())}
    shutil.rmtree(R2["outputs"]["export_root"], ignore_errors=True)
    os.remove(fresh_cfg)

    # 6 blocked
    Rb = path_resolver.resolve(blocked_cfg, overwrite=True)
    before_b = export_state(Rb)
    rc, r = run(blocked_cfg, "--overwrite")
    res["6_blocked"] = {"rc": rc, "status": r.get("status"), "issues": [i["code"] for i in r.get("issues", [])],
                        "export_unchanged": export_state(Rb) == before_b,
                        "ok": rc == 2 and export_state(Rb) == before_b and not r.get("published")}

    res["all_ok"] = all(v["ok"] for v in res.values() if isinstance(v, dict))
    json.dump(res, open(out, "w"), indent=1, default=str)
    for k, v in res.items():
        if isinstance(v, dict):
            print(f"{'OK ' if v['ok'] else 'BAD'} {k}: rc={v['rc']} {v.get('status')}")
    print("ALL OK" if res["all_ok"] else "FAILURES")
    sys.exit(0 if res["all_ok"] else 1)


if __name__ == "__main__":
    main()

"""Path resolver guard tests, shot config schema v2 (no Houdini/Maya/Nuke).

    python tests/test_path_resolver.py <valid_shot_config.json> <work_dir> <out.json>

Takes a valid config, mutates one thing at a time, and checks that the resolver
refuses what it must refuse -- before anything is written.
"""
import copy
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "common"))
import path_resolver as pr  # noqa: E402
import site_config  # noqa: E402


def attempt(cfg, work, name, overwrite=False):
    p = os.path.join(work, f"{name}.json")
    json.dump(cfg, open(p, "w"), indent=1)
    try:
        r = pr.resolve(p, protected_roots=[os.path.dirname(site_config.get("upstream_repo"))], overwrite=overwrite)
        return {"accepted": True, "shot": r["shot"], "outputs": r["outputs"], "planned": r["planned"]}
    except pr.ConfigError as e:
        return {"accepted": False, "error": str(e).splitlines()[0][:200]}


def main():
    base_cfg, work, out = sys.argv[1:4]
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)
    work = os.path.abspath(work).replace("\\", "/")
    base = json.load(open(base_cfg))
    base_dir = os.path.dirname(os.path.abspath(base_cfg)).replace("\\", "/")
    base["vars"] = dict(base.get("vars", {}))
    for k, v in list(base["vars"].items()):  # keep relative vars valid from the test folder
        v = base["vars"][k] = str(v).replace("{config_dir}", base_dir)
        if not os.path.isabs(str(v)):
            base["vars"][k] = os.path.normpath(os.path.join(base_dir, str(v))).replace("\\", "/")
    fresh = f"{work}/fresh_export"
    cases = {}

    def mutate(name, fn, expect_accept, overwrite=False):
        c = copy.deepcopy(base)
        c["outputs"] = {"export_root": fresh, "work_dir": f"{work}/fresh_work"}
        c["options"] = {"flatten_mode": "none"}
        fn(c)
        r = attempt(c, work, name, overwrite)
        r["expected_accept"] = expect_accept
        r["ok"] = r["accepted"] == expect_accept
        cases[name] = r

    mutate("valid", lambda c: None, True)
    mutate("existing_outputs_without_overwrite", lambda c: c["outputs"].__setitem__("export_root", base_existing), False) \
        if (base_existing := _existing_export(base, base_cfg)) else None
    mutate("output_inside_ai_tracking_scene", lambda c: c["outputs"].__setitem__("lens_dir", "{ai_tracking_scene_dir}/lens"), False)
    mutate("output_inside_ai_flatten", lambda c: c["outputs"].__setitem__("maya_dir", "{ai_tracking_scene_dir}/undistort/images_undistorted/x"), False)
    mutate("output_inside_upstream_install",
           lambda c: c["outputs"].__setitem__("nuke_dir", site_config.get("upstream_repo").replace("\\", "/") + "/x"), False)
    mutate("output_inside_source_plate",
           lambda c: c["outputs"].__setitem__("metadata_dir", os.path.dirname(c["inputs"]["source_plate"]) + "/meta"), False)
    mutate("work_dir_inside_export", lambda c: c["outputs"].__setitem__("work_dir", fresh + "/work"), False)
    mutate("missing_export_root", lambda c: c["outputs"].pop("export_root"), False)
    mutate("missing_shot_name", lambda c: c.pop("shot"), False)
    mutate("unsafe_shot_name", lambda c: c.__setitem__("shot", "SH 010/../x"), False)
    mutate("missing_input", lambda c: c["inputs"].__setitem__("ai_tracking_scene_dir", work + "/nope"), False)
    mutate("unknown_token", lambda c: c["outputs"].__setitem__("maya_dir", "{nowhere}/maya"), False)
    mutate("bad_flatten_mode", lambda c: c["options"].__setitem__("flatten_mode", "copy"), False)
    mutate("render_without_pattern", lambda c: c["options"].__setitem__("flatten_mode", "render"), False)
    mutate("render_flatten_not_pattern", lambda c: (c["options"].__setitem__("flatten_mode", "render"),
                                                    c["outputs"].__setitem__("production_flatten", fresh + "/flat.exr")), False)
    mutate("relative_output_path", lambda c: c["outputs"].__setitem__("lens_dir", "rel_lens"), True)
    mutate("default_layout_and_names", lambda c: None, True)

    rel = cases["relative_output_path"]
    rel["resolved_against_config_dir"] = rel.get("outputs", {}).get("lens_dir", "").lower() == f"{work}/rel_lens".lower()
    d = cases["default_layout_and_names"]
    shot = d.get("shot", "")
    d["layout_ok"] = d.get("accepted") and all(d["outputs"][k] == f"{fresh}/{sub}" for k, sub in
                                                (("lens_dir", "lens"), ("maya_dir", "maya"), ("metadata_dir", "metadata"), ("nuke_dir", "nuke")))
    d["names_use_shot_only"] = d.get("accepted") and all(os.path.basename(p).startswith(shot + "_") for p in d["planned"].values())

    res = {"cases": cases, "all_ok": all(v["ok"] for v in cases.values()) and rel["resolved_against_config_dir"]
           and d["layout_ok"] and d["names_use_shot_only"]}
    json.dump(res, open(out, "w"), indent=1)
    for k, v in cases.items():
        print(f"{'OK ' if v['ok'] else 'BAD'} {k}: accepted={v['accepted']} {v.get('error', '')[:110]}")
    print("ALL OK" if res["all_ok"] else "FAILURES")


def _existing_export(base, base_cfg):
    """export_root of the base config if it already holds outputs (overwrite guard test)."""
    try:
        r = pr.resolve(base_cfg, overwrite=True)
        return r["outputs"]["export_root"] if any(os.path.exists(p) for k, p in r["planned"].items() if k != "manifest") else None
    except pr.ConfigError:
        return None


if __name__ == "__main__":
    main()

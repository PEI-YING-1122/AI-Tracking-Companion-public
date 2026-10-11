"""Project config (project-specific rules only; machine paths live in configs/site.json).

{
 "schema": "ai_tracking_companion.project/1",
 "name": "...",
 "vars": {"project_root": "X:/proj"},
 "fps": 24,                                   # fallback when the source has none
 "shot_name_regex": "(sq\\d{4}_sh\\d{4})",    # suggestion only; the Artist confirms the name
 "plate_search": ["{project_root}/plates/*{shot}*/exr/*.####.exr", ...],   # ordered by priority
 "export_root": "{ai_tracking_output}/export",
 "work_root": "",                             # empty -> <Companion>/work
 "flatten_mode": "reference_ai_tracking",
 "outputs_default": {"lens": true, "maya": true, "nuke": true}
}
"""
import json
import os
import re

COMPANION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = {
    "name": "", "vars": {}, "fps": None, "shot_name_regex": "", "plate_search": [],
    "export_root": "{ai_tracking_output}/export", "work_root": "", "flatten_mode": "reference_ai_tracking",
    "outputs_default": {"lens": True, "maya": True, "nuke": True},
}
TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ProjectConfigError(Exception):
    pass


def load(path):
    if not path:
        cfg = dict(DEFAULTS)
        cfg["_path"] = None
        return cfg
    try:
        raw = json.load(open(path))
    except (OSError, ValueError) as e:
        raise ProjectConfigError(f"cannot read project config {path}: {e}")
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
    cfg["_path"] = os.path.abspath(path)
    if not isinstance(cfg["plate_search"], list):
        raise ProjectConfigError("plate_search must be a list of patterns")
    return cfg


def substitute(value, tokens, where="project config"):
    for _ in range(10):
        new = TOKEN.sub(lambda m: str(tokens[m.group(1)]) if m.group(1) in tokens else m.group(0), value)
        if new == value:
            break
        value = new
    left = TOKEN.findall(value)
    if left:
        raise ProjectConfigError(f"{where}: unknown token(s) {left} in '{value}'")
    return value


def project_dir(cfg):
    return os.path.dirname(cfg["_path"]).replace("\\", "/") if cfg.get("_path") else COMPANION_ROOT.replace("\\", "/")


def work_root(cfg):
    """{project_dir} and vars allowed; relative paths are relative to the project file."""
    w = os.path.expandvars(cfg.get("work_root") or "")
    if not w:
        return os.path.join(COMPANION_ROOT, "work")
    tokens = dict(cfg.get("vars") or {})
    tokens["project_dir"] = project_dir(cfg)
    w = substitute(w, tokens, "work_root")
    return os.path.normpath(w if os.path.isabs(w) else os.path.join(project_dir(cfg), w))

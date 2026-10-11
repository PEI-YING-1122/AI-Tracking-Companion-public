"""Workstation tool locations (Houdini, Maya, Nuke, ffmpeg, upstream repo).

Read from configs/site.json next to the Companion (not tracked by git; see
configs/site.example.json), or the file named by
COMPANION_SITE_CONFIG; each key can be overridden by env COMPANION_<KEY>.
Nothing here knows about projects or shots -- those come from the shot config
(common/path_resolver.py).
"""
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        path = os.environ.get("COMPANION_SITE_CONFIG")
        if not path:  # configs/ (repo layout); config/ kept as a fallback for older checkouts
            path = next((p for p in (os.path.join(_ROOT, "configs", "site.json"), os.path.join(_ROOT, "config", "site.json"))
                         if os.path.exists(p)), os.path.join(_ROOT, "configs", "site.json"))
        with open(path) as f:
            _CACHE = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        _CACHE["_path"] = path
    return _CACHE


def get(key, must_exist=True):
    val = os.environ.get(f"COMPANION_{key.upper()}") or _load().get(key)
    if not val:
        raise KeyError(f"site config has no '{key}' ({_load()['_path']})")
    val = os.path.normpath(val)
    if must_exist and not os.path.exists(val):
        raise FileNotFoundError(f"site config '{key}' not found: {val}")
    return val


def companion_root():
    return _ROOT

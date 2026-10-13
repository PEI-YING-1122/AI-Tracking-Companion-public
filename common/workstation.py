"""Workstation configuration: tool detection, validation and configs/site.json generation.

Used by the Workstation Setup window (gui/workstation_setup.py, Configure_Companion.bat), the
main GUI's first-run check and the CLI preflight.  Detection only looks at common install
roots / known locations, never the whole disk:

    Houdini   <Program Files>/Side Effects Software/Houdini*/bin/hython.exe
    Maya      <Program Files>/Autodesk/Maya*/bin/mayapy.exe
    Nuke      <Program Files>/Nuke*/Nuke<major>.<minor>.exe
    FFmpeg    C:/ffmpeg[/*]/bin, C:/Tools/ffmpeg*/bin, PATH, next to the AI Tracking install,
              COMPANION_SEARCH_ROOTS
    AI Tracking  folder with run_autotracker.py, depth-limited under Downloads / Desktop /
              Documents, <drive>:/Tools, <drive>:/*AI_Tracking*, COMPANION_SEARCH_ROOTS

Nuke target = the LOWEST SUPPORTED detected version by default (a script written by an older
Nuke opens in a newer one, not the other way round); the Artist / TD can choose another
supported one.  Supported Nuke range (Companion runtime / .nk writer): 13.0 - 17.x.  Nuke 12 and
older embed a Python the writer cannot run (SyntaxError) and are refused before saving.
"""
import glob
import json
import os
import re
import shutil
import string
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ("hython", "mayapy", "nuke", "ffmpeg", "ffprobe", "upstream_repo")
NAMES = {"hython": "Houdini", "mayapy": "Maya", "nuke": "Nuke", "ffmpeg": "FFmpeg", "ffprobe": "FFprobe",
         "upstream_repo": "AI Tracking"}
EXE_RE = {"hython": r"hython(\.exe)?", "mayapy": r"mayapy(\.exe)?", "nuke": r"nuke\d+\.\d+(\.exe)?",
          "ffmpeg": r"ffmpeg(\.exe)?", "ffprobe": r"ffprobe(\.exe)?"}
NUKE_SUPPORTED = (13, 17)   # major versions, inclusive (runtime / writer range; not every major manually QC'd)
NUKE_SUPPORTED_TEXT = "13.0–17.x"
UPSTREAM_FILES = ("run_autotracker.py", "undistortionNerfstudioColmap.py")
COMMENT = ("Written by Workstation Setup (Configure_Companion.bat). Workstation-level tool locations, not "
           "project or shot paths. TD: may be edited by hand (see configs/site.example.json); override any "
           "key with env COMPANION_<KEY>.")
SKIP_DIRS = {"windows", "$recycle.bin", "system volume information", "node_modules", "programdata", "appdata",
             "__pycache__", ".git", ".venv"}
WALK_LIMIT = 20000   # directories visited per search root (keeps a scan to seconds)


# ------------------------------------------------------------------ site.json location / status
def site_path():
    p = os.environ.get("COMPANION_SITE_CONFIG")
    if p:
        return p
    return next((q for q in (os.path.join(ROOT, "configs", "site.json"), os.path.join(ROOT, "config", "site.json"))
                 if os.path.exists(q)), os.path.join(ROOT, "configs", "site.json"))


def version_key(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or ""))


def nuke_version(path):
    """'C:/Program Files/Nuke16.0v1/Nuke16.0.exe' -> '16.0v1' (folder), else '16.0' (exe name)"""
    p = (path or "").replace("\\", "/")
    m = re.search(r"Nuke(\d+\.\d+v\d+)", os.path.basename(os.path.dirname(p)), re.I) \
        or re.search(r"Nuke(\d+\.\d+)", os.path.basename(p), re.I)
    return m.group(1) if m else None


def nuke_major(path):
    """major version from the executable name (Nuke12.2.exe -> 12), else from its folder"""
    p = (path or "").replace("\\", "/")
    m = re.search(r"Nuke(\d+)\.\d+", os.path.basename(p), re.I) or \
        re.search(r"Nuke(\d+)\.\d+", os.path.basename(os.path.dirname(p)), re.I)
    return int(m.group(1)) if m else None


def nuke_supported(path):
    major = nuke_major(path)
    return major is not None and NUKE_SUPPORTED[0] <= major <= NUKE_SUPPORTED[1]


def unsupported_nuke_message(path):
    return (f"Unsupported Nuke version{' ' + nuke_version(path) if nuke_version(path) else ''}. "
            f"Supported Nuke versions: {NUKE_SUPPORTED_TEXT}.")


def problem(key, value):
    """None if the value is usable, else a short message for the Artist"""
    name = NAMES[key]
    v = (value or "").strip()
    if not v:
        return f"{name} path not set"
    if "<" in v or ">" in v:
        return f"{name} path is still a placeholder: {v}"
    if key == "upstream_repo":
        if not os.path.isdir(v):
            return f"{name} path not found: {v}"
        miss = [f for f in UPSTREAM_FILES if not os.path.isfile(os.path.join(v, f))]
        return f"{name} folder has no {', '.join(miss)}: {v}" if miss else None
    if not os.path.isfile(v):
        return f"{name} path not found: {v}"
    if not re.fullmatch(EXE_RE[key], os.path.basename(v), re.I):
        return f"{name} path is not the {name} program: {v}"
    if key == "nuke" and not nuke_supported(v):
        return unsupported_nuke_message(v)
    return None


def read_site(path=None):
    """-> (values, error).  values: the file's tool keys; error: None / 'missing' / 'invalid JSON …'"""
    path = path or site_path()
    if not os.path.exists(path):
        return {}, "missing"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        return {}, f"invalid JSON ({e})"
    if not isinstance(data, dict):
        return {}, "invalid JSON (not an object)"
    return data, None


def status(path=None, keys=KEYS):
    """First-run / preflight view of the workstation: what is missing, in Artist words."""
    path = path or site_path()
    data, err = read_site(path)
    values = {k: os.environ.get(f"COMPANION_{k.upper()}") or data.get(k) or "" for k in KEYS}
    problems = []
    if err == "missing":
        problems.append({"key": "site", "message": f"Workstation configuration not found ({path})"})
    elif err:
        problems.append({"key": "site", "message": f"Workstation configuration is not valid: {err}"})
    for k in keys:
        if err == "missing" and not os.environ.get(f"COMPANION_{k.upper()}"):
            continue  # one line for a missing file is enough
        msg = problem(k, values[k])
        if msg:
            problems.append({"key": k, "message": msg})
    return {"path": path, "values": values, "problems": problems, "ok": not problems,
            "nuke_version": nuke_version(values["nuke"]), "companion_on_network_drive": is_network_path(ROOT)}


# ------------------------------------------------------------------ drives
def is_network_path(path):
    """True for UNC paths and mapped network drives (Windows); False when it cannot be told."""
    p = os.path.abspath(path)
    if p.startswith(("\\\\", "//")):
        return True
    if sys.platform != "win32" or len(p) < 2 or p[1] != ":":
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(f"{p[0]}:\\") == 4   # DRIVE_REMOTE
    except Exception:  # noqa: BLE001
        return False


def fixed_drives():
    if sys.platform != "win32":
        return []
    import ctypes
    return [f"{d}:/" for d in string.ascii_uppercase
            if ctypes.windll.kernel32.GetDriveTypeW(f"{d}:\\") == 3]   # DRIVE_FIXED (local disks only)


# ------------------------------------------------------------------ detection
def program_files(roots=None):
    if roots:
        return [r.replace("\\", "/") for r in roots]
    out = []
    for r in (os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles"), "C:/Program Files"):
        if r and os.path.isdir(r) and os.path.normcase(os.path.abspath(r)) not in {os.path.normcase(os.path.abspath(x)) for x in out}:
            out.append(r.replace("\\", "/"))
    return out


def _found(path, label, version):
    return {"path": os.path.normpath(path).replace("\\", "/"), "label": label, "version": version}


def detect_houdini(roots=None):
    out = []
    for pf in program_files(roots):
        for d in glob.glob(os.path.join(pf, "Side Effects Software", "Houdini*")):
            exe = os.path.join(d, "bin", "hython.exe")
            if os.path.isfile(exe):
                v = os.path.basename(d).replace("Houdini", "").strip()
                out.append(_found(exe, f"Houdini {v}", v))
    return sorted(out, key=lambda f: version_key(f["version"]))


def detect_maya(roots=None):
    out = []
    for pf in program_files(roots):
        for d in glob.glob(os.path.join(pf, "Autodesk", "Maya*")):
            exe = os.path.join(d, "bin", "mayapy.exe")
            if os.path.isfile(exe):
                v = os.path.basename(d).replace("Maya", "").strip()
                out.append(_found(exe, f"Maya {v}", v))
    return sorted(out, key=lambda f: version_key(f["version"]))


def detect_nuke(roots=None):
    out = []
    for pf in program_files(roots):
        for d in glob.glob(os.path.join(pf, "Nuke*")):
            for exe in glob.glob(os.path.join(d, "Nuke*.exe")):
                if re.fullmatch(r"nuke\d+\.\d+\.exe", os.path.basename(exe), re.I):
                    v = nuke_version(exe)
                    f = _found(exe, f"Nuke {v}", v)
                    f["supported"] = nuke_supported(exe)
                    if not f["supported"]:
                        f["label"] += " (unsupported)"
                    out.append(f)
    return sorted(out, key=lambda f: version_key(f["version"]))


def search_roots(home=None, extra=None):
    """known locations for tools without an installer (AI Tracking, ffmpeg); never a whole drive"""
    home = home or os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in ("Downloads", "Desktop", "Documents")]
    for drv in fixed_drives():
        roots.append(os.path.join(drv, "Tools"))
        roots += [d for d in glob.glob(os.path.join(drv, "*")) if os.path.isdir(d)
                  and re.search(r"ai[_ -]?tracking|colmap", os.path.basename(d), re.I)]
    env = os.environ.get("COMPANION_SEARCH_ROOTS")
    roots += [r for r in (env.split(os.pathsep) if env else []) if r]
    roots += list(extra or [])
    seen, out = set(), []
    for r in roots:
        k = os.path.normcase(os.path.abspath(r))
        if k not in seen and os.path.isdir(r):
            seen.add(k)
            out.append(r)
    return out


def _walk(root, max_depth):
    """os.walk limited in depth and size; skips system / cache folders"""
    n = 0
    for d, dirs, files in os.walk(root):
        n += 1
        if n > WALK_LIMIT:
            return
        rel = os.path.relpath(d, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.startswith(".")] if depth < max_depth else []
        yield d, files


def detect_ai_tracking(roots=None, max_depth=3):
    out, seen = [], set()
    for r in (roots if roots is not None else search_roots()):
        for d, files in _walk(r, max_depth):
            if "run_autotracker.py" in files and not problem("upstream_repo", d):
                k = os.path.normcase(os.path.abspath(d))
                if k not in seen:
                    seen.add(k)
                    out.append(_found(d, os.path.basename(d), None))
    return out


def detect_ffmpeg(roots=None, near=()):
    """-> [{ffmpeg, ffprobe, label}] for every bin folder holding both"""
    cands = ["C:/ffmpeg/bin"] + glob.glob("C:/ffmpeg/*/bin") + glob.glob("C:/Tools/ffmpeg*/bin") \
        + glob.glob("C:/Tools/ffmpeg*/*/bin")
    for n in near:  # e.g. next to the AI Tracking install
        p = os.path.dirname(os.path.normpath(n))
        cands += glob.glob(os.path.join(p, "ffmpeg*", "bin")) + glob.glob(os.path.join(p, "ffmpeg*", "*", "bin"))
    for r in roots or []:
        cands += glob.glob(os.path.join(r, "ffmpeg*", "bin")) + glob.glob(os.path.join(r, "bin"))
    w = shutil.which("ffmpeg")
    if w:
        cands.append(os.path.dirname(w))
    out, seen = [], set()
    for b in cands:
        fm, fp = os.path.join(b, "ffmpeg.exe"), os.path.join(b, "ffprobe.exe")
        k = os.path.normcase(os.path.abspath(b))
        if k not in seen and os.path.isfile(fm) and os.path.isfile(fp):
            seen.add(k)
            out.append({"ffmpeg": os.path.normpath(fm).replace("\\", "/"), "ffprobe": os.path.normpath(fp).replace("\\", "/"),
                        "label": os.path.normpath(b).replace("\\", "/")})
    return out


def detect_all(program_roots=None, search=None):
    ai = detect_ai_tracking(search)
    roots = search if search is not None else search_roots()
    return {"hython": detect_houdini(program_roots), "mayapy": detect_maya(program_roots),
            "nuke": detect_nuke(program_roots), "upstream_repo": ai,
            "ffmpeg": detect_ffmpeg(roots, near=[a["path"] for a in ai])}


def default_choice(key, found, current=None):
    """Keep a valid current value; else Nuke -> LOWEST SUPPORTED version (none -> None),
    Houdini / Maya -> highest, others first."""
    if current and not problem(key, current):
        return current.replace("\\", "/")
    if key == "ffprobe":
        return found[0]["ffprobe"] if found else None
    if not found:
        return None
    if key == "ffmpeg":
        return found[0]["ffmpeg"]
    if key == "nuke":   # sorted ascending: the lowest SUPPORTED version, never an unsupported one
        return next((f["path"] for f in found if f.get("supported", nuke_supported(f["path"]))), None)
    if key in ("hython", "mayapy"):
        return found[-1]["path"]
    return found[0]["path"]


# ------------------------------------------------------------------ save
def validate(values):
    return [{"key": k, "message": m} for k in KEYS for m in [problem(k, values.get(k))] if m]


def save(values, path=None):
    """Validate every required path, then write site.json atomically (never invalid JSON).
    Keys other than the tools (e.g. work_root) of an existing file are kept.  -> problems ([] = saved)"""
    path = path or site_path()
    probs = validate(values)
    if probs:
        return probs
    old, err = read_site(path)
    data = {"_comment": COMMENT}
    if not err:
        data.update({k: v for k, v in old.items() if k not in KEYS and k != "_comment"})
    for k in KEYS:
        data[k] = os.path.normpath(values[k].strip()).replace("\\", "/")
    text = json.dumps(data, indent=1) + "\n"
    json.loads(text)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="site.", suffix=".json.tmp", dir=os.path.dirname(os.path.abspath(path)))
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    return []

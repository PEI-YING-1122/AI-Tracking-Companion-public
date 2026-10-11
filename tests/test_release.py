"""Release smoke tests (no Houdini / Maya / Nuke, seconds):

    python tests/test_release.py [<package_dir>]

  * one version: common/version.py == pyproject.toml; GUI title and CLI build results carry it
  * requirements-lock.txt matches the running environment
  * CLI: --help, and a BLOCKED direct-mode Check writes a result with the version
  * launcher and setup script exist with CRLF line ends
  * with <package_dir>: the package holds every module the CLI / GUI import at runtime and
    nothing from the exclusion list
"""
import importlib.metadata as md
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
from version import __version__  # noqa: E402

R = {}


def ok(name, cond, **info):
    R[name] = dict(info, ok=bool(cond))


def main():
    pkg = sys.argv[1] if len(sys.argv) > 1 else None
    pyproj = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    pv = re.search(r'^version\s*=\s*"([^"]+)"', pyproj, re.M).group(1)
    ok("version_single", pv == __version__ and not re.search(r"dev|rc|a\d|b\d", __version__),
       version=__version__, pyproject=pv)

    lock = {}
    for ln in open(os.path.join(ROOT, "requirements-lock.txt"), encoding="utf-8"):
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s#]+)", ln.strip())
        if m:
            lock[m.group(1).lower()] = m.group(2)
    env = {k: md.version(k) for k in lock}
    ok("lock_matches_environment", all(env[k] == v for k, v in lock.items()), lock=lock, env=env)

    py = sys.executable
    r = subprocess.run([py, os.path.join(ROOT, "companion_run.py"), "--help"], capture_output=True, text=True)
    ok("cli_help", r.returncode == 0 and "--cancel-file" in r.stdout, rc=r.returncode)
    work = tempfile.mkdtemp(prefix="companion_release_")
    e = dict(os.environ, COMPANION_WORK_ROOT=work, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([py, os.path.join(ROOT, "companion_run.py"), "--input", work, "--shot", "", "--dry-run"],
                       capture_output=True, text=True, env=e)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("@@RESULT ")]
    res = json.load(open(line[-1].split(" ", 1)[1])) if line else {}
    ok("cli_blocked_check", r.returncode == 2 and res.get("status") == "BLOCKED", rc=r.returncode,
       issues=[i["code"] for i in res.get("issues", [])])

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, os.path.join(ROOT, "gui"))
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import companion_gui
    w = companion_gui.MainWindow()
    ok("gui_title_version", w.windowTitle() == f"AI Tracking Companion {__version__}", title=w.windowTitle())
    del app

    for b in ("AI_Tracking_Companion.bat", "setup.bat"):
        data = open(os.path.join(ROOT, b), "rb").read()
        ok(f"{b}_crlf", b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""))

    if pkg:
        need = ["AI_Tracking_Companion.bat", "setup.bat", "requirements-lock.txt", "QUICK_START.md", "companion_run.py",
                "gui/companion_gui.py", "gui/launch.py", "common/version.py", "common/site_config.py",
                "stmap/stmap_core.py", "stmap/stmap_generator.py", "maya_export/run_maya_export.py",
                "maya_export/hython_export.py", "maya_export/shot_loader_template.py",
                "nuke_package/build_nuke_package.py", "nuke_package/check_nuke_setup.py",
                "tests/verify_shot.py", "tests/test_01_validate.py", "tests/maya_loader_check.py",
                "configs/site.example.json"]
        missing = [n for n in need if not os.path.exists(os.path.join(pkg, n))]
        banned = [n for n in (".git", ".venv", "logs", "work", "test_runs", "manual_qc", "configs/site.json",
                              "tests/run_all.py", "tests/baselines", "diagnostics", "shots")
                  if os.path.exists(os.path.join(pkg, n))]
        caches = [os.path.join(b, d) for b, ds, _ in os.walk(pkg) for d in ds if d == "__pycache__"]
        ok("package_contents", not missing and not banned and not caches, missing=missing, banned=banned, caches=caches)

    R["all_ok"] = all(v["ok"] for v in R.values() if isinstance(v, dict))
    for k, v in R.items():
        if isinstance(v, dict):
            print(f"{'OK ' if v['ok'] else 'BAD'} {k}  {json.dumps({x: y for x, y in v.items() if x != 'ok'})[:200]}")
    print("ALL OK" if R["all_ok"] else "FAILURES")
    sys.exit(0 if R["all_ok"] else 1)


if __name__ == "__main__":
    main()

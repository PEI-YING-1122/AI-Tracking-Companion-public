"""Build the copyable release folder AI_Tracking_Companion_v<version>/ (no installer).

    python scripts/make_release_package.py <out_dir> [--with-uv <uv.exe>] [--ref <git ref>]

Takes the files committed at <ref> (default HEAD; the working tree must be clean) and keeps
only what runs on an Artist workstation. Not included: .git, .venv, configs/site.json, work,
logs, test data, regression suites, reports, diagnostics, caches. The Python environment is
created on the target machine by setup.bat (requirements-lock.txt); --with-uv adds tools/uv.exe
so the target needs nothing pre-installed except Houdini / Maya / Nuke / ffmpeg / AI Tracking.
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
from version import __version__  # noqa: E402

INCLUDE_FILES = {"AI_Tracking_Companion.bat", "setup.bat", "requirements-lock.txt", "pyproject.toml", "README.md",
                 "QUICK_START.md", "CHANGELOG.md", "companion_run.py",
                 "configs/site.example.json", "configs/project_template.json", "configs/shot_template.json",
                 # validation used by every build (imported / started by companion_run)
                 "tests/verify_shot.py", "tests/test_01_validate.py", "tests/maya_loader_check.py",
                 "docs/gui.md", "docs/configuration.md", "docs/known_upstream_behavior.md",
                 "docs/RELEASE_NOTES_v0.2.0.md", "docs/DEPLOYMENT_TEST_v0.2.0.md"}
INCLUDE_DIRS = ("common/", "gui/", "stmap/", "maya_export/", "nuke_package/")


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, check=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--with-uv")
    ap.add_argument("--ref", default="HEAD")
    a = ap.parse_args()
    if git("status", "--porcelain").strip():
        sys.exit("working tree is not clean: commit first (the package must equal a commit)")
    commit = git("rev-parse", "--short", a.ref + "^{commit}").strip()
    files = [f for f in git("ls-tree", "-r", "--name-only", a.ref).splitlines()
             if f in INCLUDE_FILES or (f.startswith(INCLUDE_DIRS) and not f.endswith((".pyc", ".pyo")))]
    missing = sorted(INCLUDE_FILES - set(files))
    if missing:
        sys.exit(f"not committed at {a.ref}: {missing}")
    dest = os.path.join(os.path.abspath(a.out_dir), f"AI_Tracking_Companion_v{__version__}")
    if os.path.exists(dest):
        sys.exit(f"exists: {dest}")
    for f in files:  # file content exactly as committed (git show), line ends as in the repository
        out = os.path.join(dest, *f.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        data = subprocess.run(["git", "-C", ROOT, "show", f"{a.ref}:{f}"], capture_output=True, check=True).stdout
        if f.endswith(".bat"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        open(out, "wb").write(data)
    if a.with_uv:
        os.makedirs(os.path.join(dest, "tools"), exist_ok=True)
        shutil.copy2(a.with_uv, os.path.join(dest, "tools", "uv.exe"))
    open(os.path.join(dest, "RELEASE.txt"), "w", encoding="utf-8").write(
        f"AI Tracking Companion {__version__}\ncommit {commit}\nfiles {len(files)}\n"
        f"Python environment: run setup.bat once (creates .python\\ and .venv\\ here)\n")
    size = sum(os.path.getsize(os.path.join(b, x)) for b, _, fs in os.walk(dest) for x in fs)
    print(f"{dest}\n{len(files)} files from {commit}, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

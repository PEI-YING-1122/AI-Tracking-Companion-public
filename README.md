# AI Tracking Companion

Independent companion utility for
**[chordee/colmap-camera-tracking](https://github.com/chordee/colmap-camera-tracking)** ("AI Tracking").

> **Important:** this project does not modify the upstream AI Tracking repository. It is not a
> fork and not an official part of AI Tracking: it reads the results AI Tracking produces and
> builds a Maya / Nuke production delivery from them.

**Windows Release: v0.2.1**

## Features
- Maya camera delivery — Alembic primary, FBX + sidecar fallback (corrected film offset, full-resolution intrinsics)
- Maya point cloud delivery — NPZ + Maya-native particle loader (camera, image plane, point cloud in one call)
- Full-resolution lens STMaps — undistort / converged redistort on the production canvas
- Nuke lens setup — Artist undistort / redistort handoff
- Artist GUI — AI Tracking Folder, Shot Name, Original Plate, Export Folder; Check / Start / Stop
- Transactional build / rollback — stage, validate, publish; backups and exact rollback
- FPS detection / override — video metadata or EXR header, default 24, Artist override

## Basic flow
```
AI Tracking result  +  Original Plate  +  Shot Name
                          |
                          v
        Maya / Nuke delivery  (export/lens, maya, metadata, nuke)
```

| Delivery | Files (`<shot>` = Artist shot name) |
|---|---|
| Lens | `lens/<shot>_undistort_stmap.exr`, `lens/<shot>_redistort_stmap.exr` (32-bit float STMaps, DATA) |
| Maya | `maya/<shot>_load_maya.py` (Artist entry point), `<shot>_cam_corrected.abc` (primary), `<shot>_cam_corrected.fbx` + `<shot>_camera.json` (fallback), `<shot>_points.npz` |
| Metadata | `metadata/<shot>_metadata.json` |
| Nuke | `nuke/<shot>_lens_setup.nk` (lens handoff / example setup, not a comp template) |

## What it does NOT do
- It does **not** modify, fork or patch AI Tracking. The AI Tracking install is read only.
- It does **not** copy plates, the AI Tracking flatten or any source sequence: they are referenced in place.
- It does **not** save the AI Tracking `.hip` (camera fixes happen in memory only).

## Status
`v0.2.1` — **Workstation setup and compatibility fixes** on `v0.2.0` (Production Release: Artist GUI +
transactional builder on the frozen `v0.1.0` core, regression-locked, see `docs/regression.md`).
Release notes: `docs/RELEASE_NOTES_v0.2.1.md` (and `_v0.2.0`), changes: `CHANGELOG.md`, Artist
steps: `QUICK_START.md`.

## Requirements / setup
- Windows x64; AI Tracking installation, Houdini (hython), Maya (mayapy), Nuke, ffmpeg / ffprobe —
  locations in `configs/site.json`, written by **Workstation Setup** (`Configure_Companion.bat`:
  detects the installed tools, Nuke target = lowest installed **supported** Nuke (13.0–17.x) by default, validates
  before saving). TDs may still edit it by hand (`configs/site.example.json`).
- **Install on a local disk** (e.g. `C:\Tools\AI_Tracking_Companion_v0.2.x` or
  `D:\Tools\AI_Tracking_Companion_v0.2.x`). Not a mapped network drive, NAS or restricted share:
  uv's managed Python cannot create its runtime there (`Access denied (os error 5)`), and
  `setup.bat` stops with "Companion runtime must be installed on a local disk." Administrator
  rights are not a workaround.
- Python environment: run `setup.bat` once per workstation. It uses uv (`tools\uv.exe` or uv on
  PATH) to create `.python\` (Python 3.11.14) and `.venv\` (`requirements-lock.txt`) inside the
  Companion folder; nothing system-wide. A `.venv` copied from another computer does not work
  (it points to that computer's Python).
- Release folder: `python scripts/make_release_package.py <out_dir> [--with-uv <uv.exe>]`.

## Usage (GUI)
Double-click `AI_Tracking_Companion.bat` (uses the Companion's `.venv`; or `python gui/companion_gui.py`).
AI Tracking Folder, Shot Name, Original Plate, Export Folder (default `<folder>/export`), FPS,
Maya / Nuke; Check, Start, Stop. No project config needed. The GUI only collects input and
runs the CLI below; it shows the CLI's own result. See `docs/gui.md`.
Requires `uv pip install -e ".[gui]"` (PySide6).

## Usage (CLI)
```
python companion_run.py <shot_config.json> [--overwrite] [--dry-run] [--outputs maya nuke lens]
python companion_run.py --input <AI Tracking folder> --shot <name> --plate <original plate>
                        [--export <dir>] [--fps <override>] [--overwrite] [--dry-run] [--outputs ...]
                        [--cancel-file <path>]
python companion_run.py [--project <project.json>] --input <AI Tracking folder> --detect
python companion_run.py --project <project.json> --input <AI Tracking folder> --shot <name>
                        [--export <dir>] [--plate <path>] [--overwrite] [--dry-run] [--outputs ...]
```
Direct mode (what the GUI uses) needs no project config: export defaults to
`<AI Tracking folder>/export`, fps comes from the plate (else 24, else `--fps`).
A shot config names the AI Tracking scene folder, the source plate and the export root
(`configs/shot_template.json`); project mode (optional preset) builds it from project rules +
plate auto detect. Exit codes: `0` PASS / WARNING, `1` FAIL, `2` BLOCKED, `5` cancelled
(outputs exist, or stopped through the cancel file — nothing published).
Overwrites back the previous delivery up first; the newest `backup_keep` (default 2)
backups per shot / export are kept after a validated publish.

## Layout
```
companion_run.py   CLI / builder entry
gui/               Artist GUI (PySide6), a shell over companion_run.py
common/            config, path resolver, shot metadata, version
stmap/             lens maths and STMap generation (frozen core)
maya_export/       Houdini -> Maya camera / point cloud, Maya loader template (frozen core)
nuke_package/      Nuke writers and checks
tests/             regression suites and baselines
diagnostics/       one-off probes kept for reference
configs/           site / project / shot templates
docs/              documentation
```

## Upstream attribution
AI Tracking — <https://github.com/chordee/colmap-camera-tracking> — is a separate project by its
own authors. AI Tracking Companion is an independent tool: it does not fork, vendor or modify the
upstream source and is not affiliated with or endorsed by it. It uses the results an AI Tracking
installation produces (and, read only, its lens canvas rule from the installed copy) to build the
Maya / Nuke production delivery. Upstream behaviours that affect the Companion are recorded in
`docs/known_upstream_behavior.md` (reported, never patched).

## License
No license has been chosen yet. This repository contains only Companion
code: no AI Tracking source code, no COLMAP, no project data.

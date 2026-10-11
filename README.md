# AI Tracking Companion

Independent companion tool for **[chordee/colmap-camera-tracking](https://github.com/chordee/colmap-camera-tracking)** ("AI Tracking").

AI Tracking solves the camera. The Companion takes over from a **finished** AI Tracking
output and builds the production delivery for Maya and Nuke:

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
`v0.1.0` — **Core Production Baseline**. The lens / camera / point-cloud core is frozen and
regression-locked (see `docs/regression.md`). `v1.0.0` is reserved for the complete
production tool (transactional builder + GUI) validated on real shots.

## Requirements
- Windows, Python 3.11 (a local `.venv`; `uv venv` + `uv pip install -e .` works)
- Houdini (hython), Maya (mayapy), Nuke — paths in `configs/site.json`
  (copy `configs/site.example.json`)
- ffmpeg / ffprobe

## Usage (GUI)
```
python gui/companion_gui.py
```
Project, AI Tracking folder, shot name, export folder, Maya / Nuke. The GUI only collects
input and runs the CLI below (`--detect`, `--dry-run` for Check, then the build); it shows
the CLI's own result. See `docs/gui.md`. Requires `pip install -e .[gui]` (PySide6).

## Usage (CLI)
```
python companion_run.py <shot_config.json> [--overwrite] [--dry-run] [--outputs maya nuke lens]
python companion_run.py --project <project.json> --input <AI Tracking folder> --shot <name>
                        [--export <dir>] [--plate <path>] [--overwrite] [--dry-run] [--outputs ...]
python companion_run.py --project <project.json> --input <AI Tracking folder> --detect
```
A shot config names the AI Tracking scene folder, the source plate and the export root
(`configs/shot_template.json`); project mode builds it from project rules + auto detect.
Exit codes: `0` PASS / WARNING, `1` FAIL, `2` BLOCKED, `5` cancelled (outputs exist).
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

## License / relation to upstream
This repository contains only Companion code. It does not include AI Tracking source code,
COLMAP, or any project data.

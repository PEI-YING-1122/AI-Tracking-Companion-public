# Changelog

## v0.2.1 — Workstation setup and compatibility fixes
Workstation setup and compatibility fixes for v0.2.0. No new
features; the frozen lens / STMap / camera / point cloud core is unchanged.
Details: `docs/RELEASE_NOTES_v0.2.1.md`.

- Original Plate: PNG sequences supported (`.exr .jpg .jpeg .png`, any letter case); only the
  picked sequence is read even when other sequences share the folder; clearer messages
  ("No supported image-sequence frames (EXR/JPG/JPEG/PNG) found", "Do not select AI Tracking
  working images. Select the original distorted production plate.").
- AI Tracking flatten: three states — production compatible / reference compatible (principal
  point within 0.05 px: still the Maya image plane and the Nuke tracking reference, labelled
  "reference only") / incompatible (not used, WARNING). Never a production lens source.
- Nuke setup (Artist reference topology): Original Plate → CROP_BLACK_OUTSIDE →
  APPLY_UNDISTORT; TRACKING_REFERENCE_FLATTEN → APPLY_REDISTORT (reference only, own TRACKING
  REFERENCE backdrop). Without a tracking reference APPLY_REDISTORT takes APPLY_UNDISTORT.
  Final layout from the Artist reference (positions / backdrop geometry only); LENS_INFO shows
  shot, plate size, frames, fps value, undistort size and STMap mode (fps source stays in
  metadata / GUI / log).
- Nuke: the `.nk` Root name is finalised to the delivery path before validation (Nuke 17 kept
  the build stage path → `stage_path_leak`): the Root block is parsed by brace depth, every Root
  `name` knob is removed and exactly one final name is written. Any other stage reference still fails.
- Nuke target version: supported Nuke range 13.0–17.x (Companion runtime / `.nk` writer; Nuke 12
  and older cannot run the writer). Workstation Setup defaults to the lowest installed
  supported Nuke and refuses an unsupported one before saving; the GUI Check shows
  "Nuke Generator".
- Workstation Setup (`Configure_Companion.bat`): detects Houdini / Maya / Nuke / FFmpeg /
  AI Tracking and writes a validated `configs/site.json`; the GUI shows "Workstation Setup
  Required" on first run; the CLI reports BLOCKED instead of a FileNotFoundError.
- `setup.bat` refuses network / mapped drives ("Companion runtime must be installed on a local
  disk.") and no longer copies the placeholder example into `site.json`.

## v0.2.0 — Production Release
Artist GUI, transactional builder and deployment files on top of the frozen v0.1.0 core.
Details: `docs/RELEASE_NOTES_v0.2.0.md`.

- Project-independent Artist GUI (PySide6): AI Tracking Folder, Shot Name, Original Plate,
  Export Folder, FPS; Check / Start / Stop.
- Direct mode CLI (`--input --shot --plate`), `--detect`, `--cancel-file`.
- Transactional builder: stage / validate / publish, backup + exact rollback, backup retention
  (`backup_keep`, default 2), partial builds with module provenance.
- FPS detection (video / EXR header) with default 24 and Artist override.
- Windows launcher `AI_Tracking_Companion.bat`, one-time `setup.bat`, `requirements-lock.txt`.
- Core (lens / STMap / camera / NPZ / Maya loader / Nuke setup / metadata) unchanged since v0.1.0:
  2700 / 2700 baseline values identical.

## v0.1.0 — Core Production Baseline
Lens, STMap, camera correction, Maya (ABC / FBX + sidecar, NPZ point cloud, loader) and Nuke
Artist lens setup frozen and regression-locked.

# Changelog

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

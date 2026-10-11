# AI Tracking Companion v0.2.0 — Production Release

Companion for [chordee/colmap-camera-tracking](https://github.com/chordee/colmap-camera-tracking)
("AI Tracking"): builds the Maya and Nuke production delivery of a finished AI Tracking result.
AI Tracking itself is not modified.

## Main features
- **Project-independent Artist GUI** — AI Tracking Folder, Shot Name, Original Plate, Export
  Folder; no project config needed (project configs remain an optional CLI preset).
- **Original Plate as an explicit input** — any frame of an EXR / JPG / PNG / … sequence or a
  video; validated against the AI Tracking result.
- **FPS auto detection + override** — video metadata or EXR header, otherwise 24 (default),
  Artist override (23.976 / 29.97 … as exact 1000/1001 rates).
- **Maya camera** — Alembic (`<shot>_cam_corrected.abc`) primary; FBX + `<shot>_camera.json`
  sidecar fallback; corrected film offset (winy), full-resolution intrinsics.
- **Point cloud** — `<shot>_points.npz` + Maya-native particle loader (`<shot>_load_maya.py`:
  camera, image plane, point cloud in one call).
- **Full-resolution production STMaps** — undistort / converged redistort on the converged
  production canvas.
- **Nuke Artist lens setup** — `<shot>_lens_setup.nk` (lens handoff, not a comp template).
- **Transactional builder** — stage → validate → publish; nothing is published unless every
  validation passes.
- **Backup / rollback** — an overwrite backs the previous delivery up first (newest 2 kept per
  shot / export); a failed publish is rolled back exactly.
- **Safe cooperative Stop** — stops at the next safe step, never during publish.
- **Windows launcher** — `AI_Tracking_Companion.bat`; one-time `setup.bat` per workstation.
- **Metadata / validation** — `<shot>_metadata.json` (lens, camera, frames, fps, provenance,
  module build ids); every build re-validates camera projection, STMaps, Maya loader and Nuke setup.

## Validation
- GUI Human QC — PASS
- Full Regression (PoC, workflow, transaction, project mode, partial build, GUI) — PASS
- v0.1.0 core baseline — 2700 / 2700 values identical
- Maya manual QC — PASS
- Nuke manual QC — PASS

## Known limitations
1. If the AI Tracking flatten is not in the production space (e.g. proxy-resolution tracking),
   the delivery is built without the tracking flatten reference and the GUI reports a WARNING.
2. JPG / PNG sequences usually carry no FPS: 24 fps is used unless the Artist overrides it.
3. This release is Windows-oriented (launcher, setup, tool paths).
4. Deployment to other workstations is being validated separately
   (`docs/DEPLOYMENT_TEST_v0.2.0.md`); the environment is created per machine by `setup.bat`.
5. Requires on the workstation: AI Tracking installation, Houdini (hython), Maya (mayapy), Nuke,
   ffprobe — locations in `configs/site.json`.
6. AI Tracking scenes contain absolute paths: an AI Tracking folder that was moved after the
   solve cannot be exported (upstream behaviour, see `docs/known_upstream_behavior.md`).

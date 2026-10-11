# Deployment Test — AI Tracking Companion v0.2.0

Workstation: ____________________   Tester: ____________   Date: ____________

## 0. Before the test (TD, once per workstation)
1. Copy the folder **`AI_Tracking_Companion_v0.2.0`** to the workstation
   (local disk recommended, e.g. `D:\Tools\AI_Tracking_Companion_v0.2.0`; a path with spaces is fine).
2. Double-click **`setup.bat`** (creates `.python\` and `.venv\` inside the folder; needs
   internet for Python + packages, or a `wheels\` folder — see setup.bat). Expected last lines:
   `numpy 2.4.6 | opencv 4.13.0 | PySide6 6.11.1` and `Setup complete.`
3. Edit **`configs\site.json`** (created by setup from the example) for this workstation:
   | key | example |
   |---|---|
   | `hython` | `C:/Program Files/Side Effects Software/Houdini 20.0.547/bin/hython.exe` |
   | `mayapy` | `C:/Program Files/Autodesk/Maya2023/bin/mayapy.exe` |
   | `nuke` | `C:/Program Files/Nuke13.2v3/Nuke13.2.exe` |
   | `ffprobe`, `ffmpeg` | the ffmpeg build of the AI Tracking install |
   | `upstream_repo` | `<AI Tracking install>/colmap-camera-tracking-master` |
   Use forward slashes. No Python file needs editing.

Use a **new** AI Tracking result solved on this workstation (or one whose folder was not moved
after the solve) and its original plate. Record the folder sizes / file list of the AI Tracking
folder before the test (step "AI Tracking folder unchanged").

## 1. Checklist
- [ ] Companion folder copied completely (`RELEASE.txt` shows v0.2.0 and the commit)
- [ ] `setup.bat` finished with `Setup complete.`
- [ ] Double-click `AI_Tracking_Companion.bat` opens the GUI (title `AI Tracking Companion 0.2.0`)
- [ ] Windows PATH was not changed (no PowerShell, no activation needed)
- [ ] GUI displays correctly (labels, buttons, ⓘ icons readable)
- [ ] AI Tracking Folder — Browse works
- [ ] Shot Name can be typed
- [ ] Original Plate — Browse works (pick any frame / the video)
- [ ] Export Folder becomes `<AI Tracking Folder>\export` automatically
- [ ] FPS is correct, or can be overridden (Source changes to Artist Override)
- [ ] Check: Ready / expected WARNING (write down any message): __________________
- [ ] Start: BUILD COMPLETE
- [ ] Maya delivery created (`export\maya\`: `_load_maya.py`, `.abc`, `.fbx`, `_camera.json`, `_points.npz`)
- [ ] Nuke delivery created (`export\nuke\<shot>_lens_setup.nk`)
- [ ] STMaps created (`export\lens\<shot>_undistort_stmap.exr`, `_redistort_stmap.exr`)
- [ ] Maya: drag `<shot>_load_maya.py` into Maya → camera, image plane, point cloud
- [ ] Nuke: open `<shot>_lens_setup.nk` → plate reads, undistort / redistort work
- [ ] Open Export Folder opens Explorer at the export folder
- [ ] Existing delivery → Start → **No** → Cancelled, nothing changed
- [ ] Existing delivery → Start → **Yes** → BUILD COMPLETE, backup made
      (`<Companion>\work\<shot>\builds\<id>\backup\`)
- [ ] Stop during a Start → Cancelled, export folder unchanged
- [ ] AI Tracking folder unchanged (no new / changed files, HIP not saved)
- [ ] Unrelated files in the export folder were not deleted or changed

## 2. If something fails
- GUI does not open: the launcher shows the reason in its window, or a message box points to
  `%LOCALAPPDATA%\AI_Tracking_Companion\gui_last_run.log`.
- Check / Start messages: copy **Details / Log**, plus `<Companion>\work\<shot>\builds\<latest>\build_result.json`.
- Send both to the TD with this checklist.

Result: [ ] PASS  [ ] PASS with notes  [ ] FAIL — notes: ______________________________

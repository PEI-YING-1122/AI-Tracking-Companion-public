# Deployment Test — AI Tracking Companion v0.2.1

Workstation: ____________________   Tester: ____________   Date: ____________

## 0. Before the test (TD, once per workstation)
1. Copy the folder **`AI_Tracking_Companion_v0.2.1`** to a **local disk**, e.g.
   `C:\Tools\AI_Tracking_Companion_v0.2.1` or `D:\Tools\AI_Tracking_Companion_v0.2.1`.
   - **Not** a mapped network drive (`U:\…`), NAS or share: uv's managed Python cannot be
     installed there (`Access denied (os error 5)`). `setup.bat` stops with
     "Companion runtime must be installed on a local disk." Do not run as Administrator to work
     around it.
   - Keep the folder path **short (under ~100 characters)**: Nuke cannot open paths of 260+
     characters and the build's validation files sit ~110 characters below this folder.
   - Moving the folder later: run `setup.bat` again.
2. Double-click **`setup.bat`** (creates `.python\` and `.venv\` inside the folder; needs
   internet for Python + packages, or a `wheels\` folder). Expected:
   `numpy 2.4.6 | opencv 4.13.0 | PySide6 6.11.1` and `Setup complete.`
3. **Workstation Setup** opens (or double-click **`Configure_Companion.bat`**):
   - Houdini, Maya, Nuke Target, FFmpeg, FFprobe, AI Tracking are detected; several versions →
     dropdown; not found → Browse.
   - **Nuke Target** defaults to the lowest installed **supported** Nuke (13.0–17.x; Nuke 12 and
     older are refused).
   - **Save Configuration** (only possible when every path is valid) writes `configs\site.json`.
   No JSON / Python file needs editing.

Use a representative validation shot (AI Tracking result solved on this workstation
or not moved after the solve) and its original plate (PNG or JPG sequence).

## 1. Checklist
- [ ] Companion folder on a local disk (`RELEASE.txt` shows v0.2.1 and the commit)
- [ ] `setup.bat` finished with `Setup complete.`
- [ ] (optional) the same folder on a mapped drive: `setup.bat` stops with the local-disk message
- [ ] Workstation Setup: all rows ✓, Save Configuration → `Saved …site.json`
- [ ] `AI_Tracking_Companion.bat` opens the GUI (title `AI Tracking Companion 0.2.1`), no
      "Workstation Setup Required" box
- [ ] AI Tracking Folder / Shot Name `<shot>` / Original Plate `<shot>_1001.png` (any frame)
- [ ] Check: Ready / Ready (warnings). Original Plate `PNG sequence`; Frames and Resolution as expected;
      FPS `24 (Default)` or the Artist override
- [ ] Check: **Flatten** `ⓘ Tracking Flatten: Reference Only (principal point Δ between 0.01 and 0.05 px)`
      (no `flatten_not_used`)
- [ ] Check: **Nuke Generator** = the chosen (lower) Nuke version: __________
- [ ] Start: BUILD COMPLETE, 9 files published
- [ ] Maya: drag `<shot>_load_maya.py` → Camera, Point Cloud, Timeline, Resolution, FPS PASS,
      **Image Plane present** (AI Tracking flatten, reference)
- [ ] Nuke (the Artists' lower version, e.g. Nuke 16): `<shot>_lens_setup.nk` opens
- [ ] Nuke: Original Plate, Undistort, Redistort PASS
- [ ] Nuke: **TRACKING_REFERENCE_FLATTEN present**, label "AI Tracking flatten — reference only"
- [ ] Nuke: **APPLY_UNDISTORT** inputs = CROP_BLACK_OUTSIDE (image) + READ_STMAP_UNDISTORT (STMap);
      CROP_BLACK_OUTSIDE ← READ_ORIGINAL_PLATE
- [ ] Nuke: **APPLY_REDISTORT** inputs = TRACKING_REFERENCE_FLATTEN (image) + READ_STMAP_REDISTORT (STMap);
      not APPLY_UNDISTORT (same wiring as the Artist reference setup)
- [ ] Nuke: layout as the Artist reference (SOURCE / UNDISTORT / REDISTORT / TRACKING REFERENCE);
      LENS_INFO = 4 lines: shot, `plate … frames … fps 24` (no fps source in brackets), undistort size, STMap mode
- [ ] Nuke: File → Script Name / Root name = the export path (`…\export\nuke\<shot>_lens_setup.nk`),
      not `…\work\…\stage\…`; in a text editor the Root block has exactly **one** `name` line
- [ ] Validate PASS, Publish PASS, 9 files published (no `stage_path_leak`)
- [ ] Existing delivery → Start → **No** → Cancelled; **Yes** → BUILD COMPLETE, backup made
- [ ] Stop during a Start → Cancelled, export folder unchanged
- [ ] AI Tracking folder unchanged; unrelated files in the export folder untouched
- [ ] Original Plate = an AI Tracking working image (`…\images\frame_000001.jpg`) → BLOCKED
      "Do not select AI Tracking working images. Select the original distorted production plate."

## 2. If something fails
- GUI does not open: the launcher window or `%LOCALAPPDATA%\AI_Tracking_Companion\gui_last_run.log`.
- Check / Start messages: copy **Details / Log**, plus
  `<Companion>\work\<shot>\builds\<latest>\build_result.json`.
- Send both to the TD with this checklist.

Result: [ ] PASS  [ ] PASS with notes  [ ] FAIL — notes: ______________________________

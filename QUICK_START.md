# AI Tracking Companion — Quick Start

1. Open the **AI Tracking Companion** folder.
2. Double-click **`AI_Tracking_Companion.bat`**.
3. **AI Tracking Folder** → Browse… → the AI Tracking result folder.
4. **Shot Name** → type the shot name (e.g. `demo_sh0010`).
5. **Original Plate** → Browse… → any frame of the original plate sequence (EXR / JPG / PNG), or the video.
   Never the AI Tracking working images (`imagesrame_…jpg`).
6. Check **Export Folder** (default: `<AI Tracking Folder>\export`) and **FPS**
   (type another value if the shown one is wrong).
7. Press **Check** — wait for **Ready**.
8. Press **Start** — wait for **BUILD COMPLETE**, then **Open Export Folder**.

The delivery:
```
export\maya\<shot>_load_maya.py      drag into Maya
export\nuke\<shot>_lens_setup.nk     open in Nuke
export\lens\                         undistort / redistort STMaps
export\metadata\<shot>_metadata.json
```

- **Stop** stops after the current step; nothing is delivered, the export folder stays as it was.
- If the shot was delivered before, Start asks **Overwrite existing delivery?** — the previous
  delivery is backed up first.
- Click **ⓘ** next to Original Plate or FPS for a short explanation.
- Something red? Open **Details / Log** and send its text to the TD.

First time on a new computer (TD):
1. Copy the Companion folder to a **local disk**, e.g. `C:\Tools\AI_Tracking_Companion_v0.2.1`
   (not a mapped network drive / NAS / share — setup stops there).
2. Run `setup.bat` once.
3. **Workstation Setup** opens (later: `Configure_Companion.bat`): check the detected Houdini,
   Maya, Nuke Target (default: the lowest installed supported Nuke, 13–17), FFmpeg / FFprobe and AI Tracking,
   then **Save Configuration**. No JSON editing.
If the GUI shows **Workstation Setup Required**, press **Configure**.
See `docs\DEPLOYMENT_TEST_v0.2.1.md`.

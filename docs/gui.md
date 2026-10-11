# AI Tracking Companion — GUI

Double-click **`AI_Tracking_Companion.bat`** (or `python gui/companion_gui.py`).
The launcher uses the Companion's own `.venv`; no PowerShell, no activation, system PATH untouched.

The GUI is a thin shell over `companion_run.py`. It never computes lens, camera, STMap or
Nuke data and never resolves or validates paths itself: everything shown comes from the
CLI's result (`build_result.json`). The CLI works the same without the GUI.
No project config is needed (project configs remain a CLI / pipeline option).

| GUI action | CLI call |
|---|---|
| choose the AI Tracking Folder | `--input F --detect` (scene, HIP, export default) |
| Check | `--input F --shot S --plate P [--export E] [--fps X] [--outputs …] --dry-run` |
| Start | the same without `--dry-run`, plus `--cancel-file`; `--overwrite` only after **Overwrite existing delivery? → Yes** |
| Stop | creates the cancel file: the CLI stops at its next safe point |

## Inputs
- **AI Tracking Folder** — the AI Tracking output folder. HIP, transforms, tracking flatten,
  camera / lens metadata, tracking resolution and frames are read from it.
- **Shot Name** — required; the basename of every delivered file (`<shot>_cam_corrected.abc`, …).
- **Original Plate ⓘ** — the original distorted plate: any frame of an image sequence
  (EXR / JPG / PNG / …) or a video (MOV / MP4). Resolution, frame range and FPS metadata come from it.
- **Export Folder** — defaults to `<AI Tracking Folder>/export`; can be changed. An existing
  folder is used as it is (never deleted, cleared or recreated); a missing one is created.
  Only the Companion's own files (`lens/ maya/ metadata/ nuke/<shot>_…`) are written.
- **FPS ⓘ** — filled by Check: video metadata, EXR header, otherwise 24 (Default — not a warning).
  Typing another value (e.g. 23.976, 25, 29.97) makes it an Artist Override and runs Check again.
- **Outputs** — Maya, Nuke. Metadata is always generated; Nuke includes the lens STMaps.

## Check
Status **Ready**, **Ready (warnings)**, **BLOCKED** (Start disabled) or **FAIL**, then:
Tracking Scene, Camera, Original Plate, Flatten, Frames (`1001–1100 (100 frames)`),
Resolution (`plate → production canvas`), FPS (value and source), Export.
An existing Companion delivery of this shot is shown as information; Start asks before overwriting.
The internal tracking frame mapping is in Details / Log.

## Start / Stop
Progress: Preflight → Resolving → Building Lens → Building Maya → Building Nuke →
Validating → Publishing → Done.

**Stop** is cooperative: the current step finishes, nothing is published, the export folder stays
as it was, the status becomes **Cancelled**. Once **Publishing** starts Stop is disabled
("Finishing publish transaction...") — the publish completes or rolls back; it is never cut off.

| State | Check | Start | Stop |
|---|---|---|---|
| idle | on | on only after a passing Check of the current inputs | off |
| running | off | off | on |
| publishing | off | off | off |

The result lists Shot, Export Folder and Maya / Nuke / Lens / Metadata (built, kept from an
earlier build, or not built). **Open Export Folder** opens it; Maya and Nuke are not started.

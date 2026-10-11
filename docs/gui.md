# AI Tracking Companion — GUI

```
python gui/companion_gui.py
```

The GUI is a thin shell over `companion_run.py`. It never computes lens, camera, STMap or
Nuke data and never resolves or validates paths itself: everything shown comes from the
CLI's result (`build_result.json`). The CLI works the same without the GUI.

| GUI action | CLI call |
|---|---|
| choose the AI Tracking folder | `--project P --input F --detect` (scene, shot name and export candidates) |
| Check | `--project P --input F --shot S [--export E] [--plate X] [--outputs …] --dry-run` |
| Build | the same without `--dry-run` (`--overwrite` only after the Artist said Yes) |

## Inputs
- **Project** — project configs listed in `site.json` → `project_configs`.
- **AI Tracking Folder** — the AI Tracking output folder (the one holding `<scene>/` and
  `<scene>_transforms.json`). Choosing it fills Shot Name and Export Folder; both can be edited.
- **Outputs** — Maya, Nuke. Metadata is always built. Nuke includes the lens STMaps.
  Lens-only builds are CLI only (`--outputs lens`).
- **Source Plate** — appears only when the plate rules found none or several plates.
  Pick a candidate or browse to any frame of the sequence (or a video); Check runs again.
  The choice is stored for this shot and reused next time (and validated every time).

## Check
Shows Camera (AI Tracking scene / HIP), Camera Model, Plate, Flatten, FPS, Frames,
Resolution and Export Path, plus **Existing Delivery Found** when the export already holds
this shot's delivery.

| Status | Meaning | Build |
|---|---|---|
| Ready | everything resolved | enabled |
| Ready (warnings) | e.g. `FPS source metadata unavailable. Using project setting: 24 fps.` | enabled |
| BLOCKED | e.g. `Multiple valid plate candidates found. Please select source plate.`, Unsupported camera | disabled |
| FAIL | the CLI failed (details in Details / Log) | disabled |

## Build
If a delivery exists the GUI asks **Overwrite existing delivery?** — No cancels, Yes builds
with `--overwrite`. The builder stages, validates, backs the old delivery up and publishes;
a failure publishes nothing (or rolls back). The GUI never moves or deletes files.

Progress: Preflight → Resolving → Building Lens → Building Maya → Building Nuke →
Validating → Publishing → Done. **Details / Log** holds the full CLI log.

The result lists Shot, Export Folder and Maya / Nuke / Lens / Metadata (built, kept from an
earlier build, or not built). **Open Export Folder** opens it; Maya and Nuke are not started.

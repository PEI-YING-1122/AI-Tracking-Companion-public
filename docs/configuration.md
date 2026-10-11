# Configuration layers

| Layer | File | Content | Who edits |
|---|---|---|---|
| site | `configs/site.json` (untracked; from `site.example.json`) | tool executables only (hython, mayapy, nuke, ffprobe, ffmpeg, upstream repo) | TD per workstation |
| project (optional preset) | `<project>.json` (from `configs/project_template.json`) | fps fallback, plate search rules, export rule, shot naming rule, work root | TD per project |
| shot | generated per build (resolver / GUI) | resolved paths, detected facts, artist overrides, build provenance | the tool (Artist via GUI) |

**Project configs are an optional convenience preset**, not a workflow dependency. The Artist
GUI does not use them (direct mode: AI Tracking Folder, Shot Name, Original Plate, Export Folder).
They stay for the CLI (`--project`), regression, batch / pipeline integration and a possible
future Advanced / Preset option.

## Direct mode (GUI) defaults
| Item | Rule |
|---|---|
| export folder | `<AI Tracking folder>/export` unless given; created if missing, never cleared |
| fps | original plate metadata (video / EXR header) → 24 (Default, information only) → Artist override |
| flatten | AI Tracking flatten as Nuke reference when it is in the production space, otherwise not used (WARNING) |
| work folder | `<Companion>/work/<shot>`; site key `work_root` or env `COMPANION_WORK_ROOT` overrides |
| backups | `backup_keep` 2 |

## Project keys (summary)
| Key | Default | Meaning |
|---|---|---|
| `fps` | none | used when the source has no fps (WARNING "FPS source metadata unavailable") |
| `plate_search` | — | ordered plate rules (`{shot}`, `{scene}`, vars) |
| `export_root` | — | export folder rule; `lens/ maya/ metadata/ nuke/` below it |
| `work_root` | `<Companion>/work` | build records, backups, shot configs (never inside the export) |
| `flatten_mode` | `reference_ai_tracking` | `reference_ai_tracking` / `render` / `none` |
| `shot_name_regex` | none | shot name suggestion from plate / scene paths |
| `backup_keep` | `2` | backups kept per shot / export delivery; older ones are removed only after a new delivery was published and validated. Not shown in the GUI. |

A shot config may set `options.backup_keep` the same way.

## Artist overrides (project mode)
A source plate given with `--plate` in project mode is stored in `<work_root>/<shot>/<shot>.shot.json`
and reused next time; it is validated again on every Check / build. In direct mode the Artist
names the Original Plate on every run (it is recorded in the build provenance).

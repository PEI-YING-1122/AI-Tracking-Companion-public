# Configuration layers

| Layer | File | Content | Who edits |
|---|---|---|---|
| site | `configs/site.json` (untracked; from `site.example.json`) | tool executables only (hython, mayapy, nuke, ffprobe, ffmpeg, upstream repo) | TD per workstation |
| project | `<project>.json` (from `configs/project_template.json`) | fps fallback, plate search rules, export rule, shot naming rule, work root | TD per project |
| shot | generated per build (resolver / GUI) | resolved paths, detected facts, artist overrides, build provenance | the tool (Artist via GUI) |

## Site keys used by the GUI
- `project_configs`: list of project config files or folders (every `*.json` in a folder) shown in
  the GUI's Project dropdown. `configs/projects/` inside the Companion is listed as well.
  Machine specific, so it lives in the untracked `site.json`.

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

## Artist overrides
A source plate chosen in the GUI (or `--plate`) is stored in `<work_root>/<shot>/<shot>.shot.json`
and reused next time; it is validated again on every Check / build.

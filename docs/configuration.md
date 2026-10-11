# Configuration layers

| Layer | File | Content | Who edits |
|---|---|---|---|
| site | `configs/site.json` (untracked; from `site.example.json`) | tool executables only (hython, mayapy, nuke, ffprobe, ffmpeg, upstream repo) | TD per workstation |
| project | `<project>.json` (from `configs/project_template.json`) | fps fallback, plate search rules, export rule, shot naming rule, work root | TD per project |
| shot | generated per build (resolver / GUI) | resolved paths, detected facts, artist overrides, build provenance | the tool (Artist via GUI) |

# Known Upstream Behavior (AI Tracking) — recorded, not modified

## COLMAP log files in the AI Tracking tool folder
- Severity: low / quality of life. Does not affect solve correctness.
- Pattern: `colmap.<HOST>.<USER>.log.<SEVERITY>.<YYYYMMDD-HHMMSS>.<PID>` (glog), one set per COLMAP call.
- glog writes to `TEMP` / `TMP`; only without them it falls back to the current working directory.
  Runs launched by the Companion (full environment) put them in `%TEMP%` (user `artist`).
  The files found in the tool folder carry user `invalid-user`, i.e. `USERNAME` was missing too.
- Suspected (inference, not researched further): the AI Tracking GUI builds its QProcess
  environment from `self.process.processEnvironment()`, which for a fresh QProcess is empty,
  so children may not inherit `TEMP` / `USERNAME`.
- Changing only the subprocess cwd would move the files, not fix the missing environment.
- Issue candidate: decide after Companion V1.

## Failed reconstruction reported as success
`run_autotracker.py` treats `sparse/0/cameras.bin` as success even when COLMAP's bundle
adjustment had no 3D points (seen on a rehearsal shot: focal 0.43 px, k1 = 173). The
Companion refuses such scenes (solve sanity guard). Issue candidate.

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
- Status: Known Upstream Behavior, record only. No upstream change, no Companion workaround,
  no GitHub Issue for now. Reproducing the QProcess environment is scheduled after the
  Companion production release; the Issue decision stays with the user.
- The Companion GUI itself starts its CLI with `QProcessEnvironment.systemEnvironment()`
  (full inherited environment), so it does not have this behaviour.

## Failed reconstruction reported as success
`run_autotracker.py` treats `sparse/0/cameras.bin` as success even when COLMAP's bundle
adjustment had no 3D points (seen on a rehearsal shot: focal 0.43 px, k1 = 173). The
Companion refuses such scenes (solve sanity guard). Issue candidate.

## AI Tracking scenes are not relocatable
`build_houdini_scene` writes absolute paths into the HIP, partly with backslashes
(`/obj/NeRF_Import/Scene/Import_Point_Cloud` `file` = `E:\...\<scene>\points3D.ply`,
`Nerfstudio_Animated_Cam` `vm_background` = `E:/.../<scene>/undistort/images_undistorted/frame_$F6.jpg`).
After the AI Tracking folder is moved or renamed, the HIP no longer cooks its point cloud and
the Companion's Maya export fails (FAIL, nothing published). `HOUDINI_PATHMAP` does not map the
backslash form. Found while moving the regression fixtures (GUI implementation, STEP 01); the
fixtures are kept byte-identical and reached through directory junctions at their origin
(`scripts/link_fixture_origins.py`). Record only; `$HIP`-relative paths upstream would fix it.
Issue candidate (user decides).

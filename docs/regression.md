# Regression

Everything in one command (`scripts/run_regression.bat` does the same):
```
python tests/run_all.py [--skip-poc] [--skip-gui]
```
| Suite | Script | Checks |
|---|---|---|
| PoC (TEST 01-03, Revision 01) | `tests/run_poc.py` | lens / camera / Nuke core |
| Workflow | `tests/run_workflow.py` | path resolver guards, mock A / B / C, baseline shot demo |
| Transaction | `tests/test_transaction.py` | stage / validate / publish / rollback |
| Project mode | `tests/test_project_mode.py` | auto detect, plate rules, overrides |
| Partial build | `tests/test_partial_build.py` | `--outputs`, module provenance, backup_keep |
| GUI (headless) | `tests/test_gui.py` | the real GUI driving the real CLI; GUI / CLI parity |
| Baseline compare | `tests/baseline_metrics.py` | every result leaf vs `tests/baselines/v0.1.0.json` |

`v0.1.0.json` holds every numeric / string result leaf (timings, versions, build ids, work
paths and work sizes excluded); numbers must match to 1e-9. New values are allowed.
It was measured on the production baseline shot, so it is **private test data** and not in git:
`<root>/baselines_private/v0.1.0.json`. Without it `run_all` reports the compare as
`NOT RUN` and exits with 3. Paths recorded in the baselines refer to the checkout they were
captured in; set `baseline_capture_repo` in the local config when running from another checkout. The GUI suite reads the shot's expected Check values from
`baseline.expected` in `tests/local_test_config.json` (also private).

Exit codes of `run_all.py` and the v0.2.1 suites: `0` all run and passed, `1` failure,
`3` everything that ran passed but something was NOT RUN (missing private fixture / test data).
Without any test data, `tests/test_release.py` and the fixture-free parts of
`tests/test_v021_fixes.py` / `tests/test_v021_test2.py` still run (the rest is listed as NOT RUN).

## Test data (outside the repository)
Set `COMPANION_TEST_DATA` or copy `tests/local_test_config.example.json` to
`tests/local_test_config.json` (untracked):
```
<root>/poc/        AI Tracking demo output, PoC work / deliveries
<root>/workflow/   mock projects A / B / C and their project configs, scratch work
<root>/baseline/   demo_sh0010 configs + Companion work (the shot's media stay in the project)
<root>/results/    result JSON read by the baseline compare
<root>/baselines_private/  frozen v0.1.0 baselines (production shot measurements; private)
<root>/manual_qc/  archive (no test uses it)
<root>/fixture_origins.json
```
Fixture HIP files contain the absolute paths they were generated at (see
`docs/known_upstream_behavior.md`). After placing the data on a machine run once:
```
python scripts/link_fixture_origins.py
```
It creates directory junctions at those origins (no data, `--remove` deletes them).
`run_all` refuses to start while they are missing.

# Regression

Three suites guard the frozen core. Any builder / GUI change must keep them identical.

| Suite | Command | Needs |
|---|---|---|
| PoC (TEST 01-03, Revision 01) | `python tests/run_poc.py` | hython, mayapy, Nuke, demo data in `test_runs/` |
| Workflow (resolver + mock shots + baseline shot) | `python tests/run_workflow.py` | same + baseline shot data |
| Baseline shot `demo_sh0010` | part of the workflow suite | project data (outside git) |

Compare with the frozen baseline:
```
python tests/baseline_metrics.py capture tests/baselines/candidate.json --extra work/demo_sh0010
python tests/baseline_metrics.py compare tests/baselines/v0.1.0.json tests/baselines/candidate.json
```
`tests/baselines/v0.1.0.json` holds every numeric / string result leaf of the suites
(timings, versions, build ids and work paths excluded); numbers must match to 1e-9.

Test data (`test_runs/`, project folders) is not in git. Data location dependencies are
listed in `reports/v1_implementation_phase01.md`.

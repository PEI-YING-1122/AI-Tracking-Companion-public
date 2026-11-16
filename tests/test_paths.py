"""Where the regression test data lives (outside the repository).

Resolution order:
  1. env COMPANION_TEST_DATA
  2. tests/local_test_config.json  {"test_data_root": "..."}   (machine specific, not tracked)
Nothing falls back to the repository folder: missing configuration is an error.

Layout under the root:
    poc/        AI Tracking demo output + PoC work / delivery folders
    workflow/   mock projects A / B / C, their project configs, scratch work
    baseline/   the production baseline shot (folder named in the local config): shot / project configs, work
    results/    regression result JSON (read by tests/baseline_metrics.py)
    baselines_private/  frozen regression baselines measured on the production baseline shot
                (v0.1.0.json, ...) -- private, never in git; missing -> baseline compare NOT RUN
    manual_qc/  archive (not used by any test)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_CONFIG = os.path.join(HERE, "local_test_config.json")


class TestDataNotConfigured(RuntimeError):
    pass


def root():
    r = os.environ.get("COMPANION_TEST_DATA")
    if not r and os.path.exists(LOCAL_CONFIG):
        r = json.load(open(LOCAL_CONFIG)).get("test_data_root")
    if not r:
        raise TestDataNotConfigured("set COMPANION_TEST_DATA or tests/local_test_config.json "
                                    "(see tests/local_test_config.example.json)")
    r = os.path.abspath(r)
    if not os.path.isdir(r):
        raise TestDataNotConfigured(f"test data root not found: {r}")
    return r


def _join(*parts):
    return os.path.join(root(), *parts).replace("\\", "/")


def poc(*p):
    return _join("poc", *p)


def workflow(*p):
    return _join("workflow", *p)


def baseline(*p):
    return _join("baseline", *p)


def _local():
    return json.load(open(LOCAL_CONFIG)) if os.path.exists(LOCAL_CONFIG) else {}


def baseline_shot():
    """The production baseline shot (names / plate frames from the untracked local config, so the
    repository holds no production names): absolute paths + the shot name."""
    b = _local().get("baseline")
    if not b:
        raise TestDataNotConfigured("tests/local_test_config.json has no 'baseline' section "
                                    "(see tests/local_test_config.example.json)")
    d = baseline(b["dir"])
    return {"shot": b["shot"], "dir": d, "shot_config": f"{d}/{b['shot_config']}",
            "project": f"{d}/projects/{b['project_config']}", "ambiguous_project": f"{d}/projects/{b['ambiguous_project_config']}",
            "work": f"{d}/work/{b['shot']}", "plate_exr": b["plate_exr_frame"], "plate_jpg": b["plate_jpg_frame"],
            "plate_jpg_pattern": b["plate_jpg_pattern"]}


def baseline_expected():
    """Expected Check values of the production baseline shot, from the PRIVATE local config
    (baseline.expected) -- never derived from the output under test, never in git."""
    e = (_local().get("baseline") or {}).get("expected")
    if not e:
        raise TestDataNotConfigured("tests/local_test_config.json has no 'baseline.expected' section "
                                    "(see tests/local_test_config.example.json)")
    return e


def capture_repo():
    """The checkout the frozen baselines were captured in (private 'baseline_capture_repo'): its old
    test_runs / work paths are mapped to the test data root before comparing.  Default: this checkout."""
    return _local().get("baseline_capture_repo") or None


def private_baselines(*p):
    """<test data root>/baselines_private/...: the frozen v0.1.0 regression baselines (private)."""
    return _join("baselines_private", *p)


def aliases():
    """real -> neutral names of the baseline shot (longest first); applied before comparisons"""
    a = _local().get("aliases") or {}
    return sorted(a.items(), key=lambda kv: -len(kv[0]))


def fixture_origins():
    """{origin path written into fixture HIP files: current path} from <root>/fixture_origins.json"""
    p = os.path.join(root(), "fixture_origins.json")
    if not os.path.exists(p):
        return {}
    return {k: _join(*v.split("/")) for k, v in json.load(open(p)).get("origins", {}).items()}


def missing_fixture_links():
    """origins that do not resolve to their fixture (run scripts/link_fixture_origins.py)"""
    return [k for k, v in fixture_origins().items()
            if not (os.path.isdir(k) and os.path.samefile(k, v))]


def results(*p):
    path = _join("results", *p)
    os.makedirs(_join("results"), exist_ok=True)
    return path


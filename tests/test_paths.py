"""Where the regression test data lives (outside the repository).

Resolution order:
  1. env COMPANION_TEST_DATA
  2. tests/local_test_config.json  {"test_data_root": "..."}   (machine specific, not tracked)
Nothing falls back to the repository folder: missing configuration is an error.

Layout under the root:
    poc/        AI Tracking demo output + PoC work / delivery folders
    workflow/   mock projects A / B / C, their project configs, scratch work
    baseline/   demo_sh0010 (V1 production baseline): shot / project configs, Companion work
    results/    regression result JSON (read by tests/baseline_metrics.py)
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


"""One-off: move the regression test data out of the repository.

    python scripts/migrate_test_data.py <test_data_root> [--dry-run]

Moves (rename on the same drive; nothing is copied or deleted):
    test_runs/walking-forest, deliveries, work_*, fixtures, packages  -> <root>/poc/
    test_runs/mock_project_A|B|C, work_resolver, scratch_*            -> <root>/workflow/
    test_runs/results                                                 -> <root>/results/
    work/demo_sh0010 + shots/demo_sh0010.json + shots/projects/demo_project*.json -> <root>/baseline/demo_sh0010/
    shots/projects/mock_*.json                                         -> <root>/workflow/projects/
    manual_qc/                                                         -> <root>/manual_qc/ (archive)
and rewrites the moved configs to paths relative to their own location
({config_dir} / {project_dir}), then writes tests/local_test_config.json.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TR = os.path.join(REPO, "test_runs")


def plan(root, only_existing=True, repo=None):
    """old -> new locations; repo = the checkout the old paths refer to (default: this one)"""
    j = os.path.join
    REPO = repo or globals()["REPO"]  # noqa: N806
    TR = os.path.join(REPO, "test_runs")  # noqa: N806
    moves = []
    for d in ("walking-forest", "deliveries", "work_01_offset", "work_02a", "work_02c", "work_03", "fixtures", "packages"):
        moves.append((j(TR, d), j(root, "poc", d)))
    for d in ("mock_project_A", "mock_project_B", "mock_project_C"):
        moves.append((j(TR, d), j(root, "workflow", d)))
    for d in ("work_resolver", "scratch_projtest"):
        moves.append((j(TR, d), j(root, "workflow", "work", d)))
    moves.append((j(TR, "results"), j(root, "results")))
    b = j(root, "baseline", "demo_sh0010")
    moves.append((j(REPO, "work", "demo_sh0010"), j(b, "work", "demo_sh0010")))
    moves.append((j(REPO, "shots", "demo_sh0010.json"), j(b, "demo_sh0010.json")))
    for f in ("demo_project.project.json", "demo_project.AMBIGUOUS.project.json"):
        moves.append((j(REPO, "shots", "projects", f), j(b, "projects", f)))
    for f in ("mock_B.project.json", "mock_C.project.json"):
        moves.append((j(REPO, "shots", "projects", f), j(root, "workflow", "projects", f)))
    moves.append((j(REPO, "manual_qc"), j(root, "manual_qc")))
    return [(s, d) for s, d in moves if os.path.exists(s) or not only_existing]


def rewrite(root):
    """Configs -> relative to their own folder (relocatable test data)."""
    j = os.path.join
    w = j(root, "workflow")

    def edit(path, fn):
        c = json.load(open(path))
        fn(c)
        json.dump(c, open(path, "w"), indent=1)

    def a(c):
        c["vars"]["project_root"] = "{config_dir}/../.."
        c["vars"]["ai_root"] = "{config_dir}/../../../../poc/walking-forest"
    edit(j(w, "mock_project_A", "pipeline", "configs", "WF_0010.shot.json"), a)
    edit(j(w, "mock_project_B", "configs", "RB_0020.json"), lambda c: c["vars"].__setitem__("proj", "{config_dir}/.."))
    # mock C config already relative ("root": "..")

    def mb(c):
        c["vars"] = {"proj": "{project_dir}/../mock_project_B"}
        c["work_root"] = "{project_dir}/../work/scratch_projtest"
    edit(j(w, "projects", "mock_B.project.json"), mb)

    def mc(c):
        c["vars"] = {"root": "{project_dir}/../mock_project_C/io"}
        c["work_root"] = "{project_dir}/../mock_project_C/io/scratch_projmode"
    edit(j(w, "projects", "mock_C.project.json"), mc)

    b = j(root, "baseline", "demo_sh0010")
    edit(j(b, "demo_sh0010.json"), lambda c: c["outputs"].__setitem__("work_dir", "{config_dir}/work/demo_sh0010"))
    edit(j(b, "projects", "demo_project.project.json"), lambda c: c.__setitem__("work_root", "{project_dir}/../work"))
    edit(j(b, "projects", "demo_project.AMBIGUOUS.project.json"),
         lambda c: c.__setitem__("work_root", "{project_dir}/../../../workflow/work/scratch_projtest"))


def main():
    root = os.path.abspath(sys.argv[1])
    dry = "--dry-run" in sys.argv
    moves = plan(root)
    for s, d in moves:
        print(("would move " if dry else "move ") + f"{s} -> {d}")
        if not dry:
            if os.path.exists(d):
                raise SystemExit(f"target exists, refusing to overwrite: {d}")
            os.makedirs(os.path.dirname(d), exist_ok=True)
            os.rename(s, d)  # same drive: atomic rename, no copy
    if dry:
        return
    rewrite(root)
    with open(os.path.join(root, "README.txt"), "w") as f:
        f.write("AI Tracking Companion regression test data (outside the git repository).\n"
                "poc/ workflow/ baseline/ results/ manual_qc/(archive). See tests/test_paths.py.\n")
    json.dump({"test_data_root": root.replace("\\", "/")},
              open(os.path.join(REPO, "tests", "local_test_config.json"), "w"), indent=1)
    print("done; tests/local_test_config.json written")
    if os.path.isdir(TR) and not os.listdir(TR):
        os.rmdir(TR)


if __name__ == "__main__":
    main()

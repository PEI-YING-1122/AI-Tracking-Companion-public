"""Metadata (frame numbering / fps) and Unsupported-detection tests on synthetic fixtures.

    python test_meta_and_unsupported.py --demo-scene <scene_dir> --work DIR --out result.json

Fixtures are built under --work from copies of the demo scene's small text/JSON
files (never touching the originals) plus tiny generated images.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "common"))
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import companion_meta as cm  # noqa: E402

PY = sys.executable


def make_scene(base, demo_scene, n_frames, registered, cameras_txt=None, tj_patch=None):
    """scene dir + sibling <scene>_transforms.json, like run_autotracker output"""
    scene = os.path.join(base, "out", "shot")
    os.makedirs(os.path.join(scene, "images"), exist_ok=True)
    os.makedirs(os.path.join(scene, "sparse"), exist_ok=True)
    os.makedirs(os.path.join(scene, "undistort"), exist_ok=True)
    tiny = np.zeros((4, 4, 3), np.uint8)
    for k in range(1, n_frames + 1):
        cv2.imwrite(os.path.join(scene, "images", f"frame_{k:06d}.jpg"), tiny)
    src_cams = os.path.join(demo_scene, "sparse", "cameras.txt")
    with open(os.path.join(scene, "sparse", "cameras.txt"), "w") as f:
        f.write(cameras_txt if cameras_txt is not None else open(src_cams).read())
    # real points3D.txt so the solve-sanity guard sees a valid reconstruction
    shutil.copy2(os.path.join(demo_scene, "sparse", "points3D.txt"), os.path.join(scene, "sparse", "points3D.txt"))
    out_root = os.path.dirname(demo_scene)
    tj = json.load(open(os.path.join(out_root, os.path.basename(demo_scene) + "_transforms.json")))
    frame0 = tj["frames"][0]
    tj["frames"] = [dict(frame0, file_path=f"./shot/images/frame_{k:06d}.jpg") for k in registered]
    if tj_patch:
        tj_patch(tj)
    json.dump(tj, open(os.path.join(base, "out", "shot_transforms.json"), "w"))
    uj = json.load(open(os.path.join(demo_scene, "undistort", "transforms_undistorted.json")))
    json.dump(uj, open(os.path.join(scene, "undistort", "transforms_undistorted.json"), "w"))
    return scene


def make_seq(d, names, w=64, h=36, exr=False):
    os.makedirs(d, exist_ok=True)
    for n in names:
        img = np.full((h, w, 3), 0.5 if exr else 128, np.float32 if exr else np.uint8)
        cv2.imwrite(os.path.join(d, n), img)


def run_delivery_tools(meta_path, outdir):
    """Both delivery tools must refuse (exit 2) and write nothing."""
    r1 = subprocess.run([PY, os.path.join(ROOT, "stmap", "stmap_generator.py"), "--meta", meta_path,
                         "--out-dir", os.path.join(outdir, "stmap")], capture_output=True, text=True)
    r2 = subprocess.run([PY, os.path.join(ROOT, "maya_export", "run_maya_export.py"), "--meta", meta_path,
                         "--hip", meta_path, "--out-dir", os.path.join(outdir, "maya")], capture_output=True, text=True)
    return {"stmap_rc": r1.returncode, "stmap_msg": (r1.stdout + r1.stderr).strip()[-300:],
            "maya_rc": r2.returncode, "maya_msg": (r2.stdout + r2.stderr).strip()[-300:],
            "outputs_created": os.path.exists(os.path.join(outdir, "stmap")) or os.path.exists(os.path.join(outdir, "maya"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-scene", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.path.exists(a.work):
        shutil.rmtree(a.work)
    res = {}

    # 1) JPG sequence numbered 1001-1010, COLMAP registered tracking frames 2..9
    b = os.path.join(a.work, "jpg_seq")
    make_seq(os.path.join(b, "src", "shot"), [f"shot.{n}.jpg" for n in range(1001, 1011)])
    scene = make_scene(b, a.demo_scene, 10, range(2, 10))
    m = cm.build_meta(scene, os.path.join(b, "src", "shot"))
    res["jpg_sequence"] = {"source": {k: m["source"][k] for k in ("kind", "width", "height", "fps", "fps_source",
                                                                   "source_first_frame", "source_last_frame")},
                           "tracking": m["tracking"], "support": m["support"]}

    # 2) EXR sequence 0101-0108 (one frame missing in numbering) -- contiguous files, gap in numbers
    b = os.path.join(a.work, "exr_seq_gap")
    make_seq(os.path.join(b, "src", "plate"), [f"plate_{n:04d}.exr" for n in (101, 102, 103, 105, 106, 107, 108, 109)], exr=True)
    scene = make_scene(b, a.demo_scene, 8, range(1, 9))
    m = cm.build_meta(scene, os.path.join(b, "src", "plate"))
    res["exr_sequence_numbering_gap"] = {"source": {k: m["source"][k] for k in ("kind", "fps_source", "source_first_frame", "source_last_frame")},
                                         "tracking": {k: m["tracking"][k] for k in ("frame_offset_tracking_to_source", "source_frame_of_tracking_first", "source_frame_of_tracking_last")},
                                         "support": m["support"]}

    # 3) EXR count != extracted frames (autotracker skipped an unreadable EXR) -> Unsupported
    b = os.path.join(a.work, "exr_seq_skipped")
    make_seq(os.path.join(b, "src", "plate"), [f"plate_{n:04d}.exr" for n in range(1, 9)], exr=True)
    scene = make_scene(b, a.demo_scene, 7, range(1, 8))
    m = cm.build_meta(scene, os.path.join(b, "src", "plate"))
    res["exr_sequence_count_mismatch"] = {"support": m["support"]}

    video = None
    import site_config
    for base, _, files in os.walk(os.path.join(site_config.get("upstream_repo"), "demo-test")):
        for f in files:
            if f.lower().endswith(".mp4"):
                video = os.path.join(base, f)

    # 4) fisheye model in cameras.txt -> Unsupported; delivery tools must refuse
    b = os.path.join(a.work, "fisheye")
    cams = "# fixture\n1 OPENCV_FISHEYE 360 640 293.6 293.6 180 320 0.01 0.0 0.0 0.0\n"
    scene = make_scene(b, a.demo_scene, 5, range(1, 6), cameras_txt=cams,
                       tj_patch=lambda tj: tj.update(is_fisheye=True))
    m = cm.build_meta(scene, video)
    mp = os.path.join(b, "meta.json")
    json.dump(m, open(mp, "w"))
    res["fisheye"] = {"support": m["support"], "tools": run_delivery_tools(mp, os.path.join(b, "delivery"))}

    # 5) multi-cams: two COLMAP cameras, no top-level intrinsics -> Unsupported
    b = os.path.join(a.work, "multicams")
    cams = ("1 SIMPLE_RADIAL 360 640 293.6 180 320 -0.09\n"
            "2 SIMPLE_RADIAL 360 640 300.0 180 320 -0.05\n")

    def strip(tj):
        for k in ("fl_x", "fl_y", "cx", "cy", "w", "h", "k1", "k2", "k3", "k4", "p1", "p2"):
            tj.pop(k, None)
    scene = make_scene(b, a.demo_scene, 5, range(1, 6), cameras_txt=cams, tj_patch=strip)
    m = cm.build_meta(scene, video)
    mp = os.path.join(b, "meta.json")
    json.dump(m, open(mp, "w"))
    res["multicams"] = {"support": m["support"], "tools": run_delivery_tools(mp, os.path.join(b, "delivery"))}

    # 6) defence in depth: meta hand-edited to "supported" but JSON is fisheye
    b = os.path.join(a.work, "fisheye_meta_forced")
    scene = make_scene(b, a.demo_scene, 5, range(1, 6), tj_patch=lambda tj: tj.update(is_fisheye=True))
    m = cm.build_meta(scene, video)
    m["support"] = {"supported": True, "reasons": [], "warnings": ["forced by test"]}
    mp = os.path.join(b, "meta.json")
    json.dump(m, open(mp, "w"))
    r = subprocess.run([PY, os.path.join(ROOT, "stmap", "stmap_generator.py"), "--meta", mp,
                        "--out-dir", os.path.join(b, "delivery", "stmap")], capture_output=True, text=True)
    res["fisheye_meta_forced"] = {"stmap_rc": r.returncode, "msg": (r.stdout + r.stderr).strip()[-200:],
                                  "outputs_created": os.path.exists(os.path.join(b, "delivery", "stmap"))}

    json.dump(res, open(a.out, "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

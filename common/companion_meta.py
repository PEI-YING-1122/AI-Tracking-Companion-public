"""Companion metadata for an AI Tracking (colmap-camera-tracking) scene.

Reads ONLY: the AI Tracking scene outputs and the original source media.
Writes ONLY: the JSON path the caller passes (always under AI_Tracking_Companion).

Usage:
    python companion_meta.py --scene-dir <out>/<scene> --source <video|seq dir> --out meta.json
"""
import argparse
import fractions
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SCHEMA = "ai_tracking_companion.meta/1"
DEFAULT_FPS = 24.0
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".mxf", ".m4v"}  # same set as autotracker.py

# Models colmap2nerf.py parses as plain perspective. Anything else is either a
# fisheye (undistortionNerfstudioColmap silently treats it as perspective) or a
# model colmap2nerf drops distortion for ("Unknown camera model").
PERSPECTIVE_MODELS = {"SIMPLE_PINHOLE", "PINHOLE", "SIMPLE_RADIAL", "RADIAL", "OPENCV"}
FISHEYE_MODELS = {"SIMPLE_RADIAL_FISHEYE", "RADIAL_FISHEYE", "OPENCV_FISHEYE",
                  "THIN_PRISM_FISHEYE", "RAD_TAN_THIN_PRISM_FISHEYE", "FOV"}

FRAME_RE = re.compile(r"(\d+)")


class UnsupportedScene(Exception):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def frame_number(path):
    """Last digit group of the file stem (frame_000123.jpg -> 123, shot.1001.exr -> 1001)."""
    nums = FRAME_RE.findall(os.path.splitext(os.path.basename(path))[0])
    return int(nums[-1]) if nums else None


def find_ffprobe():
    """site config 'ffprobe' first, then PATH."""
    try:
        import site_config
        return site_config.get("ffprobe")
    except (KeyError, FileNotFoundError, ImportError):
        pass
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    raise FileNotFoundError("ffprobe not found (site config 'ffprobe' or PATH)")


def probe_video(path):
    cmd = [find_ffprobe(), "-v", "error", "-select_streams", "v:0", "-count_packets",
           "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,nb_read_packets:stream_tags=timecode:format_tags=timecode",
           "-of", "json", path]
    info = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)
    st = info["streams"][0]
    rate = st.get("r_frame_rate") or st.get("avg_frame_rate")
    fr = fractions.Fraction(rate) if rate and rate != "0/0" else None
    nb = st.get("nb_read_packets") or st.get("nb_frames")
    tc = (st.get("tags") or {}).get("timecode") or ((info.get("format") or {}).get("tags") or {}).get("timecode")
    return {
        "width": int(st["width"]),
        "height": int(st["height"]),
        "fps": float(fr) if fr else DEFAULT_FPS,
        "fps_rational": f"{fr.numerator}/{fr.denominator}" if fr else None,
        "fps_source": "ffprobe" if fr else "default",
        "frame_count": int(nb) if nb else None,
        "timecode": tc,
    }


def _list_seq(d):
    files = sorted(os.path.join(d, n) for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)))
    exr = [f for f in files if f.lower().endswith(".exr")]
    jpg = [f for f in files if os.path.splitext(f)[1].lower() in (".jpg", ".jpeg")]
    if exr:  # same precedence as autotracker._sequence_kind
        return "exr_sequence", exr
    if jpg:
        return "jpg_sequence", jpg
    return None, []


def exr_header_fps(path):
    """framesPerSecond (rational) from an OpenEXR header, or None."""
    import struct
    try:
        with open(path, "rb") as f:
            data = f.read(1 << 20)
        if struct.unpack("<I", data[:4])[0] != 20000630:
            return None
        i = 8
        while data[i] != 0:
            n = data.index(b"\x00", i); name = data[i:n].decode("latin-1"); i = n + 1
            n = data.index(b"\x00", i); typ = data[i:n].decode("latin-1"); i = n + 1
            size = struct.unpack("<I", data[i:i + 4])[0]; i += 4
            if name == "framesPerSecond" and typ == "rational":
                num, den = struct.unpack("<iI", data[i:i + 8])
                return fractions.Fraction(num, den) if den else None
            i += size
    except (OSError, ValueError, struct.error, IndexError):
        return None
    return None


def probe_sequence(d):
    import cv2  # OPENCV_IO_ENABLE_OPENEXR set by caller
    kind, files = _list_seq(d)
    if not files:
        raise UnsupportedScene(f"No EXR/JPG frames in {d}")
    img = cv2.imread(files[0], cv2.IMREAD_UNCHANGED)
    if img is None:
        raise UnsupportedScene(f"Cannot read first source frame {files[0]}")
    nums = [frame_number(f) for f in files]
    fr = exr_header_fps(files[0]) if kind == "exr_sequence" else None
    return kind, files, {
        "width": int(img.shape[1]),
        "height": int(img.shape[0]),
        "fps": float(fr) if fr else DEFAULT_FPS,
        "fps_rational": f"{fr.numerator}/{fr.denominator}" if fr else None,
        # source metadata first; the caller may still apply a project fps, then default 24
        "fps_source": "exr_header" if fr else "default",
        "frame_count": len(files),
        "frame_numbers_parsed": all(n is not None for n in nums),
        "_nums": nums,
    }


def read_cameras_txt(path):
    cams = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            e = line.split()
            cams.append({"id": int(e[0]), "model": e[1], "width": int(e[2]), "height": int(e[3]),
                         "params": [float(x) for x in e[4:]]})
    return cams


def build_meta(scene_dir, source, transforms_json=None, undist_json=None):
    import cv2  # noqa: F401  (needed by probe_sequence)
    scene_dir = os.path.abspath(scene_dir)
    scene = os.path.basename(scene_dir)
    out_root = os.path.dirname(scene_dir)
    transforms_json = transforms_json or os.path.join(out_root, f"{scene}_transforms.json")
    undist_json = undist_json or os.path.join(scene_dir, "undistort", "transforms_undistorted.json")
    reasons, warnings = [], []

    # --- camera model / multi-cam detection -------------------------------------
    cams_txt = os.path.join(scene_dir, "sparse", "cameras.txt")
    cams = read_cameras_txt(cams_txt) if os.path.exists(cams_txt) else []
    if not cams:
        reasons.append(f"cameras.txt missing or empty: {cams_txt}")
    if len(cams) > 1:
        reasons.append(f"multi-cams: {len(cams)} COLMAP cameras (Unsupported)")
    for c in cams:
        if c["model"] in FISHEYE_MODELS:
            reasons.append(f"fisheye camera model {c['model']} (Unsupported)")
        elif c["model"] not in PERSPECTIVE_MODELS:
            reasons.append(f"camera model {c['model']} not parsed by colmap2nerf (distortion would be lost)")

    with open(transforms_json) as f:
        tj = json.load(f)

    # --- solve sanity: AI Tracking reports success whenever sparse/0/cameras.bin exists,
    # even if COLMAP's bundle adjustment had no 3D points (seen on rehearsal shot B).
    pts_txt = os.path.join(scene_dir, "sparse", "points3D.txt")
    n_pts = 0
    if os.path.exists(pts_txt):
        with open(pts_txt) as f:
            n_pts = sum(1 for line in f if line.strip() and not line.startswith("#"))
    if n_pts == 0:
        reasons.append("failed reconstruction: COLMAP produced 0 3D points")
    if len(tj.get("frames", [])) < 2:
        reasons.append(f"failed reconstruction: {len(tj.get('frames', []))} registered frames")
    if "fl_x" in tj and "w" in tj:
        fx_over_w = float(tj["fl_x"]) / float(tj["w"])
        if not 0.05 <= fx_over_w <= 20.0:  # ~168 deg .. ~2.9 deg horizontal FOV
            reasons.append(f"implausible calibration: fx/w = {fx_over_w:.4g} (focal {tj['fl_x']:.4g}px on {tj['w']:.0f}px)")
        bad = {k: tj.get(k, 0.0) for k in ("k1", "k2") if abs(float(tj.get(k, 0.0))) > 1.0}
        bad.update({k: tj.get(k, 0.0) for k in ("p1", "p2") if abs(float(tj.get(k, 0.0))) > 0.1})
        if bad:
            reasons.append(f"implausible calibration: distortion {bad}")
    if "fl_x" not in tj:
        reasons.append("transforms.json has no top-level intrinsics (multi-cams layout)")
    if tj.get("is_fisheye"):
        reasons.append("transforms.json is_fisheye=true (Unsupported)")
    if not os.path.exists(undist_json):
        reasons.append(f"transforms_undistorted.json missing: {undist_json}")

    # --- source media ------------------------------------------------------------
    source = os.path.abspath(source)
    if os.path.isfile(source) and os.path.splitext(source)[1].lower() in VIDEO_EXTS:
        kind = "video"
        src = probe_video(source)
        src_files, src_nums = None, None
    elif os.path.isdir(source):
        kind, src_files, src = probe_sequence(source)
        src_nums = src.pop("_nums")
    else:
        raise UnsupportedScene(f"Unrecognised source: {source}")

    # --- tracking frames (autotracker renumbers to frame_%06d starting at 1) ------
    img_dir = os.path.join(scene_dir, "images")
    extracted = sorted(glob.glob(os.path.join(img_dir, "frame_*.jpg")))
    reg = sorted(frame_number(fr["file_path"]) for fr in tj.get("frames", []))
    if not reg:
        reasons.append("no registered frames in transforms.json")
    n_ext = len(extracted)
    missing = sorted(set(range(1, n_ext + 1)) - set(reg)) if n_ext else []

    # tracking index k (1-based)  ->  source frame number
    if kind == "video":
        # FFmpeg decodes every frame; frame_000001 == first decoded frame.
        # Videos have no file frame numbers: use 1-based decode index.
        tracking_to_source = lambda k: k  # noqa: E731
        numbering = "video_decode_index_1based"
        src_first, src_last = 1, src["frame_count"] or n_ext
        if src["frame_count"] and src["frame_count"] != n_ext:
            warnings.append(f"ffprobe frame count {src['frame_count']} != extracted {n_ext}")
    else:
        numbering = "source_filename"
        if not src.get("frame_numbers_parsed"):
            reasons.append("cannot parse frame numbers from source filenames")
            tracking_to_source = lambda k: None  # noqa: E731
            src_first = src_last = None
        else:
            src_first, src_last = min(src_nums), max(src_nums)
            gaps = sorted(set(range(src_first, src_last + 1)) - set(src_nums))
            if gaps:
                warnings.append(f"source numbering has {len(gaps)} gaps (first: {gaps[:10]})")
            if len(src_files) != n_ext:
                # autotracker silently skips unreadable EXRs without leaving a hole,
                # so index k no longer identifies a source file.
                reasons.append(f"source frames {len(src_files)} != extracted {n_ext}: frame mapping ambiguous")
            tracking_to_source = lambda k: src_nums[k - 1] if 1 <= k <= len(src_nums) else None  # noqa: E731

    proxy_w, proxy_h = (int(tj["w"]), int(tj["h"])) if "w" in tj else (None, None)
    meta = {
        "schema": SCHEMA,
        "scene_name": scene,
        "scene_dir": scene_dir,
        "transforms_json": transforms_json,
        "transforms_undistorted_json": undist_json,
        "source": {"path": source, "kind": kind, "frame_numbering": numbering,
                   "source_first_frame": src_first, "source_last_frame": src_last, **src},
        "tracking": {
            "proxy_width": proxy_w, "proxy_height": proxy_h,
            "scale_x": proxy_w / src["width"] if proxy_w else None,
            "scale_y": proxy_h / src["height"] if proxy_h else None,
            "extracted_frames": n_ext,
            "registered_frames": len(reg),
            "tracking_first_frame": reg[0] if reg else None,
            "tracking_last_frame": reg[-1] if reg else None,
            "unregistered_frames": missing,
            "source_frame_of_tracking_first": tracking_to_source(reg[0]) if reg else None,
            "source_frame_of_tracking_last": tracking_to_source(reg[-1]) if reg else None,
            "frame_offset_tracking_to_source": (tracking_to_source(1) - 1) if tracking_to_source(1) is not None else None,
        },
        "camera": {"colmap_cameras": cams, "is_fisheye": bool(tj.get("is_fisheye", False)), "points3d": n_pts},
        "support": {"supported": not reasons, "reasons": reasons, "warnings": warnings},
    }
    if kind != "video" and meta["support"]["supported"]:
        nums_t = [tracking_to_source(k) for k in range(1, n_ext + 1)]
        if nums_t != list(range(nums_t[0], nums_t[0] + n_ext)):
            # a constant tracking->source offset would silently mis-key every frame after the gap
            reasons.append("source numbering not contiguous: constant frame offset invalid (Unsupported)")
            meta["support"]["supported"] = False
    return meta


def require_supported(meta):
    """Raise UnsupportedScene when delivery must not be produced."""
    if not meta["support"]["supported"]:
        raise UnsupportedScene("; ".join(meta["support"]["reasons"]))


def main():
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene-dir", required=True)
    ap.add_argument("--source", required=True, help="Original video file or image-sequence directory")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    meta = build_meta(a.scene_dir, a.source)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps({k: meta[k] for k in ("source", "tracking", "support")}, indent=2))
    if not meta["support"]["supported"]:
        print("UNSUPPORTED:", "; ".join(meta["support"]["reasons"]), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

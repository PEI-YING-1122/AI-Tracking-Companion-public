"""Auto detection from an AI Tracking folder + project rules.

AI Tracking does not record the source plate path, so the plate is found by
search rules and validated with cheap checks first:

  1. project search rules, in priority order (first rule with validated candidates wins)
  2. frame count == frames AI Tracking extracted
  3. resolution / aspect consistent with the tracking images (header-only reads)
  4. filename / frame-range pattern (single padded, contiguous sequence)
  5. image-content verification -- ONLY if several candidates of the same rule survive

  1 candidate  -> auto select        0 -> BLOCKED        several -> Artist override required
"""
import glob
import os
import re
import struct
import subprocess

import project_config

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".mxf", ".m4v"}
IMAGE_EXTS = {".exr", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dpx"}
SEQ_RE = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")
NCC_MIN = 0.90


# ------------------------------------------------------------------ scene
def find_scenes(folder):
    """AI Tracking scenes: dirs with sparse/0/cameras.bin and a sibling <name>_transforms.json."""
    folder = os.path.abspath(folder)

    def is_scene(d):
        return os.path.exists(os.path.join(d, "sparse", "0", "cameras.bin")) and \
            os.path.exists(os.path.join(os.path.dirname(d), os.path.basename(d) + "_transforms.json"))
    if is_scene(folder):
        return [folder]
    return sorted(os.path.join(folder, d) for d in os.listdir(folder)
                  if os.path.isdir(os.path.join(folder, d)) and is_scene(os.path.join(folder, d)))


def tracking_facts(scene_dir):
    imgs = sorted(glob.glob(os.path.join(scene_dir, "images", "frame_*.jpg")))
    w = h = None
    if imgs:
        w, h = image_size(imgs[0])
    return {"extracted_frames": len(imgs), "tracking_resolution": [w, h], "first_image": imgs[0] if imgs else None,
            "images": imgs, "scene_dir": os.path.abspath(scene_dir)}


# ------------------------------------------------------------------ cheap header reads
def _exr_size(path):
    with open(path, "rb") as f:
        data = f.read(1 << 16)
    if struct.unpack("<I", data[:4])[0] != 20000630:
        return None
    i = 8
    while data[i] != 0:
        n = data.index(b"\x00", i); name = data[i:n]; i = n + 1
        n = data.index(b"\x00", i); typ = data[i:n]; i = n + 1
        size = struct.unpack("<I", data[i:i + 4])[0]; i += 4
        if name == b"dataWindow" and typ == b"box2i":
            x0, y0, x1, y1 = struct.unpack("<iiii", data[i:i + 16])
            return x1 - x0 + 1, y1 - y0 + 1
        i += size
    return None


def _jpeg_size(path):
    with open(path, "rb") as f:
        data = f.read(1 << 18)
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg
    return None


def image_size(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".exr":
            s = _exr_size(path)
        elif ext in (".jpg", ".jpeg"):
            s = _jpeg_size(path)
        else:
            s = None
        if s:
            return s
    except (OSError, struct.error, ValueError, IndexError):
        pass
    import cv2  # fallback: full decode (rare formats only)
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return (img.shape[1], img.shape[0]) if img is not None else (None, None)


def video_info(path, ffprobe):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=width,height,nb_read_packets", "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        w, h, n = (int(x) for x in r.stdout.strip().split(","))
        return w, h, n
    except ValueError:
        return None, None, None


# ------------------------------------------------------------------ candidates
def _glob_pattern(p):
    return re.sub(r"#+|%0?\d*d", "*", p)


def _sequences(files):
    """group files into padded sequences -> {key: (pattern, [(num, path)])}"""
    seqs = {}
    for f in files:
        m = SEQ_RE.match(os.path.basename(f))
        if not m or os.path.splitext(f)[1].lower() not in IMAGE_EXTS:
            continue
        pre, num, ext = m.groups()
        key = (os.path.dirname(f), pre, len(num), ext.lower())
        seqs.setdefault(key, []).append((int(num), f))
    out = []
    for (d, pre, pad, ext), items in seqs.items():
        items.sort()
        out.append({"kind": "sequence", "pattern": os.path.join(d, f"{pre}%0{pad}d{os.path.splitext(items[0][1])[1]}").replace("\\", "/"),
                    "dir": d.replace("\\", "/"), "frames": [n for n, _ in items], "files": [p for _, p in items]})
    return out


def candidates_for_rule(pattern):
    files = [f for f in glob.glob(_glob_pattern(pattern)) if os.path.isfile(f)]
    vids = [{"kind": "video", "pattern": f.replace("\\", "/"), "files": [f]} for f in files
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
    return _sequences(files) + vids


def _inside(path, folder):
    a = os.path.normcase(os.path.abspath(path))
    b = os.path.normcase(os.path.abspath(folder)).rstrip("\/")
    return a == b or a.startswith(b + os.sep)


def cheap_check(c, facts, ffprobe=None):
    """frame count, contiguity, resolution / aspect.  Returns (ok, reasons, info)."""
    reasons, info = [], {}
    if facts.get("scene_dir") and _inside(c["files"][0], facts["scene_dir"]):
        # AI Tracking's own extracted / undistorted frames match perfectly but are not the plate
        return False, ["inside the AI Tracking scene folder (working images, not a source plate)"], info
    n_need = facts["extracted_frames"]
    tw, th = facts["tracking_resolution"]
    if c["kind"] == "video":
        w, h, n = video_info(c["files"][0], ffprobe) if ffprobe else (None, None, None)
        info.update(width=w, height=h, frames=n)
    else:
        fr = c["frames"]
        n = len(fr)
        info.update(frames=n, first=fr[0], last=fr[-1])
        if fr != list(range(fr[0], fr[0] + n)):
            reasons.append("frame numbering not contiguous")
        w, h = image_size(c["files"][0])
        info.update(width=w, height=h)
    if n != n_need:
        reasons.append(f"frame count {n} != tracking {n_need}")
    if not w or not h:
        reasons.append("resolution unreadable")
    elif tw and th:
        if abs(w / h - tw / th) > 0.01 * (tw / th):
            reasons.append(f"aspect {w}x{h} != tracking {tw}x{th}")
        elif w < tw:
            reasons.append(f"resolution {w}x{h} smaller than tracking {tw}x{th}")
        else:
            s = tw / w
            if abs(round(h * s) - th) > 1:
                reasons.append(f"tracking {tw}x{th} is not a uniform scale of {w}x{h}")
            info["scale"] = s
    return not reasons, reasons, info


def _gray_small(img, width=256):
    import cv2
    import numpy as np
    if img.dtype != np.uint8:  # float (EXR) -> display-ish so it compares with the sRGB tracking JPGs
        img = np.clip(img[..., :3] if img.ndim == 3 else img, 0, 1)
        img = (np.where(img <= 0.0031308, img * 12.92, 1.055 * np.power(img, 1 / 2.4) - 0.055) * 255).astype(np.uint8)
    g = cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h = int(round(g.shape[0] * width / g.shape[1]))
    g = cv2.resize(g, (width, h), interpolation=cv2.INTER_AREA).astype(np.float64)
    return (g - g.mean()) / (g.std() + 1e-9)


def content_check(c, facts):
    """NCC of first / middle / last frames vs the AI Tracking images (only when ambiguous)."""
    import os as _os
    _os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    import cv2
    import numpy as np
    n = facts["extracted_frames"]
    idx = sorted({0, n // 2, n - 1})
    scores = []
    for i in idx:
        trk = cv2.imread(facts["images"][i], cv2.IMREAD_UNCHANGED)
        if c["kind"] == "video":
            cap = cv2.VideoCapture(c["files"][0])
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, src = cap.read()
            cap.release()
            if not ok:
                return 0.0
        else:
            src = cv2.imread(c["files"][i], cv2.IMREAD_UNCHANGED)
        a, b = _gray_small(trk), _gray_small(src)
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]))
        scores.append(float((a * b).mean()))
    return min(scores) if scores else 0.0


def resolve_plate(project, tokens, facts, ffprobe=None, override=None):
    """-> dict(status in auto|override|ambiguous|none|override_invalid, selected, candidates, rule)"""
    if override:
        c = _candidate_from_path(override)
        ok, reasons, info = cheap_check(c, facts, ffprobe) if c else (False, ["override path not found"], {})
        return {"status": "override" if ok else "override_invalid", "selected": c["pattern"] if (c and ok) else None,
                "candidates": [{"pattern": override, "ok": ok, "reasons": reasons, **info}], "rule": "artist_override"}
    report = []
    for ri, rule in enumerate(project.get("plate_search") or []):
        pat = project_config.substitute(rule, tokens, f"plate_search[{ri}]")
        cands = candidates_for_rule(pat)
        passed = []
        for c in cands:
            ok, reasons, info = cheap_check(c, facts, ffprobe)
            report.append({"rule": ri, "pattern": c["pattern"], "ok": ok, "reasons": reasons, **info})
            if ok:
                passed.append(c)
        if len(passed) == 1:
            return {"status": "auto", "selected": passed[0]["pattern"], "candidates": report, "rule": ri,
                    "content_check": False}
        if len(passed) > 1:  # only now pay for image reads
            for c in passed:
                c["ncc"] = content_check(c, facts)
            for r in report:
                for c in passed:
                    if r["pattern"] == c["pattern"]:
                        r["ncc"] = c["ncc"]
            good = [c for c in passed if c["ncc"] >= NCC_MIN]
            if len(good) == 1:
                return {"status": "auto", "selected": good[0]["pattern"], "candidates": report, "rule": ri,
                        "content_check": True}
            return {"status": "ambiguous", "selected": None, "candidates": report, "rule": ri, "content_check": True}
    return {"status": "none", "selected": None, "candidates": report, "rule": None}


def _candidate_from_path(p):
    p = p.replace("\\", "/")
    if os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO_EXTS:
        return {"kind": "video", "pattern": p, "files": [p]}
    if os.path.isfile(p) and os.path.splitext(p)[1].lower() in IMAGE_EXTS:  # one frame picked in a file dialog
        m = SEQ_RE.match(os.path.basename(p))
        if m:
            p = os.path.join(os.path.dirname(p), m.group(1) + "#" * len(m.group(2)) + m.group(3)).replace("\\", "/")
    if re.search(r"#+|%0?\d*d", os.path.basename(p)):
        seqs = _sequences([f for f in glob.glob(_glob_pattern(p)) if os.path.isfile(f)])
    elif os.path.isdir(p):
        seqs = _sequences([f for f in glob.glob(os.path.join(p, "*")) if os.path.isfile(f)])
    else:
        seqs = []
    return seqs[0] if len(seqs) == 1 else None


def suggest_shot_name(regex, *texts):
    if not regex:
        return None
    for t in texts:
        m = re.search(regex, t or "")
        if m:
            return m.group(1) if m.groups() else m.group(0)
    return None

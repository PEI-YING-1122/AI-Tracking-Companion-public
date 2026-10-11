"""STMap core: reproduces AI Tracking's undistortion geometry, in float precision.

Parameter parsing mirrors undistortionNerfstudioColmap.undistort_process line for
line (same keys, same defaults, same D order).  The expanded-canvas rule is NOT
re-implemented: compute_undistorted_canvas is loaded straight from the upstream
file (read-only, no bytecode written into the upstream repo; location from the
site config key 'upstream_repo').

Two canvases (Revision 01):
  * tracking space (proxy) -- canvas(cam, solver="legacy") calls the upstream
    compute_undistorted_canvas unchanged: reproduces images_undistorted / HIP.
  * production space (full res) -- canvas(cam, solver="converged"): the same
    rule (50 samples per edge, bbox incl. the original range, ceil+1,
    pp = c - min) but with the converged inverse, so every plate pixel lands
    inside the canvas (no black corners after redistort).

Pixel convention used for maps: OpenCV index coordinates (pixel i spans
[i-0.5, i+0.5]), with the COLMAP cx/cy fed to OpenCV unchanged -- exactly what
upstream does, so STMap output matches images_undistorted.

STMap convention (validated in real Nuke, TEST 02A):
    U = (col + 0.5) / W
    V = 1 - (row + 0.5) / H      row = top-origin image row (OpenCV / numpy)
    V = (y_nuke + 0.5) / H       same thing in Nuke's bottom-origin pixel coords
Nuke applies no further Y flip.  Never plug a top-origin row into the y_nuke form.
"""
import hashlib
import importlib.util
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")  # must precede `import cv2`
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import site_config  # noqa: E402

UPSTREAM_DIR = site_config.get("upstream_repo")
UPSTREAM_UNDISTORT = os.path.join(UPSTREAM_DIR, "undistortionNerfstudioColmap.py")


def _load_upstream():
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # never write __pycache__ into the READ ONLY repo
    try:
        spec = importlib.util.spec_from_file_location("_upstream_undistort", UPSTREAM_UNDISTORT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


upstream = _load_upstream()


def upstream_sha256():
    with open(UPSTREAM_UNDISTORT, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Camera:
    """Intrinsics exactly as undistort_process reads them from *_transforms.json."""

    def __init__(self, data):
        self.camera_model = data.get("camera_model", "OPENCV")
        self.is_fisheye = bool(data.get("is_fisheye", False))
        self.w = int(data.get("w", 1920))
        self.h = int(data.get("h", 1080))
        self.fl_x = float(data.get("fl_x", 1000))
        self.fl_y = float(data.get("fl_y", self.fl_x))
        self.cx = float(data.get("cx", self.w / 2))
        self.cy = float(data.get("cy", self.h / 2))
        self.k1 = float(data.get("k1", 0.0))
        self.k2 = float(data.get("k2", 0.0))
        self.k3 = float(data.get("k3", 0.0))
        self.k4 = float(data.get("k4", 0.0))
        self.p1 = float(data.get("p1", 0.0))
        self.p2 = float(data.get("p2", 0.0))

    @property
    def K(self):
        return np.array([[self.fl_x, 0, self.cx], [0, self.fl_y, self.cy], [0, 0, 1]], dtype=np.float64)

    @property
    def D(self):
        # OpenCV order k1 k2 p1 p2 k3 k4 (k5 k6 = 0), as upstream
        return np.array([self.k1, self.k2, self.p1, self.p2, self.k3, self.k4, 0.0, 0.0], dtype=np.float64)

    def scaled(self, W, H):
        """Same lens at a different plate resolution: scale fx fy cx cy, keep k/p."""
        c = Camera.__new__(Camera)
        c.__dict__.update(self.__dict__)
        sx, sy = W / self.w, H / self.h
        c.w, c.h = int(W), int(H)
        c.fl_x, c.fl_y = self.fl_x * sx, self.fl_y * sy
        c.cx, c.cy = self.cx * sx, self.cy * sy
        return c

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items()}


def unsupported_reason(cam, data):
    if cam.camera_model == "OPENCV_FISHEYE" or cam.is_fisheye:
        return "fisheye camera model (Unsupported)"
    if "fl_x" not in data:
        return "no top-level intrinsics (multi-cams layout, Unsupported)"
    return None


CANVAS_SOLVERS = ("legacy", "converged")
CONVERGED_CRITERIA = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 200, 1e-12)


def canvas(cam, crop=False, solver="legacy"):
    """(new_w, new_h, new_cx, new_cy).

    legacy    = upstream compute_undistorted_canvas itself (tracking space).
    converged = identical rule, converged inverse (production space)."""
    if crop:
        return cam.w, cam.h, cam.cx, cam.cy
    if solver == "legacy":
        _, _, nw, nh, ncx, ncy = upstream.compute_undistorted_canvas(cam.w, cam.h, cam.K, cam.D)
        return nw, nh, ncx, ncy
    if solver != "converged":
        raise ValueError(solver)
    w, h, K, D = cam.w, cam.h, cam.K, cam.D
    pts = []
    for t in np.linspace(0, 1, 50):            # same sampling as upstream
        pts.extend([[t * (w - 1), 0], [t * (w - 1), h - 1], [0, t * (h - 1)], [w - 1, t * (h - 1)]])
    pts = np.array(pts, dtype=np.float64).reshape(-1, 1, 2)
    u = cv2.undistortPointsIter(pts, K, D, None, K, CONVERGED_CRITERIA).reshape(-1, 2)
    x_min = min(0.0, float(u[:, 0].min()))
    y_min = min(0.0, float(u[:, 1].min()))
    x_max = max(float(w - 1), float(u[:, 0].max()))
    y_max = max(float(h - 1), float(u[:, 1].max()))
    nw = int(np.ceil(x_max - x_min)) + 1
    nh = int(np.ceil(y_max - y_min)) + 1
    return nw, nh, float(K[0, 2]) - x_min, float(K[1, 2]) - y_min


def new_K(cam, ncx, ncy):
    return np.array([[cam.fl_x, 0, ncx], [0, cam.fl_y, ncy], [0, 0, 1]], dtype=np.float64)


def undistort_map(cam, nw, nh, ncx, ncy):
    """For each undistorted-canvas pixel: where to sample the distorted plate.
    Identical call to upstream (CV_32FC1)."""
    m1, m2 = cv2.initUndistortRectifyMap(cam.K, cam.D, None, new_K(cam, ncx, ncy), (nw, nh), cv2.CV_32FC1)
    return m1, m2


REDISTORT_SOLVERS = ("converged", "legacy")


def redistort_map(cam, ncx, ncy, solver="converged"):
    """For each distorted-plate pixel: where to sample the undistorted canvas.

    solver="converged" (production default, decision after TEST 02): same lens
      model, inverse solved with undistortPointsIter to 1e-12.
    solver="legacy": same call as restore_distortion.py (cv2.undistortPoints,
      OpenCV's default fixed iteration count).  Not converged near the corners
      (up to ~5 px, TEST 02C).  Regression / debug only -- never delivery."""
    gx, gy = np.meshgrid(np.arange(cam.w, dtype=np.float64), np.arange(cam.h, dtype=np.float64))
    pts = np.stack([gx, gy], axis=-1).reshape(-1, 1, 2)
    if solver == "legacy":
        pu = cv2.undistortPoints(pts, cam.K, cam.D, None, new_K(cam, ncx, ncy))
    elif solver == "converged":
        pu = cv2.undistortPointsIter(pts, cam.K, cam.D, None, new_K(cam, ncx, ncy), CONVERGED_CRITERIA)
    else:
        raise ValueError(solver)
    pu = pu.reshape(cam.h, cam.w, 2)
    return pu[..., 0].astype(np.float32), pu[..., 1].astype(np.float32)


# --- STMap normalisation --------------------------------------------------------
NORMALISATIONS = ("center", "wminus1")


def to_stmap(mx, my, src_w, src_h, norm="center"):
    """OpenCV index coords (top-origin col,row) -> Nuke ST.
    center: U = (col+0.5)/W, V = 1-(row+0.5)/H  (== (y_nuke+0.5)/H)."""
    mx = mx.astype(np.float64)
    my = my.astype(np.float64)
    if norm == "center":     # pixel centres at +0.5
        s = (mx + 0.5) / src_w
        t = 1.0 - (my + 0.5) / src_h
    elif norm == "wminus1":  # first/last pixel centre at 0/1
        s = mx / (src_w - 1)
        t = 1.0 - my / (src_h - 1)
    else:
        raise ValueError(norm)
    return s.astype(np.float32), t.astype(np.float32)


def from_stmap(s, t, src_w, src_h, norm="center"):
    """Inverse of to_stmap: where (in OpenCV index coords) Nuke would sample."""
    s = s.astype(np.float64)
    t = t.astype(np.float64)
    if norm == "center":
        return (s * src_w - 0.5).astype(np.float32), ((1.0 - t) * src_h - 0.5).astype(np.float32)
    return (s * (src_w - 1)).astype(np.float32), ((1.0 - t) * (src_h - 1)).astype(np.float32)


def write_stmap_exr(path, s, t):
    """32-bit float EXR, R=s G=t B=0 (cv2 writes BGR)."""
    img = np.dstack([np.zeros_like(s), t, s]).astype(np.float32)
    ok = cv2.imwrite(path, img, [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT])
    if not ok:
        raise IOError(f"failed to write {path}")
    back = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if back is None or back.dtype != np.float32 or not (np.array_equal(back[..., 2], s) and np.array_equal(back[..., 1], t)):
        raise IOError(f"EXR read-back mismatch for {path}")


def read_stmap_exr(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return img[..., 2], img[..., 1]


def apply_stmap(img, s, t, norm="center", interp=cv2.INTER_LINEAR):
    """Nuke-STMap-like resample (validated against Nuke in test_02a)."""
    H, W = img.shape[:2]
    x, y = from_stmap(s, t, W, H, norm)
    return cv2.remap(img, x, y, interp, borderMode=cv2.BORDER_CONSTANT)

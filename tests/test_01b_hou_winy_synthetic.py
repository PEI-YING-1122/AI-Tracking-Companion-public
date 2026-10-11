"""TEST 01B (synthetic) -- run with hython.  Memory-only scene, nothing saved.

Builds cameras exactly like build_houdini_scene.py (focal/aperture/winx from the
pinhole K), with winy from (A) upstream formula and (B) corrected formula, then
projects random points with Houdini's own toNDC() and compares with the pinhole
ground truth  u = fx*X/Z + cx,  v = fy*Y/Z + cy  (image y down, edge origin).

Also verifies the Python form of Houdini's projection used by test_01_validate.

    hython test_01b_hou_winy_synthetic.py <out.json>
"""
import json
import random
import sys

import hou

CASES = [
    # w, h, fx, cx, cy    (portrait / landscape, principal point offsets in px)
    (372, 662, 520.0, 186.0, 331.0),
    (372, 662, 520.0, 186.0, 331.3),
    (372, 662, 520.0, 200.0, 371.0),
    (372, 662, 520.0, 170.0, 291.0),
    (1920, 1080, 1700.0, 960.0, 540.0),
    (1920, 1080, 1700.0, 1000.0, 600.0),
    (1920, 1080, 1700.0, 930.0, 470.0),
]


def project_pinhole(fx, cx, cy, p):
    x, y, z = p
    # Houdini camera looks down -Z, Y up; image v grows downward
    return fx * x / -z + cx, fx * -y / -z + cy


def py_houdini(focal, aperture, resx, resy, winx, winy, p):
    x, y, z = p
    ndx = 0.5 + (focal / aperture) * x / -z - winx
    ndy = 0.5 + (focal / aperture) * (resx / resy) * y / -z - winy
    return ndx * resx, (1 - ndy) * resy


def main():
    out_path = sys.argv[1]
    random.seed(7)
    obj = hou.node("/obj")
    cam = obj.createNode("cam", "c")
    geo = obj.createNode("geo", "g")
    add = geo.createNode("add")
    wr = geo.createNode("attribwrangle")
    wr.setInput(0, add)
    wr.parm("class").set(2)  # points
    wr.parm("snippet").set('v@ndc = toNDC("/obj/c", @P);')
    pts = [(random.uniform(-2, 2), random.uniform(-3, 3), random.uniform(-12, -3)) for _ in range(200)]
    add.parm("points").set(len(pts))
    for i, p in enumerate(pts):
        add.parm(f"usept{i}").set(1)
        add.parmTuple(f"pt{i}").set(p)
    results = []
    for (w, h, fx, cx, cy) in CASES:
        sensor_w = 36.0
        focal = fx / w * sensor_w    # build_houdini_scene: fl_x / sensor_w * aperture_width (no expansion case)
        aperture = sensor_w
        winx = (w / 2 - cx) / w
        variants = {"A_upstream": (h / 2 - cy) / w, "B_corrected": (cy - h / 2) / h}
        cam.parm("resx").set(w)
        cam.parm("resy").set(h)
        cam.parm("focal").set(focal)
        cam.parm("aperture").set(aperture)
        cam.parm("winx").set(winx)
        row = {"w": w, "h": h, "fx": fx, "cx": cx, "cy": cy, "cy_minus_h2": cy - h / 2}
        for name, winy in variants.items():
            cam.parm("winy").set(winy)
            wr.cook(force=True)
            g = wr.geometry()
            du, dv, fdu = [], [], []
            for pt, p in zip(g.points(), pts):
                n = pt.attribValue("ndc")
                u, v = n[0] * w, (1 - n[1]) * h
                tu, tv = project_pinhole(fx, cx, cy, p)
                hu, hv = py_houdini(focal, aperture, w, h, winx, winy, p)
                du.append(u - tu)
                dv.append(v - tv)
                fdu.append(max(abs(u - hu), abs(v - hv)))
            row[name] = {"winy": winy, "max_abs_du_px": max(map(abs, du)), "max_abs_dv_px": max(map(abs, dv)),
                         "mean_dv_px": sum(dv) / len(dv), "py_formula_vs_toNDC_max_px": max(fdu)}
        row["winy_difference"] = variants["B_corrected"] - variants["A_upstream"]
        results.append(row)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=1)
    for r in results:
        print(r["w"], r["h"], "cy-h/2=%.2f" % r["cy_minus_h2"],
              "A dv=%.4f" % r["A_upstream"]["mean_dv_px"], "B dv=%.6f" % r["B_corrected"]["mean_dv_px"],
              "B max|du|=%.2e" % r["B_corrected"]["max_abs_du_px"],
              "fmla=%.1e" % r["B_corrected"]["py_formula_vs_toNDC_max_px"])


main()

"""Workstation Setup (PySide6): find Houdini / Maya / Nuke / FFmpeg / AI Tracking on this computer
and write configs/site.json -- the Artist never edits JSON.

    Configure_Companion.bat          (or: python gui/workstation_setup.py)

Detection, validation and saving live in common/workstation.py; this window only shows the
choices.  Several installed versions -> dropdown (Nuke defaults to the LOWEST version: a script
written by an older Nuke opens in a newer one); nothing found -> Browse.  Save validates every
required path first and never writes an invalid file.
"""
import json
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
import workstation as ws  # noqa: E402
from version import __version__  # noqa: E402

ROWS = (("hython", "Houdini"), ("mayapy", "Maya"), ("nuke", "Nuke Target"), ("ffmpeg", "FFmpeg"),
        ("ffprobe", "FFprobe"), ("upstream_repo", "AI Tracking"))
BROWSE = {"hython": ("file", "hython.exe (hython.exe)"), "mayapy": ("file", "mayapy.exe (mayapy.exe)"),
          "nuke": ("file", "Nuke (Nuke*.exe)"), "ffmpeg": ("file", "ffmpeg.exe (ffmpeg.exe)"),
          "ffprobe": ("file", "ffprobe.exe (ffprobe.exe)"), "upstream_repo": ("dir", None)}
HINT = {"nuke": "Default: the lowest installed supported Nuke (older Nuke scripts open in newer Nuke, not the "
                "reverse). Nuke 12 and older are not supported.",
        "upstream_repo": "Folder that contains run_autotracker.py.",
        "hython": "Houdini that opens the AI Tracking .hip files.",
        "mayapy": "Maya used to check the camera / point cloud delivery."}


class SetupWindow(QWidget):
    def __init__(self, site_path=None, program_roots=None, search_roots=None, on_saved=None):
        super().__init__()
        self.setWindowTitle(f"AI Tracking Companion {__version__} — Workstation Setup")
        self.site_path = site_path or ws.site_path()
        self.program_roots, self.search_roots = program_roots, search_roots
        self.on_saved = on_saved
        self.combos, self.status = {}, {}
        self.saved = False
        v = QVBoxLayout(self)
        t = QLabel("Workstation Setup")
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        t.setFont(f)
        v.addWidget(t)
        v.addWidget(QLabel(f"Tool locations of this computer → {self.site_path}"))
        g = QGridLayout()
        for r, (key, label) in enumerate(ROWS):
            g.addWidget(QLabel(label), r, 0)
            c = QComboBox()
            c.setEditable(True)
            c.setMinimumWidth(460)
            c.setInsertPolicy(QComboBox.NoInsert)
            c.currentTextChanged.connect(lambda _t, k=key: self._validate_row(k))
            if key in HINT:
                c.setToolTip(HINT[key])
            self.combos[key] = c
            g.addWidget(c, r, 1)
            b = QPushButton("Browse…")
            b.clicked.connect(lambda _c=False, k=key: self._browse(k))
            g.addWidget(b, r, 2)
            s = QLabel("")
            s.setMinimumWidth(220)
            s.setWordWrap(True)
            self.status[key] = s
            g.addWidget(s, r, 3)
        v.addLayout(g)
        self.nuke_note = QLabel(f"Nuke Target — Supported: Nuke {ws.NUKE_SUPPORTED[0]}–{ws.NUKE_SUPPORTED[1]}")
        self.nuke_note.setStyleSheet("color: #555")
        self.nuke_note.setToolTip(HINT["nuke"])
        v.addWidget(self.nuke_note)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.message)
        h = QHBoxLayout()
        h.addStretch()
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self.rescan)
        self.save_btn = QPushButton("Save Configuration")
        self.save_btn.clicked.connect(self.save)
        h.addWidget(self.rescan_btn)
        h.addWidget(self.save_btn)
        v.addLayout(h)
        self.resize(1000, 380)
        self.rescan()

    # ---------------------------------------------------------------- detection
    def rescan(self):
        current, _ = ws.read_site(self.site_path)
        typed = {k: self.value(k) for k in self.combos}
        self.found = ws.detect_all(self.program_roots, self.search_roots)
        for key, c in self.combos.items():
            c.blockSignals(True)
            c.clear()
            src = self.found["ffmpeg"] if key in ("ffmpeg", "ffprobe") else self.found[key]
            for item in src:
                path = item[key] if key in ("ffmpeg", "ffprobe") else item["path"]
                label = item["label"] if key not in ("ffmpeg", "ffprobe") else path
                c.addItem(f"{label}   ({path})" if label != path else path, path)
            pick = ws.default_choice(key, src, typed.get(key) or current.get(key))
            self._select(c, pick)
            c.blockSignals(False)
            self._validate_row(key)
        n = sum(1 for f in self.found["nuke"] if f.get("supported"))
        self.message.setText(f"Detected: {len(self.found['hython'])} Houdini, {len(self.found['mayapy'])} Maya, "
                             f"{n} supported Nuke, {len(self.found['ffmpeg'])} FFmpeg, {len(self.found['upstream_repo'])} AI Tracking."
                             + ("" if all(self.found[k] for k in ("hython", "mayapy", "nuke", "ffmpeg", "upstream_repo"))
                                else "  Not found: use Browse."))

    @staticmethod
    def _select(combo, path):
        if not path:
            combo.setCurrentIndex(-1)
            combo.setEditText("")
            return
        for i in range(combo.count()):
            if os.path.normcase(os.path.normpath(combo.itemData(i) or "")) == os.path.normcase(os.path.normpath(path)):
                combo.setCurrentIndex(i)
                return
        combo.addItem(path, path)
        combo.setCurrentIndex(combo.count() - 1)

    def value(self, key):
        c = self.combos[key]
        i = c.currentIndex()
        if i >= 0 and c.itemData(i) and c.currentText() == c.itemText(i):
            return c.itemData(i)
        return c.currentText().strip()

    def set_value(self, key, path):
        self._select(self.combos[key], path)
        self._validate_row(key)

    def _validate_row(self, key):
        msg = ws.problem(key, self.value(key))
        if key == "nuke" and not self.value(key) and getattr(self, "found", None) and self.found["nuke"]:
            msg = (f"No supported Nuke found ({', '.join(f['version'] for f in self.found['nuke'])} installed). "
                   f"Supported Nuke versions: {ws.NUKE_SUPPORTED_TEXT}.")
        extra = ""
        if key == "nuke" and not msg:
            extra = f"  Nuke Generator {ws.nuke_version(self.value(key)) or '?'}"
        self.status[key].setText(("✗ " + msg) if msg else "✓ OK" + extra)
        self.status[key].setStyleSheet("color: #c62828" if msg else "color: #2e7d32")
        return msg

    def _browse(self, key):
        kind, filt = BROWSE[key]
        start = os.path.dirname(self.value(key)) if self.value(key) else ""
        if kind == "dir":
            p = QFileDialog.getExistingDirectory(self, ws.NAMES[key], start)
        else:
            p, _ = QFileDialog.getOpenFileName(self, ws.NAMES[key], start, filt + ";;All files (*)")
        if p:
            self.set_value(key, p)
            if key == "ffmpeg" and not self.value("ffprobe"):  # ffprobe normally sits next to ffmpeg
                fp = os.path.join(os.path.dirname(p), "ffprobe.exe")
                if os.path.isfile(fp):
                    self.set_value("ffprobe", fp)

    # ---------------------------------------------------------------- save
    def save(self):
        values = {k: self.value(k) for k in self.combos}
        probs = ws.save(values, self.site_path)
        for k in self.combos:
            self._validate_row(k)
        if probs:
            self.message.setText("Not saved -- fix these first:\n" + "\n".join("• " + p["message"] for p in probs))
            self.message.setStyleSheet("color: #c62828")
            return False
        self.saved = True
        self.message.setStyleSheet("color: #2e7d32")
        self.message.setText(f"Saved {self.site_path}\nNuke Generator: {ws.nuke_version(values['nuke'])}")
        if self.on_saved:
            self.on_saved(self.site_path)
        return True


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    w = SetupWindow()
    w.show()
    selftest = os.environ.get("COMPANION_SETUP_SELFTEST")  # launcher test: report and quit
    if selftest:
        def report():
            json.dump({"title": w.windowTitle(), "visible": w.isVisible(), "python": sys.executable}, open(selftest, "w"))
            app.quit()
        QTimer.singleShot(500, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

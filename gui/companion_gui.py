"""AI Tracking Companion -- Artist GUI (PySide6).

A thin shell over companion_run.py.  The GUI never computes lens / camera /
STMap / Nuke data and never resolves paths or validates anything itself:
  * folder chosen  -> companion_run --detect            (scene, shot candidate, export candidate)
  * Check          -> companion_run --dry-run           (the CLI's own check report)
  * Build          -> companion_run [--overwrite]       (stage / validate / publish in the CLI)
It only collects input, starts the CLI through QProcess and shows the structured
result (build_result.json written by the CLI).  The CLI keeps working without it.

    python gui/companion_gui.py
"""
import json
import os
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
from version import __version__  # noqa: E402

CLI = os.path.join(ROOT, "companion_run.py")
STAGES = [("preflight", "Preflight"), ("resolve", "Resolving"), ("lens", "Building Lens"),
          ("maya", "Building Maya"), ("nuke", "Building Nuke"), ("validate", "Validating"),
          ("publish", "Publishing"), ("done", "Done")]
STATUS_STYLE = {"PASS": ("Ready", "#2e7d32"), "WARNING": ("Ready (warnings)", "#b26a00"),
                "BLOCKED": ("BLOCKED", "#c62828"), "FAIL": ("FAIL", "#c62828"),
                "CANCELLED": ("Cancelled", "#555555"), "BUILD": ("BUILD COMPLETE", "#2e7d32")}
PLATE_ISSUES = ("plate_none", "plate_ambiguous", "plate_override_invalid")


def project_configs():
    """Project configs offered in the dropdown: site config key 'project_configs'
    (files or folders), plus configs/projects/ inside the Companion.  Listing only."""
    paths = []
    try:
        import site_config
        extra = site_config._load().get("project_configs") or []
    except Exception:  # noqa: BLE001 -- a broken site config must not stop the GUI from opening
        extra = []
    for p in list(extra) + [os.path.join(ROOT, "configs", "projects")]:
        p = os.path.expandvars(p)
        if os.path.isdir(p):
            paths += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".json")]
        elif os.path.isfile(p):
            paths.append(p)
    out = []
    for p in paths:
        try:
            name = json.load(open(p)).get("name") or os.path.basename(p)
        except (OSError, ValueError):
            continue
        out.append((name, os.path.abspath(p)))
    return out


class CliRunner(QObject):
    """Runs companion_run.py once; streams stage markers and log lines; returns the result JSON."""
    stage = Signal(str)
    line = Signal(str)
    finished = Signal(dict, int)

    def __init__(self, parent=None, extra_env=None):
        super().__init__(parent)
        self.proc = None
        self.result_path = None
        self.extra_env = extra_env or {}

    def busy(self):
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, args):
        self.result_path = None
        self.proc = QProcess(self)
        # full inherited environment (QProcess.processEnvironment() of a fresh QProcess is EMPTY)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONDONTWRITEBYTECODE", "1")
        for k, v in self.extra_env.items():
            env.insert(k, v)
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(ROOT)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        self.line.emit("> " + " ".join([sys.executable, CLI] + args))
        self.proc.start(sys.executable, [CLI] + args)

    def _read(self):
        for raw in bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace").splitlines():
            if raw.startswith("@@STAGE "):
                self.stage.emit(raw.split(" ", 1)[1].strip())
            elif raw.startswith("@@RESULT "):
                self.result_path = raw.split(" ", 1)[1].strip()
            self.line.emit(raw)

    def _done(self, code, _status):
        self._read()
        res = {}
        if self.result_path and os.path.exists(self.result_path):
            try:
                res = json.load(open(self.result_path))
            except ValueError:
                res = {}
        if not res:
            res = {"status": "FAIL", "issues": [{"level": "FAIL", "code": "no_result",
                                                 "message": f"companion_run ended (code {code}) without a result"}]}
        self.finished.emit(res, int(code))


class MainWindow(QMainWindow):
    def __init__(self, confirm_overwrite=None, extra_env=None):
        super().__init__()
        self.setWindowTitle(f"AI Tracking Companion {__version__}")
        self.runner = CliRunner(self, extra_env)
        self.runner.stage.connect(self._on_stage)
        self.runner.line.connect(self._log)
        self.runner.finished.connect(self._on_finished)
        self.confirm_overwrite = confirm_overwrite or self._ask_overwrite
        self.mode = None
        self.last_check = None      # last --dry-run result (the CLI's check report)
        self.last_result = None     # last result of any kind
        self._detect_export = ""
        self._build()

    # ---------------------------------------------------------------- layout
    def _build(self):
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()
        self.project = QComboBox()
        for name, path in project_configs():
            self.project.addItem(name, path)
        form.addRow("Project", self.project)
        self.input = QLineEdit()
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_input)
        form.addRow("AI Tracking Folder", self._row(self.input, b))
        self.input.editingFinished.connect(self.run_detect)
        self.shot = QLineEdit()
        form.addRow("Shot Name", self.shot)
        self.export = QLineEdit()
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_export)
        form.addRow("Export Folder", self._row(self.export, b))
        self.maya = QCheckBox("Maya")
        self.maya.setChecked(True)
        self.nuke = QCheckBox("Nuke")
        self.nuke.setChecked(True)
        outs = QHBoxLayout()
        outs.addWidget(self.maya)
        outs.addWidget(self.nuke)
        outs.addWidget(QLabel("(metadata always; Nuke includes lens)"))
        outs.addStretch()
        ow = QWidget()
        ow.setLayout(outs)
        form.addRow("Outputs", ow)
        # source plate: only shown when the resolver needs the Artist (or an override exists)
        self.plate = QLineEdit()
        self.plate_candidates = QComboBox()
        self.plate_candidates.currentIndexChanged.connect(self._pick_candidate)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_plate)
        self.plate_row = QWidget()
        pr = QHBoxLayout(self.plate_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(self.plate, 3)
        pr.addWidget(self.plate_candidates, 2)
        pr.addWidget(b)
        self.plate_label = QLabel("Source Plate")
        form.addRow(self.plate_label, self.plate_row)
        self._show_plate(False)
        v.addLayout(form)

        btns = QHBoxLayout()
        self.check_btn = QPushButton("Check")
        self.check_btn.clicked.connect(self.run_check)
        self.build_btn = QPushButton("Build")
        self.build_btn.setEnabled(False)
        self.build_btn.clicked.connect(self.run_build)
        btns.addStretch()
        btns.addWidget(self.check_btn)
        btns.addWidget(self.build_btn)
        v.addLayout(btns)

        self.status = QLabel("Choose a project and an AI Tracking folder.")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.status.setFont(f)
        v.addWidget(self.status)
        self.messages = QLabel("")
        self.messages.setWordWrap(True)
        self.messages.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.messages)

        box = QGroupBox("Detected")
        self.info = QFormLayout(box)
        self.fields = {}
        for k in ("Camera", "Camera Model", "Plate", "Flatten", "FPS", "Frames", "Resolution", "Export Path",
                  "Existing Delivery"):
            lab = QLabel("-")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.fields[k] = lab
            self.info.addRow(k, lab)
        v.addWidget(box)

        self.progress = QLabel("")
        v.addWidget(self.progress)
        self.result_box = QGroupBox("Result")
        rl = QVBoxLayout(self.result_box)
        self.result_text = QLabel("")
        self.result_text.setWordWrap(True)
        self.result_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.result_text)
        self.open_btn = QPushButton("Open Export Folder")
        self.open_btn.clicked.connect(self._open_export)
        rl.addWidget(self.open_btn)
        self.result_box.setVisible(False)
        v.addWidget(self.result_box)

        self.details_btn = QToolButton()
        self.details_btn.setText("Details / Log")
        self.details_btn.setCheckable(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.details_btn.toggled.connect(self.log.setVisible)
        v.addWidget(self.details_btn)
        v.addWidget(self.log, 1)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        v.addWidget(line)
        self.setCentralWidget(w)
        self.resize(820, 640)

    @staticmethod
    def _row(edit, button):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        h.addWidget(button)
        return w

    def _show_plate(self, on):
        self.plate_row.setVisible(on)
        self.plate_label.setVisible(on)

    # ---------------------------------------------------------------- CLI arguments
    def _project_args(self):
        return ["--project", self.project.currentData() or "", "--input", self.input.text().strip()]

    def _common_args(self):
        args = self._project_args() + ["--shot", self.shot.text().strip()]
        if self.export.text().strip():
            args += ["--export", self.export.text().strip()]
        if not self.plate_row.isHidden() and self.plate.text().strip():
            args += ["--plate", self.plate.text().strip()]
        outs = (["maya"] if self.maya.isChecked() else []) + (["nuke"] if self.nuke.isChecked() else [])
        if outs and outs != ["maya", "nuke"]:  # both = the CLI default (full delivery)
            args += ["--outputs"] + outs
        return args

    # ---------------------------------------------------------------- actions
    def run_detect(self):
        if self.runner.busy() or not self.input.text().strip():
            return
        self.mode = "detect"
        self._set_busy("Detecting…")
        self.runner.start(self._project_args() + ["--detect"] + (["--shot", self.shot.text().strip()] if self.shot.text().strip() else []))

    def run_check(self):
        if self.runner.busy():
            return
        if not (self.maya.isChecked() or self.nuke.isChecked()):
            self._status("BLOCKED", ["Select at least one output (Maya or Nuke)."])
            return
        self.mode = "check"
        self._set_busy("Checking…")
        self.runner.start(self._common_args() + ["--dry-run"])

    def run_build(self):
        if self.runner.busy() or not self.last_check:
            return
        args = self._common_args()
        if self.last_check.get("check", {}).get("existing_delivery"):
            if not self.confirm_overwrite():
                self._status("CANCELLED", ["Existing delivery kept. Build cancelled."])
                return
            args.append("--overwrite")
        self.mode = "build"
        self.result_box.setVisible(False)
        self._set_busy("Building…")
        self.runner.start(args)

    # ---------------------------------------------------------------- callbacks
    def _on_stage(self, key):
        names = dict(STAGES)
        done = []
        for k, label in STAGES:
            done.append(("▶ " if k == key else "") + label)
            if k == key:
                break
        self.progress.setText("  →  ".join(done) if key in names else key)

    def _log(self, text):
        self.log.appendPlainText(text)

    def _on_finished(self, res, code):
        self.last_result = res
        mode = self.mode
        self.mode = None
        self.check_btn.setEnabled(True)
        if mode == "detect":
            self._apply_detect(res)
            if res.get("status") != "BLOCKED" and self.shot.text().strip():
                self.run_check()
            return
        msgs = [f"{i['message']}" for i in res.get("issues", [])]
        if mode == "check":
            self.last_check = res
            self._apply_check(res)
            st = res.get("status", "FAIL")
            self._status(st, msgs)
            self.build_btn.setEnabled(st in ("PASS", "WARNING"))
        else:
            st = res.get("status", "FAIL")
            if st in ("PASS", "WARNING"):
                self._status("BUILD", msgs)
                self._show_result(res)
                self._on_stage("done")
            else:
                self._status(st, msgs)
            self.build_btn.setEnabled(False)  # re-check before building again
            self.last_check = None

    # ---------------------------------------------------------------- presentation only
    def _apply_detect(self, res):
        d = res.get("detect") or {}
        if d.get("shot_suggestion") and not self.shot.text().strip():
            self.shot.setText(d["shot_suggestion"])
        if d.get("export_candidate") and (not self.export.text().strip() or self.export.text() == self._detect_export):
            self.export.setText(d["export_candidate"])
            self._detect_export = d["export_candidate"]
        if res.get("status") == "BLOCKED":
            self._status("BLOCKED", [i["message"] for i in res.get("issues", [])])

    def _apply_check(self, res):
        c = res.get("check") or {}
        f = self.fields
        cam = c.get("camera") or {}
        f["Camera"].setText(f"{cam.get('scene', '-')}  ({cam.get('hip', '-')})" if cam else "-")
        f["Camera Model"].setText(c.get("camera_model", "-"))
        p = c.get("plate") or {}
        f["Plate"].setText(f"{p.get('path', '-')}  [{p.get('status', '-')}]")
        fl = c.get("flatten") or {}
        f["Flatten"].setText(f"{fl.get('path') or 'none'}  [{fl.get('mode', '-')}]")
        f["FPS"].setText(f"{c.get('fps', '-')} ({c.get('fps_source', '-')})" if c else "-")
        fr = c.get("frames") or {}
        f["Frames"].setText(f"source {fr.get('source')}   tracking {fr.get('tracking')}" if fr else "-")
        r = c.get("resolution") or {}
        f["Resolution"].setText(f"plate {r.get('source')}   production {r.get('production_canvas')}" if r else "-")
        f["Export Path"].setText(c.get("export_root", "-"))
        ex = c.get("existing_delivery") or []
        f["Existing Delivery"].setText(f"Existing Delivery Found ({len(ex)} files)" if ex else "none")
        issues = {i["code"]: i for i in res.get("issues", [])}
        plate_issue = next((issues[k] for k in PLATE_ISSUES if k in issues), None)
        show = bool(plate_issue) or p.get("status") == "override"
        self._show_plate(show)
        self.plate_candidates.blockSignals(True)
        self.plate_candidates.clear()
        if plate_issue and isinstance(plate_issue.get("detail"), list):
            self.plate_candidates.addItem("— candidates —", "")
            for cand in plate_issue["detail"]:
                if cand.get("ok"):
                    self.plate_candidates.addItem(os.path.basename(cand["pattern"]), cand["pattern"])
        self.plate_candidates.setVisible(self.plate_candidates.count() > 1)
        self.plate_candidates.blockSignals(False)
        if p.get("status") == "override" and not self.plate.text():
            self.plate.setText(p.get("path", ""))

    def _show_result(self, res):
        m = res.get("manifest") or {}
        d = res.get("delivery") or {}  # the CLI's own module summary (built / kept / not built)
        lines = [f"Shot: {res.get('shot')}", f"Export Folder: {m.get('export_root', '')}"]
        lines += [f"{g}: {d.get(g.lower(), '-')}" for g in ("Maya", "Nuke", "Lens", "Metadata")]
        self.result_text.setText("\n".join(lines))
        self.result_box.setVisible(True)

    def _status(self, status, msgs):
        text, color = STATUS_STYLE.get(status, (status, "#000"))
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}")
        self.messages.setText("\n".join(msgs))

    def _set_busy(self, text):
        self.check_btn.setEnabled(False)
        self.build_btn.setEnabled(False)
        self.status.setText(text)
        self.status.setStyleSheet("color: #000")
        self.progress.setText("")

    # ---------------------------------------------------------------- dialogs
    def _browse_input(self):
        d = QFileDialog.getExistingDirectory(self, "AI Tracking Folder", self.input.text())
        if d:
            self.input.setText(d)
            self.shot.clear()
            self.run_detect()

    def _browse_export(self):
        d = QFileDialog.getExistingDirectory(self, "Export Folder", self.export.text())
        if d:
            self.export.setText(d)

    def _browse_plate(self):
        f, _ = QFileDialog.getOpenFileName(self, "Source Plate (any frame of the sequence, or a video)")
        if f:
            self.plate.setText(f)
            self.run_check()

    def _pick_candidate(self, i):
        path = self.plate_candidates.itemData(i)
        if path:
            self.plate.setText(path)
            self.run_check()

    def _ask_overwrite(self):
        r = QMessageBox.question(self, "Existing delivery", "Overwrite existing delivery?\n"
                                 "(the current delivery is backed up before it is replaced)",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    def _open_export(self):
        path = ((self.last_result or {}).get("manifest") or {}).get("export_root") or self.export.text()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

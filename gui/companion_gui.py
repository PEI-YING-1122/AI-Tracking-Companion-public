"""AI Tracking Companion -- Artist GUI (PySide6).

A thin shell over companion_run.py (direct mode: no project config needed).  The GUI never
computes lens / camera / STMap / Nuke data and never resolves or validates paths itself:
  * AI Tracking Folder chosen -> companion_run --input F --detect      (scene, HIP, export default)
  * Check                     -> companion_run --input F --shot S --plate P ... --dry-run
  * Start                     -> the same without --dry-run (--overwrite only after the Artist said Yes)
  * Stop                      -> creates the --cancel-file; the CLI stops at its next safe point
                                 (never during publish)
It only collects input, starts the CLI through QProcess and shows the CLI's structured result
(build_result.json).  The CLI keeps working without it.

    python gui/companion_gui.py        (or double-click AI_Tracking_Companion.bat)
"""
import json
import os
import sys
import tempfile
import uuid

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
from version import __version__  # noqa: E402
import workstation  # noqa: E402

CLI = os.path.join(ROOT, "companion_run.py")
STAGES = [("preflight", "Preflight"), ("resolve", "Resolving"), ("lens", "Building Lens"),
          ("maya", "Building Maya"), ("nuke", "Building Nuke"), ("validate", "Validating"),
          ("publish", "Publishing"), ("done", "Done")]
STATUS_STYLE = {"PASS": ("Ready", "#2e7d32"), "WARNING": ("Ready (warnings)", "#b26a00"),
                "BLOCKED": ("BLOCKED", "#c62828"), "FAIL": ("FAIL", "#c62828"),
                "CANCELLED": ("Cancelled", "#555555"), "BUILD": ("BUILD COMPLETE", "#2e7d32")}
FPS_SOURCE = {"ffprobe": "Video Metadata", "exr_header": "EXR Header", "default": "Default",
              "artist_override": "Artist Override", "project_config": "Project Setting"}
PLATE_KIND = {"exr_sequence": "EXR sequence", "jpg_sequence": "JPG sequence", "png_sequence": "PNG sequence",
              "image_sequence": "image sequence", "video": "video"}
INFO_PLATE = ("Original distorted source plate.\n\n"
              "Used to determine production resolution, frame range, FPS metadata when available, "
              "and Nuke lens setup.\n\n"
              "For an image sequence, select any frame from the sequence.")
INFO_FPS = ("FPS is detected automatically from the original source when available.\n\n"
            "Image sequences such as JPG or PNG may not contain FPS metadata.\n\n"
            "If FPS cannot be detected, the default is 24 fps and can be overridden here.")
PLATE_FILTER = "Original plate (*.exr *.jpg *.jpeg *.png *.tif *.tiff *.dpx *.mov *.mp4 *.avi *.mkv);;All files (*)"
CHECK_ROWS = ("Tracking Scene", "Camera", "Original Plate", "Flatten", "Frames", "Resolution", "FPS", "Nuke Generator",
              "Export")


def flatten_text(fl):
    """Check row text for the AI Tracking flatten (the CLI decides the status)"""
    st = fl.get("status")
    if fl.get("mode") == "reference_ai_tracking" and st == "reference_compatible":
        d = max(abs(x) for x in (fl.get("pp_delta_px") or [0, 0]))
        return f"ⓘ Tracking Flatten: Reference Only (principal point Δ {d:.4f} px)"
    if fl.get("mode") == "reference_ai_tracking":
        return "✓ AI Tracking flatten (reference)"
    if st == "incompatible":
        return "⚠ Tracking flatten is incompatible and was not used"
    if fl.get("mode") == "none":
        return "ⓘ not used"
    return f"✓ {fl.get('mode')}"


def cli_python():
    """the console interpreter next to ours (pythonw has no stdout for the CLI)"""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(cand):
            return cand
    return exe


def fmt_fps(v):
    return f"{round(float(v), 3):g}"


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
        self.line.emit("> " + " ".join([cli_python(), CLI] + args))
        self.proc.start(cli_python(), [CLI] + args)

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
    def __init__(self, confirm_overwrite=None, extra_env=None, show_info=None, open_setup=None):
        super().__init__()
        self.setWindowTitle(f"AI Tracking Companion {__version__}")
        self.runner = CliRunner(self, extra_env)
        self.runner.stage.connect(self._on_stage)
        self.runner.line.connect(self._log)
        self.runner.finished.connect(self._on_finished)
        self.confirm_overwrite = confirm_overwrite or self._ask_overwrite
        self.show_info = show_info or self._show_info
        self.mode = None            # detect / check / build while the CLI runs
        self.last_check = None      # last --dry-run result (the CLI's check report)
        self.last_result = None     # last result of any kind
        self.check_args = None      # arguments the last Check was run with
        self.fps_override = None    # text typed by the Artist (None = use the detected fps)
        self.cancel_file = None
        self.publishing = False
        self._detect_export = ""
        self.open_setup_window = open_setup or self._open_setup_window
        self.setup_window = None
        self._build()
        self._set_state("idle")
        self.refresh_workstation()

    # ---------------------------------------------------------------- layout
    def _build(self):
        w = QWidget()
        v = QVBoxLayout(w)
        title = QLabel("AI Tracking Companion")
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        v.addWidget(title)

        self.setup_box = QGroupBox("Workstation Setup Required")   # first run / broken site.json only
        sl = QVBoxLayout(self.setup_box)
        self.setup_text = QLabel("")
        self.setup_text.setWordWrap(True)
        self.setup_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sl.addWidget(self.setup_text)
        self.configure_btn = QPushButton("Configure")
        self.configure_btn.clicked.connect(self.open_setup)
        sl.addWidget(self.configure_btn, 0, Qt.AlignLeft)
        self.setup_box.setStyleSheet("QGroupBox { color: #c62828; font-weight: bold; }")
        v.addWidget(self.setup_box)

        form = QFormLayout()
        self.input = QLineEdit()
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_input)
        form.addRow("AI Tracking Folder", self._row(self.input, b))
        self.input.editingFinished.connect(self._input_edited)

        self.shot = QLineEdit()
        self.shot.setPlaceholderText("e.g. demo_sh0010")
        form.addRow("Shot Name", self.shot)

        self.plate = QLineEdit()
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_plate)
        self.plate_info = self._info_button("Original Plate", INFO_PLATE)
        form.addRow(self._label_with_info("Original Plate", self.plate_info), self._row(self.plate, b))

        self.export = QLineEdit()
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_export)
        form.addRow("Export Folder", self._row(self.export, b))

        self.fps = QLineEdit()
        self.fps.setFixedWidth(80)
        self.fps.editingFinished.connect(self._fps_edited)
        self.fps_source = QLabel("")
        self.fps_info = self._info_button("FPS", INFO_FPS)
        fw = QWidget()
        fh = QHBoxLayout(fw)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.addWidget(self.fps)
        fh.addWidget(self.fps_source)
        fh.addStretch()
        form.addRow(self._label_with_info("FPS", self.fps_info), fw)

        self.maya = QCheckBox("Maya")
        self.maya.setChecked(True)
        self.nuke = QCheckBox("Nuke")
        self.nuke.setChecked(True)
        ow = QWidget()
        oh = QHBoxLayout(ow)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.addWidget(self.maya)
        oh.addWidget(self.nuke)
        oh.addWidget(QLabel("Metadata always generated."))
        oh.addStretch()
        form.addRow("Outputs", ow)
        v.addLayout(form)

        btns = QHBoxLayout()
        self.check_btn = QPushButton("Check")
        self.check_btn.clicked.connect(self.run_check)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.run_build)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        btns.addStretch()
        for x in (self.check_btn, self.start_btn, self.stop_btn):
            btns.addWidget(x)
        v.addLayout(btns)

        self.status = QLabel("Choose the AI Tracking Folder.")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.status.setFont(f)
        v.addWidget(self.status)
        self.messages = QLabel("")
        self.messages.setWordWrap(True)
        self.messages.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.messages)

        box = QGroupBox("Check")
        grid = QFormLayout(box)
        self.fields = {}
        for k in CHECK_ROWS:
            lab = QLabel("-")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.fields[k] = lab
            grid.addRow(k, lab)
        v.addWidget(box)

        self.progress = QLabel("")
        self.progress.setWordWrap(True)
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

        self.setup_btn = QToolButton()
        self.setup_btn.setText("Workstation Setup…")
        self.setup_btn.clicked.connect(self.open_setup)
        self.details_btn = QToolButton()
        self.details_btn.setText("Details / Log")
        self.details_btn.setCheckable(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.details_btn.toggled.connect(self.log.setVisible)
        bottom = QHBoxLayout()
        bottom.addWidget(self.details_btn)
        bottom.addStretch()
        bottom.addWidget(self.setup_btn)
        v.addLayout(bottom)
        v.addWidget(self.log, 1)
        self.setCentralWidget(w)
        self.resize(820, 700)
        for e in (self.input, self.shot, self.plate, self.export):
            e.textEdited.connect(self._inputs_changed)
        for c in (self.maya, self.nuke):
            c.toggled.connect(self._inputs_changed)

    @staticmethod
    def _row(edit, button):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        h.addWidget(button)
        return w

    def _info_button(self, title, text):
        b = QToolButton()
        b.setText("ⓘ")
        b.setAutoRaise(True)
        b.setToolTip(title)
        b.info_text = text
        b.clicked.connect(lambda: self.show_info(title, text))
        return b

    @staticmethod
    def _label_with_info(text, button):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(text))
        h.addWidget(button)
        h.addStretch()
        return w

    # ---------------------------------------------------------------- button states
    def _set_state(self, state):
        """idle / running / publishing (Start only after a passing Check of the current inputs)"""
        running = state in ("running", "publishing")
        self.check_btn.setEnabled(not running)
        self.start_btn.setEnabled(state == "idle" and self._check_still_valid())
        self.stop_btn.setEnabled(state == "running" and self.mode == "build")
        for x in (self.input, self.shot, self.plate, self.export, self.fps, self.maya, self.nuke):
            x.setEnabled(not running)

    def _check_still_valid(self):
        return bool(self.last_check) and self.last_check.get("status") in ("PASS", "WARNING") \
            and self.check_args == self._common_args()

    # ---------------------------------------------------------------- CLI arguments
    def _common_args(self):
        args = ["--input", self.input.text().strip(), "--shot", self.shot.text().strip(),
                "--plate", self.plate.text().strip()]
        if self.export.text().strip():
            args += ["--export", self.export.text().strip()]
        if self.fps_override:
            args += ["--fps", self.fps_override]
        outs = (["maya"] if self.maya.isChecked() else []) + (["nuke"] if self.nuke.isChecked() else [])
        if outs and outs != ["maya", "nuke"]:  # both = the CLI default (full delivery)
            args += ["--outputs"] + outs
        return args

    # ---------------------------------------------------------------- actions
    def run_detect(self):
        if self.runner.busy() or not self.input.text().strip():
            return
        self.mode = "detect"
        self._busy("Reading the AI Tracking folder…")
        self.runner.start(["--input", self.input.text().strip(), "--detect"])

    def run_check(self):
        if self.runner.busy():
            return
        if not (self.maya.isChecked() or self.nuke.isChecked()):
            self._status("BLOCKED", ["Select at least one output (Maya or Nuke)."])
            return
        self.mode = "check"
        self._busy("Checking…")
        self.runner.start(self._common_args() + ["--dry-run"])

    def run_build(self):
        if self.runner.busy() or not self._check_still_valid():
            return
        args = self._common_args()
        if (self.last_check.get("check") or {}).get("existing_delivery"):
            if not self.confirm_overwrite():
                self._status("CANCELLED", ["Existing delivery kept. Nothing was started."])
                return
            args.append("--overwrite")
        self.cancel_file = os.path.join(tempfile.gettempdir(), f"ai_tracking_companion_stop_{uuid.uuid4().hex}.flag")
        args += ["--cancel-file", self.cancel_file]
        self.mode = "build"
        self.publishing = False
        self.result_box.setVisible(False)
        self._busy("Running…")
        self.runner.start(args)

    def stop(self):
        """cooperative: ask the CLI to stop at its next safe point; never during publish"""
        if self.mode != "build" or self.publishing or not self.cancel_file:
            return
        open(self.cancel_file, "w").write("stop requested by the Artist\n")
        self.stop_btn.setEnabled(False)
        self.status.setText("Stopping… (the current step finishes first)")

    # ---------------------------------------------------------------- callbacks
    def _on_stage(self, key):
        if key == "publish" and self.mode == "build":
            self.publishing = True
            self._set_state("publishing")
            self.status.setText("Finishing publish transaction...")
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
        mode, self.mode = self.mode, None
        if self.cancel_file and os.path.exists(self.cancel_file):
            os.remove(self.cancel_file)
        self.cancel_file = None
        self.publishing = False
        msgs = self._messages(res)
        st = res.get("status", "FAIL")
        if mode == "detect":
            self._apply_detect(res)
            self._set_state("idle")
            if st != "BLOCKED" and self.shot.text().strip() and self.plate.text().strip():
                self.run_check()
            return
        if mode == "check":
            self.last_check = res
            self.check_args = self._common_args()
            self._apply_check(res)
            self._status(st, msgs)
        else:
            self.last_check, self.check_args = None, None  # Check again before the next Start
            if st in ("PASS", "WARNING"):
                self._status("BUILD", msgs)
                self._show_result(res)
                self._on_stage("done")
            else:
                self._status(st, msgs)
        self._set_state("idle")

    def _inputs_changed(self, *_):
        if self.mode is None and self.last_check is not None:
            self._set_state("idle")
            if not self._check_still_valid() and self.last_check.get("status") in ("PASS", "WARNING"):
                self.status.setText("Inputs changed. Press Check.")
                self.status.setStyleSheet("color: #000")

    # ---------------------------------------------------------------- presentation only
    @staticmethod
    def _messages(res):
        out = [i["message"] for i in res.get("issues", [])]
        out += ["ⓘ " + n["message"] for n in res.get("notes", [])]
        return out

    def _apply_detect(self, res):
        d = res.get("detect") or {}
        if d.get("export_candidate") and (not self.export.text().strip() or self.export.text() == self._detect_export):
            self.export.setText(d["export_candidate"])
            self._detect_export = d["export_candidate"]
        if d.get("scene"):
            self.fields["Tracking Scene"].setText(f"{d['scene']}  ({d.get('hip', '')})")
            self._log(f"AI Tracking scene {d['scene']}: {d.get('tracking_frames')} tracking frames, "
                      f"{d.get('tracking_resolution')}")
        if res.get("status") == "BLOCKED":
            self._status("BLOCKED", self._messages(res))
        elif not self.shot.text().strip() or not self.plate.text().strip():
            self.status.setText("Enter the Shot Name and choose the Original Plate, then Check.")
            self.status.setStyleSheet("color: #000")
            self.messages.setText("")

    def _apply_check(self, res):
        c = res.get("check") or {}
        f = self.fields
        ok, info = "✓", "ⓘ"
        for k in CHECK_ROWS:
            f[k].setText("-")
        if not c:
            return
        cam = c.get("camera") or {}
        f["Tracking Scene"].setText(f"{ok} {cam.get('scene', '-')}  ({cam.get('hip', '-')})")
        f["Camera"].setText(f"{ok} Ready  ({c.get('camera_model', '-')})")
        p = c.get("plate") or {}
        f["Original Plate"].setText(f"{ok} {os.path.basename(p.get('path', ''))}  "
                                    f"({PLATE_KIND.get(p.get('kind'), p.get('kind'))})")
        f["Flatten"].setText(flatten_text(c.get("flatten") or {}))
        ng = c.get("nuke_generator")
        f["Nuke Generator"].setText(f"{info} {ng.get('version') or '?'}" if ng else "- (Nuke not selected)")
        if ng:
            self._log(f"Nuke Generator: {ng.get('version')}  ({ng.get('path')})")
        fr = c.get("frames") or {}
        if fr.get("tracking"):
            a, b = fr["tracking"]
            f["Frames"].setText(f"{ok} {a}–{b} ({fr.get('count', b - a + 1)} frames)")
            ti = fr.get("tracking_internal")
            if ti:
                self._log(f"Tracking frames {ti[0]}–{ti[1]} = source frames {a}–{b}; plate {fr.get('source')}")
        r = c.get("resolution") or {}
        if r.get("source") and r.get("production_canvas"):
            f["Resolution"].setText(f"{ok} {r['source'][0]}×{r['source'][1]} → "
                                    f"{r['production_canvas'][0]}×{r['production_canvas'][1]}")
        src = FPS_SOURCE.get(c.get("fps_source"), c.get("fps_source") or "")
        if c.get("fps") is not None:
            f["FPS"].setText(f"{info} {fmt_fps(c['fps'])} ({src})")
            if not self.fps_override:
                self.fps.setText(fmt_fps(c["fps"]))
            self.fps_source.setText(f"Source: {src}")
        ex = c.get("existing_delivery") or []
        f["Export"].setText(c.get("export_root", "-") + (f"\n{info} Existing Companion delivery ({len(ex)} files)"
                                                        if ex else ""))

    # ---------------------------------------------------------------- workstation
    def refresh_workstation(self):
        """first-run check: site.json missing / placeholder / tools not found -> 'Workstation Setup Required'"""
        st = workstation.status()
        self.workstation = st
        probs = [p["message"] for p in st["problems"]]
        if st["companion_on_network_drive"]:
            probs.append("The Companion runs from a network drive. Install it on a local disk "
                         "(e.g. C:\\Tools\\AI_Tracking_Companion_v0.2.x).")
        self.setup_text.setText("\n".join("• " + p for p in probs))
        self.setup_box.setVisible(bool(probs))
        if not self.last_check:  # before a Check: what the site configuration says
            self.fields["Nuke Generator"].setText(f"ⓘ {st['nuke_version']}" if st["nuke_version"] and not any(
                p["key"] == "nuke" for p in st["problems"]) else "-")
        return st

    def open_setup(self):
        self.open_setup_window(self)

    def _open_setup_window(self, _parent):
        import workstation_setup
        self.setup_window = workstation_setup.SetupWindow(on_saved=lambda _p: self.refresh_workstation())
        self.setup_window.show()
        self.setup_window.raise_()

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

    def _busy(self, text):
        self._set_state("running")
        self.status.setText(text)
        self.status.setStyleSheet("color: #000")
        self.messages.setText("")
        self.progress.setText("")

    # ---------------------------------------------------------------- inputs
    def _input_edited(self):
        if self.input.isModified():
            self.input.setModified(False)
            self._new_folder()

    def _new_folder(self):
        self.fps_override = None
        self.fps.clear()
        self.fps_source.setText("")
        self.last_check, self.check_args = None, None
        for k in CHECK_ROWS:
            self.fields[k].setText("-")
        self.run_detect()

    def _fps_edited(self):
        t = self.fps.text().strip()
        detected = fmt_fps(((self.last_check or {}).get("check") or {}).get("fps") or 0) if self.last_check else None
        new = None if (not t or (t == detected and not self.fps_override)) else t
        if new != self.fps_override:
            self.fps_override = new
            if self.input.text().strip() and self.shot.text().strip() and self.plate.text().strip():
                self.run_check()

    def _browse_input(self):
        d = QFileDialog.getExistingDirectory(self, "AI Tracking Folder", self.input.text())
        if d:
            self.input.setText(d)
            self._new_folder()

    def _browse_export(self):
        d = QFileDialog.getExistingDirectory(self, "Export Folder", self.export.text())
        if d:
            self.export.setText(d)
            self._inputs_changed()

    def _browse_plate(self):
        start = os.path.dirname(self.plate.text()) if self.plate.text() else self.input.text()
        f, _ = QFileDialog.getOpenFileName(self, "Original Plate (any frame of the sequence, or a video)", start,
                                           PLATE_FILTER)
        if f:
            self.plate.setText(f)
            if self.input.text().strip() and self.shot.text().strip():
                self.run_check()

    def _ask_overwrite(self):
        r = QMessageBox.question(self, "Existing delivery", "Overwrite existing delivery?\n"
                                 "(the current delivery is backed up before it is replaced)",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    def _show_info(self, title, text):
        QMessageBox.information(self, title, text)

    def _open_export(self):
        path = ((self.last_result or {}).get("manifest") or {}).get("export_root") or self.export.text()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    selftest = os.environ.get("COMPANION_GUI_SELFTEST")  # launcher test: report and quit
    if selftest:
        def report():
            json.dump({"title": w.windowTitle(), "visible": w.isVisible(), "python": sys.executable,
                       "cli_python": cli_python(), "has_project_field": hasattr(w, "project")},
                      open(selftest, "w"))
            app.quit()
        QTimer.singleShot(500, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""Transactional build support: issue levels, build folders, stage -> publish with backup / rollback.

Levels
    PASS      nothing to report
    WARNING   correct result, the Artist should know (build continues, recorded)
    BLOCKED   a precondition failed -- nothing is built or published
    FAIL      the build or its validation failed -- nothing is published
    CANCELLED outputs already exist and overwrite was not requested -- nothing is built

Build folder:  <work_dir>/builds/<build_id>/
    stage/        complete candidate delivery, same relative layout and filenames as the export
    validate/     temporary, path-remapped copies used only by validation
    backup/       previous delivery files replaced by this build (overwrite only)
    logs/         subprocess logs
    build_result.json, shot_config.json (provenance), manifest.json
"""
import hashlib
import json
import os
import shutil
import time
import uuid

PASS, WARNING, BLOCKED, FAIL, CANCELLED = "PASS", "WARNING", "BLOCKED", "FAIL", "CANCELLED"
EXIT_CODES = {PASS: 0, WARNING: 0, FAIL: 1, BLOCKED: 2, CANCELLED: 5}
_RANK = {PASS: 0, WARNING: 1, CANCELLED: 2, BLOCKED: 3, FAIL: 4}


class BuildStop(Exception):
    """Raised to stop the build; carries the level (BLOCKED / FAIL / CANCELLED)."""

    def __init__(self, level, code, message, detail=None):
        super().__init__(message)
        self.level, self.code, self.message, self.detail = level, code, message, detail


def new_build_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


class BuildRecord:
    """Collects issues and step results; writes build_result.json."""

    def __init__(self, build_dir, build_id, shot):
        self.build_dir, self.build_id, self.shot = build_dir, build_id, shot
        self.issues, self.steps = [], []
        self.t0 = time.time()
        self.status = PASS
        self.published = []
        self.extra = {}

    def issue(self, level, code, message, detail=None):
        self.issues.append({"level": level, "code": code, "message": message, "detail": detail})
        if _RANK[level] > _RANK[self.status]:
            self.status = level

    def step(self, name, status, seconds, **info):
        self.steps.append({"step": name, "status": status, "seconds": round(seconds, 1), **info})

    def write(self):
        os.makedirs(self.build_dir, exist_ok=True)
        res = {"build_id": self.build_id, "shot": self.shot, "status": self.status,
               "exit_code": EXIT_CODES[self.status], "elapsed_s": round(time.time() - self.t0, 1),
               "steps": self.steps, "issues": self.issues, "published": self.published, **self.extra}
        with open(os.path.join(self.build_dir, "build_result.json"), "w") as f:
            json.dump(res, f, indent=1, default=str)
        return res


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def state_of(paths):
    """{path: sha256 or None} -- used to prove a rollback restored the export exactly."""
    return {p: (sha256(p) if os.path.exists(p) else None) for p in paths}


def stage_path(final_path, export_root, stage_root):
    """Same relative location under the stage root."""
    fp, er = final_path.replace("\\", "/"), export_root.replace("\\", "/").rstrip("/")
    if not fp.lower().startswith(er.lower() + "/"):
        raise ValueError(f"{final_path} is not under the export root {export_root}")
    return stage_root.replace("\\", "/").rstrip("/") + fp[len(er):]


def existing_targets(targets):
    return [t for t in targets if os.path.exists(t)]


def publish(pairs, backup_dir, overwrite, record, fault_after=None):
    """Copy stage files to their final paths as one unit.

    pairs: [(stage_file, final_file)].  Existing finals are backed up first (copies),
    each final is written via <final>.companion_tmp + os.replace (atomic per file).
    Any error -> rollback to the exact previous state, then BuildStop(FAIL).
    """
    finals = [f for _, f in pairs]
    before = state_of(finals)
    present = [f for f in finals if before[f] is not None]
    if present and not overwrite:
        raise BuildStop(CANCELLED, "outputs_exist", "delivery already exists (overwrite not requested)", present)
    done, backups = [], {}
    try:
        for f in present:  # backup = copy: the export stays intact until each file is replaced
            b = os.path.join(backup_dir, os.path.splitdrive(f)[1].lstrip("\\/"))
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(f, b)
            backups[f] = b
        for i, (src, dst) in enumerate(pairs):
            if fault_after is not None and i >= fault_after:
                raise OSError(f"injected publish fault after {fault_after} file(s) (test hook)")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".companion_tmp"
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
            done.append(dst)
        record.published = [{"path": d, "bytes": os.path.getsize(d), "replaced": d in backups} for d in done]
        return {"published": len(done), "backed_up": len(backups), "backup_dir": backup_dir if backups else None}
    except Exception as e:  # rollback: restore every touched final to its previous state
        rb_errors = []
        for dst in done:
            try:
                if dst in backups:
                    shutil.copy2(backups[dst], dst + ".companion_tmp")
                    os.replace(dst + ".companion_tmp", dst)
                else:
                    os.remove(dst)
            except Exception as e2:  # noqa: BLE001 -- keep going, report all
                rb_errors.append(f"{dst}: {e2}")
        for _, dst in pairs:
            if os.path.exists(dst + ".companion_tmp"):
                os.remove(dst + ".companion_tmp")
        after = state_of(finals)
        restored = after == before
        record.extra["rollback"] = {"error": str(e), "files_touched": len(done), "restored_exactly": restored,
                                    "rollback_errors": rb_errors}
        raise BuildStop(FAIL, "publish_failed",
                        f"publish failed ({e}); rollback {'restored the previous delivery exactly' if restored else 'INCOMPLETE'}",
                        record.extra["rollback"])

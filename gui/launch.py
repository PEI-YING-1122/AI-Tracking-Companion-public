"""Start the Artist GUI from the Windows launcher (pythonw: no console).

Keeps errors visible without a console: stderr goes to
%LOCALAPPDATA%\\AI_Tracking_Companion\\gui_last_run.log, and a failure to start
(missing package, broken environment, crash before the window opens) is shown in a
plain Windows message box with that log's location.  The GUI itself is unchanged.
"""
import os
import sys
import traceback

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "AI_Tracking_Companion")
LOG = os.path.join(LOG_DIR, "gui_last_run.log")


def _message_box(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "AI Tracking Companion", 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001 -- nothing else left to report with
        pass


def main():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        sys.stderr = open(LOG, "w", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = sys.stderr
    except OSError:
        pass
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import companion_gui
        companion_gui.main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 -- show anything that stops the GUI from starting
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        _message_box("AI Tracking Companion could not start.\n\n" + tb.strip().splitlines()[-1]
                     + f"\n\nDetails: {LOG}\nRun setup.bat again or send the details to the TD.")
        sys.exit(1)


if __name__ == "__main__":
    main()

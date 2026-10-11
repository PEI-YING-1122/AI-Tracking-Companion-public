@echo off
rem AI Tracking Companion -- double-click to open the Artist GUI.
rem Uses the Companion's own environment (.venv next to this file); system PATH is not used or changed.
setlocal
set "HERE=%~dp0"
set "PYW=%HERE%.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo AI Tracking Companion: Python environment not found:
  echo   %HERE%.venv
  echo Create it once in this folder:  uv venv   then   uv pip install -e ".[gui]"
  pause
  exit /b 1
)
start "AI Tracking Companion" "%PYW%" "%HERE%gui\companion_gui.py" %*

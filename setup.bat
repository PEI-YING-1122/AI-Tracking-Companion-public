@echo off
rem AI Tracking Companion -- one-time setup on a workstation (run again after moving the folder).
rem Creates the private Python environment inside this folder:
rem   .python\   Python 3.11.14 (managed by uv, local to this folder)
rem   .venv\     the Companion environment (requirements-lock.txt)
rem Nothing is installed system-wide; PATH is not changed.
rem Needs uv: tools\uv.exe in this folder, or uv on PATH.
rem Offline: put the wheels of requirements-lock.txt into wheels\ (used instead of the internet).
setlocal
set "HERE=%~dp0"
set "PAUSE=pause"
if /i "%~1"=="/nopause" set "PAUSE=rem"
set "UV="
if exist "%HERE%tools\uv.exe" set "UV=%HERE%tools\uv.exe"
if not defined UV (
  where uv >nul 2>&1 && set "UV=uv"
)
if not defined UV (
  echo uv was not found: put uv.exe into "%HERE%tools\" or install uv.
  %PAUSE%
  exit /b 1
)
set "UV_PYTHON_INSTALL_DIR=%HERE%.python"
set "UV_PYTHON_PREFERENCE=only-managed"
set "SRC="
if exist "%HERE%wheels\" set "SRC=--no-index --find-links "%HERE%wheels""

echo [1/4] Python 3.11.14
"%UV%" python install 3.11.14 || goto failed
echo [2/4] environment .venv
"%UV%" venv --clear --python 3.11.14 "%HERE%.venv" || goto failed
echo [3/4] packages (requirements-lock.txt)
"%UV%" pip install --python "%HERE%.venv\Scripts\python.exe" %SRC% -r "%HERE%requirements-lock.txt" || goto failed
echo [4/4] check
"%HERE%.venv\Scripts\python.exe" -c "import numpy, cv2, PySide6; print('numpy', numpy.__version__, '| opencv', cv2.__version__, '| PySide6', PySide6.__version__)" || goto failed

if not exist "%HERE%configs\site.json" (
  copy "%HERE%configs\site.example.json" "%HERE%configs\site.json" >nul
  echo.
  echo configs\site.json was created from the example: set the Houdini, Maya, Nuke, ffmpeg
  echo and AI Tracking locations of this computer in it before the first build.
)
echo.
echo Setup complete. Start the Companion with AI_Tracking_Companion.bat
%PAUSE%
exit /b 0

:failed
echo.
echo Setup failed (see the messages above).
%PAUSE%
exit /b 1

@echo off
rem AI Tracking Companion -- one-time setup on a workstation (run again after moving the folder).
rem Creates the private Python environment inside this folder:
rem   .python\   Python 3.11.14 (managed by uv, local to this folder)
rem   .venv\     the Companion environment (requirements-lock.txt)
rem Nothing is installed system-wide; PATH is not changed.
rem Needs uv: tools\uv.exe in this folder, or uv on PATH.
rem Offline: put the wheels of requirements-lock.txt into wheels\ (used instead of the internet).
rem The Companion must be on a LOCAL disk (e.g. C:\Tools\AI_Tracking_Companion_v0.2.x): uv's managed
rem Python cannot be installed on mapped network drives / NAS / restricted shares (Access denied).
rem   setup.bat [/nopause] [/check-location]   (/check-location: only the local-disk check)
setlocal
set "HERE=%~dp0"
set "PAUSE=pause"
set "ONLYCHECK="
for %%A in (%*) do (
  if /i "%%~A"=="/nopause" set "PAUSE=rem"
  if /i "%%~A"=="/check-location" set "ONLYCHECK=1"
)
rem ---- local disk check (UNC path or mapped network drive -> blocked) ----
if "%HERE:~0,2%"=="\\" goto netdrive
powershell -NoProfile -NonInteractive -Command "if (([System.IO.DriveInfo]'%HERE:~0,2%').DriveType -eq 'Network') { exit 1 } else { exit 0 }" >nul 2>&1
if "%errorlevel%"=="1" goto netdrive
if defined ONLYCHECK (
  echo Local disk: OK  "%HERE%"
  exit /b 0
)
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

echo.
echo Setup complete.
if not exist "%HERE%configs\site.json" (
  echo Next: Workstation Setup finds Houdini, Maya, Nuke, FFmpeg and AI Tracking on this computer
  echo and writes configs\site.json  ^(Configure_Companion.bat; no JSON editing needed^).
  if /i not "%PAUSE%"=="rem" call "%HERE%Configure_Companion.bat"
) else (
  echo To change tool locations later: Configure_Companion.bat
)
echo Start the Companion with AI_Tracking_Companion.bat
%PAUSE%
exit /b 0

:netdrive
echo.
echo Companion runtime must be installed on a local disk.
echo This folder is on a network / mapped drive or share:
echo   "%HERE%"
echo Copy the whole Companion folder to a local disk, for example
echo   C:\Tools\AI_Tracking_Companion_v0.2.x   or   D:\Tools\AI_Tracking_Companion_v0.2.x
echo and run setup.bat there.  Do not run as Administrator to work around this.
%PAUSE%
exit /b 3

:failed
echo.
echo Setup failed (see the messages above).
%PAUSE%
exit /b 1

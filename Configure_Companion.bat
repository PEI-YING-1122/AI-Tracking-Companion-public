@echo off
rem AI Tracking Companion -- Workstation Setup: finds Houdini / Maya / Nuke / FFmpeg / AI Tracking
rem on this computer and writes configs\site.json (no JSON editing needed).
rem Run once after setup.bat, and again when a tool is installed / moved.
setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
set "PYW=%HERE%.venv\Scripts\pythonw.exe"
if not exist "%PYW%" goto noenv
"%PY%" -c "" 1>"%TEMP%\AI_Tracking_Companion_launcher.txt" 2>&1
if errorlevel 1 goto broken
start "AI Tracking Companion Workstation Setup" "%PYW%" "%HERE%gui\launch.py" --setup %*
exit /b 0

:noenv
echo AI Tracking Companion is not set up on this computer yet.
echo Run once:  setup.bat   (in "%HERE%")
echo.
pause
exit /b 1

:broken
echo AI Tracking Companion: the Python environment in
echo   "%HERE%.venv"
echo cannot start on this computer:
echo.
type "%TEMP%\AI_Tracking_Companion_launcher.txt"
echo.
echo Run setup.bat again (in "%HERE%"), or send this message to the TD.
echo.
pause
exit /b 1

@echo off
rem Full regression (PoC, workflow, transaction, project mode, v0.1.0 baseline).
rem Needs hython / mayapy / Nuke (configs\site.json) and the local test data.
cd /d "%~dp0.."
".venv\Scripts\python.exe" tests\run_all.py %*

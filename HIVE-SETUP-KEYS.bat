@echo off
REM Double-click (Windows): the API-key walkthrough on its own (add / replace / re-test keys).
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% -m hive setup
%PY% -m hive doctor
pause

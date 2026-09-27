@echo off
REM Double-click (Windows) to start the Hive. First start walks you through every API key.
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% --version >nul 2>nul || (echo Python 3.10+ is not installed. Get it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) & pause & exit /b 1)
%PY% -m hive start
pause

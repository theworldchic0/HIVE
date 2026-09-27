@echo off
REM Double-click (Windows) to start the Hive: Fib Bee watcher + Trader Bee loop + UI
cd /d "%~dp0"
start "" http://127.0.0.1:8790
python -m hive start
pause

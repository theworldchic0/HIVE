import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'hive_market_direction.py'
def run(*args): return subprocess.run([sys.executable,str(SCRIPT),*args],cwd=ROOT,capture_output=True,text=True)
def test_context_json(): json.loads(run('context').stdout)
def test_check_has_state(): assert run('check').stdout.strip() in {'REFRESH_REQUIRED','STALE','NO_CHANGE'}

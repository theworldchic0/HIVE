import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/queen.py'

def run(*args): return subprocess.run([sys.executable,str(SCRIPT),*args],cwd=ROOT,capture_output=True,text=True,check=True)

def test_status():
    out=run('status').stdout
    data=json.loads(out)
    assert 'agents' in data
    assert any(a['agent_id']=='queen' for a in data['agents'])

def test_usage_and_event():
    run('usage','--agent','research_agent','--provider','test','--calls','2','--input-tokens','100','--output-tokens','50','--cache-hits','1')
    run('event','--agent','research_agent','--event-type','handoff','--success','false','--target','bottom_blueprint_observatory')
    data=json.loads(run('audit').stdout)
    row=next(x for x in data['agents'] if x['agent_id']=='research_agent')
    assert row['communication_failures']>=1

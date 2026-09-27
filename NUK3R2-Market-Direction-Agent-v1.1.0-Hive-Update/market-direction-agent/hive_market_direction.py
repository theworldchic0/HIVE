#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LATEST=ROOT/'shared_context/market_direction/latest.json'
ARCHIVE=ROOT/'shared_context/market_direction/archive'
def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def load():
    if not LATEST.exists(): return {'status':'MISSING'}
    return json.loads(LATEST.read_text())
def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(data,indent=2)+'\n'); os.replace(tmp,path)
def status(): print(json.dumps(load(),indent=2))
def context():
    d=load(); print(json.dumps({k:d.get(k) for k in ['snapshot_id','generated_at','expires_at','status','regime','final_signal','final_call','horizons','btc_context','risk_context','trigger_state','source_health','communication_health']},indent=2)); return 0 if d.get('status') not in {'MISSING','STALE'} else 2
def check():
    d=load();
    if d.get('status')=='MISSING' or not d.get('generated_at'): print('REFRESH_REQUIRED'); return 2
    dt=datetime.fromisoformat(d['generated_at'].replace('Z','+00:00')); age=(now()-dt).total_seconds()/3600
    if age>216: print('STALE'); return 3
    if d.get('trigger_state',{}).get('refresh_required'): print('REFRESH_REQUIRED'); return 4
    if age>168: print('REFRESH_REQUIRED'); return 5
    print('NO_CHANGE'); return 0
def publish(src):
    d=json.loads(Path(src).read_text()); prev=load(); t=now(); sid='MD-'+t.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    d.update({'snapshot_id':sid,'generated_at':iso(t),'expires_at':iso(t+timedelta(days=7)),'status':d.get('status','FRESH')})
    d.setdefault('communication_health',{'agent':'healthy','shared_context':'healthy'})
    if prev.get('snapshot_id'): save(ARCHIVE/(prev['snapshot_id']+'.json'),prev)
    save(LATEST,d); print(json.dumps(d,indent=2))
def run_full():
    p=os.environ.get('MARKET_DIRECTION_ENGINE_PATH')
    if not p: print('MARKET_DIRECTION_ENGINE_PATH is not set',file=sys.stderr); return 2
    return subprocess.call([sys.executable,str(Path(p)/'run.py'),'all'],cwd=p)
p=argparse.ArgumentParser(); p.add_argument('command',choices=['status','context','check','publish','run-full']); p.add_argument('--input'); a=p.parse_args()
if a.command=='status': status(); sys.exit(0)
if a.command=='context': sys.exit(context())
if a.command=='check': sys.exit(check())
if a.command=='publish':
    if not a.input: p.error('--input required');
    publish(a.input); sys.exit(0)
if a.command=='run-full': sys.exit(run_full())

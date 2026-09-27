#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,shutil
from datetime import date,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent; CFG=json.loads((ROOT/'config/bottom_blueprint.json').read_text()); CTX=ROOT/'shared_context/latest.json'; ARCH=ROOT/'shared_context/archive'; EVENTS=ROOT/'output/events'
for p in (ARCH,EVENTS): p.mkdir(parents=True,exist_ok=True)
def inclusive(a,b): return (date.fromisoformat(b)-date.fromisoformat(a)).days+1
def clock(now=None):
 d=now or date.today(); c=CFG['cycle']; s=date.fromisoformat(c['bottom_window_start']); e=date.fromisoformat(c['bottom_window_end']); ms=date.fromisoformat(c['momentum_window_start']); me=date.fromisoformat(c['momentum_window_end'])
 if d<s: state='PRE_BOTTOM_WINDOW'; day=0
 elif d<=e: state='BOTTOM_WINDOW_ACTIVE'; day=(d-s).days+1
 elif d<ms: state='POST_BOTTOM_PRE_MOMENTUM'; day=inclusive(c['bottom_window_start'],c['bottom_window_end'])
 elif d<=me: state='MOMENTUM_WINDOW_ACTIVE'; day=inclusive(c['bottom_window_start'],c['bottom_window_end'])
 else: state='POST_MOMENTUM_WINDOW'; day=inclusive(c['bottom_window_start'],c['bottom_window_end'])
 return {'date':d.isoformat(),'state':state,'bottom_window_day':day,'bottom_window_total_days':inclusive(c['bottom_window_start'],c['bottom_window_end']),'days_to_bottom_center':(date.fromisoformat(c['bottom_center'])-d).days,'days_to_momentum_center':(date.fromisoformat(c['momentum_center'])-d).days,'momentum_window_total_days':inclusive(c['momentum_window_start'],c['momentum_window_end'])}
def status():
 x=json.loads(CTX.read_text()); print(json.dumps({'agent_id':CFG['agent_id'],'snapshot_id':x['snapshot_id'],'clock':clock(),'cycle':CFG['cycle'],'step_2_rule':CFG['step_2_rule'],'experiment':'LIVE OUT-OF-SAMPLE TEST'},indent=2))
def snapshot():
 x=json.loads(CTX.read_text()); sid='BB-'+datetime.now().astimezone().strftime('%Y-%m-%d-%H%M%S'); shutil.copy2(CTX,ARCH/(x['snapshot_id']+'.json')); x['snapshot_id']=sid; x['captured_at']=datetime.now().astimezone().isoformat(); x['clock']=clock(); CTX.write_text(json.dumps(x,indent=2)); print(json.dumps(x,indent=2))
def verify():
 c=CFG['cycle']; checks=[('bottom_ordered',c['bottom_window_start']<=c['bottom_center']<=c['bottom_window_end']),('momentum_ordered',c['momentum_window_start']<=c['momentum_center']<=c['momentum_window_end']),('rule_45_days',CFG['step_2_rule']['required_consecutive_days']==45),('clock_valid',clock()['state'] in {'PRE_BOTTOM_WINDOW','BOTTOM_WINDOW_ACTIVE','POST_BOTTOM_PRE_MOMENTUM','MOMENTUM_WINDOW_ACTIVE','POST_MOMENTUM_WINDOW'})]; print(json.dumps({'ok':all(v for _,v in checks),'checks':checks},indent=2))
def add_candidate(path):
 d=json.loads(Path(path).read_text()); d.setdefault('received_at',datetime.now().astimezone().isoformat()); d.setdefault('observatory_clock',clock()); d.setdefault('blueprint_snapshot_id',json.loads(CTX.read_text())['snapshot_id']); out=EVENTS/(d.get('event_id','event')+'.json'); out.write_text(json.dumps(d,indent=2)); print(out)
def record_price(symbol,price,timestamp):
 d={'event_type':'market_observation','event_id':f'PRICE-{symbol}-{timestamp.replace(":","").replace("+","")}','observed_at':timestamp,'symbol':symbol,'price':price,'cycle_clock':clock()}; out=EVENTS/(d['event_id']+'.json'); out.write_text(json.dumps(d,indent=2)); print(out)
def main():
 p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True); s.add_parser('status'); s.add_parser('verify'); s.add_parser('snapshot'); a=s.add_parser('add-candidate'); a.add_argument('path'); a=s.add_parser('record-price'); a.add_argument('--symbol',required=True); a.add_argument('--price',required=True,type=float); a.add_argument('--timestamp',required=True); q=p.parse_args();
 if q.cmd=='status': status()
 elif q.cmd=='verify': verify()
 elif q.cmd=='snapshot': snapshot()
 elif q.cmd=='add-candidate': add_candidate(q.path)
 elif q.cmd=='record-price': record_price(q.symbol,q.price,q.timestamp)

if __name__=='__main__': main()

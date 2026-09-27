#!/usr/bin/env python3
import argparse, json, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DB=DATA/'queen.db'; SNAPSHOT=DATA/'queen_snapshot.json'
CONFIG=json.loads((ROOT/'config/queen.json').read_text()); REGISTRY=json.loads((ROOT/'config/agent_registry.json').read_text())
SCHEMA='''
CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,display_name TEXT NOT NULL,role TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'unknown',last_heartbeat REAL,last_success REAL,last_failure REAL,last_error TEXT,jobs_completed INTEGER DEFAULT 0,jobs_failed INTEGER DEFAULT 0,communication_failures INTEGER DEFAULT 0,metadata_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at REAL NOT NULL,agent_id TEXT NOT NULL,provider TEXT NOT NULL,operation TEXT DEFAULT '',calls INTEGER DEFAULT 1,input_tokens INTEGER DEFAULT 0,output_tokens INTEGER DEFAULT 0,estimated_cost_usd REAL,latency_ms REAL,cache_hits INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,query_hash TEXT DEFAULT '',metadata_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at REAL NOT NULL,agent_id TEXT NOT NULL,event_type TEXT NOT NULL,success INTEGER NOT NULL,target_agent TEXT DEFAULT '',correlation_id TEXT DEFAULT '',message TEXT DEFAULT '',metadata_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS recommendations(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at REAL NOT NULL,severity TEXT NOT NULL,category TEXT NOT NULL,recommendation TEXT NOT NULL,evidence_json TEXT DEFAULT '{}',status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS queue_observations(id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at REAL NOT NULL,queue_name TEXT NOT NULL,pending INTEGER DEFAULT 0,running INTEGER DEFAULT 0,failed INTEGER DEFAULT 0,oldest_pending_age_s REAL DEFAULT 0,metadata_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS source_outcomes(id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at REAL NOT NULL,agent_id TEXT NOT NULL,provider TEXT NOT NULL,signal_type TEXT DEFAULT '',confirmed INTEGER DEFAULT 0,lead_time_s REAL,metadata_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS weekly_reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at REAL NOT NULL,window_days INTEGER NOT NULL,report_json TEXT NOT NULL,status TEXT DEFAULT 'proposed');
CREATE TABLE IF NOT EXISTS change_proposals(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at REAL NOT NULL,category TEXT NOT NULL,title TEXT NOT NULL,problem TEXT NOT NULL,evidence_json TEXT NOT NULL,proposed_change TEXT NOT NULL,expected_optimization TEXT NOT NULL,risks TEXT NOT NULL,rollback TEXT NOT NULL,validation TEXT NOT NULL,status TEXT DEFAULT 'proposed',approved_at REAL,approved_by TEXT);
'''
def now(): return time.time()
def iso(ts=None): return datetime.fromtimestamp(ts or now(),timezone.utc).isoformat()
def db(): DATA.mkdir(exist_ok=True); c=sqlite3.connect(DB); c.executescript(SCHEMA); return c
def ensure_agents(c):
    for a in REGISTRY['agents']: c.execute('INSERT OR IGNORE INTO agents(id,display_name,role) VALUES(?,?,?)',(a['id'],a['display_name'],a['role']))
    c.commit()
def heartbeat(agent,status='healthy',message=''):
    c=db(); ensure_agents(c); t=now()
    if status=='healthy': c.execute('UPDATE agents SET status=?,last_heartbeat=?,last_success=?,last_error=NULL,jobs_completed=jobs_completed+1 WHERE id=?',(status,t,t,agent))
    else: c.execute('UPDATE agents SET status=?,last_heartbeat=?,last_error=? WHERE id=?',(status,t,message,agent))
    c.commit(); c.close(); snapshot()
def usage(args):
    c=db(); ensure_agents(c); t=now(); c.execute('INSERT INTO usage(observed_at,agent_id,provider,operation,calls,input_tokens,output_tokens,estimated_cost_usd,latency_ms,cache_hits,failures,query_hash,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(t,args.agent,args.provider,args.operation,args.calls,args.input_tokens,args.output_tokens,args.cost,args.latency_ms,args.cache_hits,args.failures,args.query_hash,args.metadata or '{}')); c.commit(); c.close(); snapshot()
def event(args):
    c=db(); ensure_agents(c); t=now(); ok=1 if args.success else 0; c.execute('INSERT INTO events(observed_at,agent_id,event_type,success,target_agent,correlation_id,message,metadata_json) VALUES(?,?,?,?,?,?,?,?)',(t,args.agent,args.event_type,ok,args.target,args.correlation_id,args.message,args.metadata or '{}'))
    if args.event_type=='handoff' and not ok: c.execute('UPDATE agents SET communication_failures=communication_failures+1 WHERE id=?',(args.agent,))
    if not ok: c.execute('UPDATE agents SET jobs_failed=jobs_failed+1,last_failure=?,last_error=? WHERE id=?',(t,args.message,args.agent))
    c.commit(); c.close(); snapshot()
def audit():
    c=db(); ensure_agents(c); t=now(); out=[]
    for a in c.execute('SELECT * FROM agents').fetchall():
        aid,name,role,status,last_hb,last_ok,last_fail,last_err,jc,jf,cf,meta=a; age=(t-last_hb) if last_hb else 1e9
        if status=='failed' or (jf>0 and age>CONFIG['health_thresholds']['yellow_max_age_seconds']): color='red'
        elif age>CONFIG['health_thresholds']['green_max_age_seconds'] or cf>=CONFIG['health_thresholds']['communication_error_threshold']: color='yellow'
        else: color='green'
        out.append({'agent_id':aid,'display_name':name,'role':role,'status':color,'last_heartbeat_age_s':round(age,1),'jobs_completed':jc,'jobs_failed':jf,'communication_failures':cf,'last_error':last_err})
    rows=c.execute('SELECT agent_id,provider,SUM(calls),SUM(input_tokens),SUM(output_tokens),SUM(cache_hits),SUM(failures),AVG(latency_ms) FROM usage GROUP BY agent_id,provider').fetchall()
    usage_rows=[{'agent_id':r[0],'provider':r[1],'calls':r[2],'input_tokens':r[3],'output_tokens':r[4],'cache_hits':r[5],'failures':r[6],'avg_latency_ms':round(r[7] or 0,1)} for r in rows]
    comm_fail=c.execute("SELECT COUNT(*) FROM events WHERE event_type='handoff' AND success=0 AND observed_at>?",(t-86400,)).fetchone()[0]
    dup=c.execute("SELECT COUNT(*) FROM (SELECT query_hash,COUNT(*) n FROM usage WHERE query_hash!='' AND observed_at>? GROUP BY query_hash HAVING n>1)",(t-86400,)).fetchone()[0]
    rec=[]
    if comm_fail: rec.append({'severity':'high' if comm_fail>=3 else 'medium','category':'communication','recommendation':'Inspect failed handoffs and requeue affected work.','evidence':{'failed_handoffs_24h':comm_fail}})
    if any(x['failures'] for x in usage_rows): rec.append({'severity':'medium','category':'provider_reliability','recommendation':'Route around failing providers and preserve cached context.','evidence':{'providers':[x for x in usage_rows if x['failures']]}})
    if dup: rec.append({'severity':'medium','category':'duplicate_searches','recommendation':'Increase cache reuse or deduplicate queue items before repeating identical provider searches.','evidence':{'duplicate_query_hash_groups_24h':dup}})
    if any(x['cache_hits']==0 and x['calls']>=5 for x in usage_rows): rec.append({'severity':'low','category':'efficiency','recommendation':'Review repeated provider calls with zero cache hits.','evidence':{'usage':usage_rows}})
    return {'timestamp_utc':iso(t),'agents':out,'usage':usage_rows,'open_recommendations':rec,'severity_basis':CONFIG['severity_basis']}
def optimize():
    report=audit(); c=db(); t=now()
    for r in report['open_recommendations']: c.execute('INSERT INTO recommendations(created_at,severity,category,recommendation,evidence_json) VALUES(?,?,?,?,?)',(t,r['severity'],r['category'],r['recommendation'],json.dumps(r['evidence'])))
    c.commit(); c.close(); snapshot(); return report
def snapshot(): SNAPSHOT.write_text(json.dumps(audit(),indent=2))
def weekly_review():
    report=audit(); c=db(); t=now(); start=t-7*86400; prev=start-7*86400
    def totals(a,b):
        r=c.execute("SELECT COALESCE(SUM(calls),0),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),COALESCE(SUM(cache_hits),0),COALESCE(SUM(failures),0),COALESCE(AVG(latency_ms),0) FROM usage WHERE observed_at>=? AND observed_at<?",(a,b)).fetchone()
        return {'calls':r[0],'input_tokens':r[1],'output_tokens':r[2],'cache_hits':r[3],'failures':r[4],'avg_latency_ms':round(r[5] or 0,1)}
    cur=totals(start,t); old=totals(prev,start)
    def delta(k):
        o=old[k]; n=cur[k]
        return None if o==0 else round((n-o)/o*100,1)
    duplicate_groups=c.execute("SELECT COUNT(*) FROM (SELECT query_hash FROM usage WHERE query_hash!='' AND observed_at>=? GROUP BY query_hash HAVING COUNT(*)>1)",(start,)).fetchone()[0]
    handoffs=c.execute("SELECT COUNT(*),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0) FROM events WHERE event_type='handoff' AND observed_at>=?",(start,)).fetchone()
    report.update({'review_type':'weekly_system_optimization','window_start_utc':iso(start),'window_end_utc':iso(t),'telemetry_current':cur,'telemetry_prior':old,'telemetry_change_pct':{k:delta(k) for k in cur},'duplicate_query_groups':duplicate_groups,'handoffs':{'total':handoffs[0],'failed':handoffs[1]},'research_directive':'Research current Claude Code architecture, subagents, agent teams, hooks, MCP, context/token optimization, testing and observability; recommend only evidence-backed changes.'})
    c.execute('INSERT INTO weekly_reviews(created_at,window_days,report_json,status) VALUES(?,?,?,?)',(t,7,json.dumps(report),'proposed'))
    for r in report['open_recommendations']:
        c.execute('INSERT INTO recommendations(created_at,severity,category,recommendation,evidence_json) VALUES(?,?,?,?,?)',(t,r['severity'],r['category'],r['recommendation'],json.dumps(r['evidence'])))
    c.commit(); c.close(); snapshot(); return report

def propose(category,title,problem,evidence,change,optimization,risks,rollback,validation):
    c=db(); t=now(); c.execute('INSERT INTO change_proposals(created_at,category,title,problem,evidence_json,proposed_change,expected_optimization,risks,rollback,validation) VALUES(?,?,?,?,?,?,?,?,?,?)',(t,category,title,problem,json.dumps(evidence),change,optimization,risks,rollback,validation)); c.commit(); c.close(); return {'status':'proposed','title':title,'created_at_utc':iso(t)}

def status(): print(json.dumps(audit(),indent=2))
def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True); s.add_parser('status'); s.add_parser('audit'); s.add_parser('optimize'); s.add_parser('weekly-review')
    h=s.add_parser('heartbeat'); h.add_argument('agent'); h.add_argument('--status',default='healthy'); h.add_argument('--message',default='')
    u=s.add_parser('usage'); u.add_argument('--agent',required=True); u.add_argument('--provider',required=True); u.add_argument('--operation',default=''); u.add_argument('--calls',type=int,default=1); u.add_argument('--input-tokens',type=int,default=0); u.add_argument('--output-tokens',type=int,default=0); u.add_argument('--cost',type=float,default=None); u.add_argument('--latency-ms',type=float,default=0); u.add_argument('--cache-hits',type=int,default=0); u.add_argument('--failures',type=int,default=0); u.add_argument('--query-hash',default=''); u.add_argument('--metadata',default='{}')
    e=s.add_parser('event'); e.add_argument('--agent',required=True); e.add_argument('--event-type',required=True); e.add_argument('--success',type=lambda x:x.lower()=='true',required=True); e.add_argument('--target',default=''); e.add_argument('--correlation-id',default=''); e.add_argument('--message',default=''); e.add_argument('--metadata',default='{}')
    args=p.parse_args(); {'status':status,'audit':lambda:print(json.dumps(audit(),indent=2)),'optimize':lambda:print(json.dumps(optimize(),indent=2)),'weekly-review':lambda:print(json.dumps(weekly_review(),indent=2)),'heartbeat':lambda:heartbeat(args.agent,args.status,args.message),'usage':lambda:usage(args),'event':lambda:event(args)}[args.cmd]()
if __name__=='__main__': main()

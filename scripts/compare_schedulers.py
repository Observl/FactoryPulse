"""Reproduce synthetic native Workers / production CP-SAT comparison."""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BUDGET_SECONDS = 15


def validate(f, result):
    """Recompute constraints from source snapshot, never trust returned totals."""
    source = {t['equipment_id']: t for t in f['tasks']}
    staff = {p['staff_id']: p for p in f['staff']}
    rows = result['scheduled']
    errors, intervals, usage, parts, seen = [], [], {}, {}, set()
    cost = hours = priority = person_hours = 0
    dt = datetime.fromisoformat
    overlap = lambda a,b,c,d: a < d and c < b
    for row in rows:
        key = row['equipment_id']
        if key not in source or key in seen:
            errors.append('unknown/duplicate task: '+key)
            continue
        seen.add(key)
        t = source[key]
        a,b = dt(row['start_at']),dt(row['end_at'])
        team = row['staff_ids']
        if len(team) != t['people'] or len(set(team)) != len(team): errors.append('team: '+key)
        if (b-a).total_seconds() != t['hours']*3600: errors.append('duration: '+key)
        if a < max(dt(f['now']),dt(f['start_at']),dt(t['window_start'])) or b > dt(t['window_end']): errors.append('window: '+key)
        for identifier in team:
            p = staff.get(identifier)
            if not p: errors.append('unknown staff'); continue
            if not set(t['required_skill'].split(',')).issubset(p['skills'].split(',')): errors.append('skill: '+key)
            if a < dt(p['shift_start']) or b > dt(p['shift_end']): errors.append('shift: '+key)
            usage[identifier] = usage.get(identifier,0)+t['hours']
        for o in f['orders']:
            if o['equipment_id']==key and overlap(a,b,dt(o['start_at']),dt(o['end_at'])): errors.append('production: '+key)
        for x,y,k,ids in intervals:
            if overlap(a,b,x,y) and (key==k or set(team)&set(ids)): errors.append('overlap: '+key)
        intervals.append((a,b,key,team))
        for p in t['spare_parts']: parts[p['part_name']]=parts.get(p['part_name'],0)+p['quantity']
        cost+=t['cost']; hours+=t['hours']; priority+=t['priority_weight']; person_hours+=t['hours']*len(team)
    if cost > f['budget']: errors.append('budget')
    if hours > f['max_hours']: errors.append('downtime')
    for k,v in usage.items():
        if v > staff[k]['available_hours']: errors.append('staff hours: '+k)
    for k,v in parts.items():
        if v > f['stock'].get(k,0): errors.append('stock: '+k)
    events = sorted([(a,len(ids)) for a,b,k,ids in intervals]+[(b,-len(ids)) for a,b,k,ids in intervals])
    count=0
    for _,delta in events:
        count+=delta
        if count > f['staff_limit']: errors.append('capacity')
    priority_counts={level:sum(source[k]['priority']==level for k in seen) for level in ['高','中','低']}
    missing=set(source)-seen
    explained={c.get('equipment_id') for c in result['conflicts']}
    if not missing.issubset(explained): errors.append('missing explanation')
    return dict(task_count=len(seen),coverage=len(seen)/len(source),priority_weight=priority,priority_counts=priority_counts,cost=cost,budget_utilization=cost/f['budget'] if f['budget'] else 0,maintenance_hours=hours,downtime_utilization=hours/f['max_hours'],person_hours=person_hours,staff_hours=usage,parts=parts,unscheduled=sorted(missing),hard_constraint_errors=errors)


def cp_worker(f):
    from ortools.sat.python import cp_model
    from backend.analytics import schedule_selected
    original=cp_model.CpSolver.solve
    statuses=[]
    def solve(self,model,*args,**kwargs):
        self.parameters.max_time_in_seconds=10
        self.parameters.num_search_workers=1
        self.parameters.random_seed=0
        status=original(self,model,*args,**kwargs)
        statuses.append(dict(status=self.status_name(status),objective=self.objective_value,best_bound=self.best_objective_bound,solver_wall_seconds=self.wall_time))
        return status
    cp_model.CpSolver.solve=solve
    tasks=copy.deepcopy(f['tasks'])
    for t in tasks:
        t['priority_score']=t['priority_weight']/10000
        for p in t['spare_parts']: p['available_quantity']=f['stock'].get(p['part_name'],0)
    begin=time.perf_counter()
    rows,conflicts=schedule_selected(tasks,f['staff'],f['orders'],f['start_at'],staff_limit=f['staff_limit'],allow_subset=True,budget=f['budget'],max_hours=f['max_hours'])
    return dict(scheduled=rows,conflicts=conflicts,solver_evidence=statuses,optimizer_status=statuses[-1]['status'] if statuses else 'PRECHECK_NO_CANDIDATES',algorithm_ms=(time.perf_counter()-begin)*1000)


def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--repeat',type=int,default=3);p.add_argument('--output',default='docs/evidence/scheduler-comparison.json');a=p.parse_args()
    if a.repeat < 1: p.error('--repeat must be positive')
    if a.worker:
        print(json.dumps(cp_worker(json.load(sys.stdin)),ensure_ascii=False));return
    if hasattr(os, 'sched_getaffinity'):
        cpu=min(os.sched_getaffinity(0)); os.sched_setaffinity(0,{cpu})
    fixture=ROOT/'tests/fixtures/scheduler-comparison.json'
    raw=fixture.read_bytes(); cases=json.loads(raw)
    report=dict(schema_version=1,source_ref='60336749ac7c84188c9e75eb85cb9209f1bb0c2f',fixture_sha256=hashlib.sha256(raw).hexdigest(),python=sys.version,node=subprocess.check_output(['node','--version'],text=True).strip(),platform=platform.platform(),cpu=platform.processor(),process_budget_seconds=BUDGET_SECONDS,cp_solver_seconds=10,repeat=a.repeat,runs=[])
    import ortools
    report['ortools']=ortools.__version__
    report['dependencies']={name:importlib.metadata.version(name) for name in ['ortools','absl-py','numpy','pandas','protobuf','typing-extensions','immutabledict','python-dateutil','tzdata']}
    report['source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['backend/analytics.py','backend/field_profiles.py','cloudflare/identity/work-orders.mjs','scripts/compare-workers.mjs','scripts/compare_schedulers.py']}
    report['cpu_affinity']=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None
    for f in cases:
        for repetition in range(a.repeat):
            # Alternate execution order to reduce systematic warm-up bias.
            for method in (['workers','cp_sat'] if repetition%2==0 else ['cp_sat','workers']):
                command=['node',str(ROOT/'scripts/compare-workers.mjs')] if method=='workers' else [sys.executable,__file__,'--worker']
                begin=time.perf_counter()
                try:
                    proc=subprocess.run(command,input=json.dumps(f),text=True,capture_output=True,timeout=BUDGET_SECONDS,cwd=ROOT,check=True)
                    result=json.loads(proc.stdout)
                except subprocess.TimeoutExpired:
                    result=dict(scheduled=[],conflicts=[dict(equipment_id=t['equipment_id'],reason='external process budget exceeded; no infeasibility claim') for t in f['tasks']],optimizer_status='PROCESS_TIMEOUT',algorithm_ms=None)
                record=dict(case=f['name'],repetition=repetition,method=method,elapsed_ms=(time.perf_counter()-begin)*1000,result=result)
                record['metrics']=validate(f,result)
                record['acceptance_errors']=[key for key,value in f['expected'][method].items() if record['metrics'][key]!=value]
                report['runs'].append(record)
    target=ROOT/a.output;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for f in cases:
        for method in ['workers','cp_sat']:
            rows=[r for r in report['runs'] if r['case']==f['name'] and r['method']==method]
            r=rows[0];print(f['name'],method,r['metrics']['task_count'],r['metrics']['priority_weight'],r['result']['optimizer_status'],round(statistics.median(x['elapsed_ms'] for x in rows),2),r['metrics']['hard_constraint_errors'])
    if any(r['metrics']['hard_constraint_errors'] or r['acceptance_errors'] for r in report['runs']): raise SystemExit('Independent constraint validation failed; see saved report')
    if any(r['result']['optimizer_status']=='PROCESS_TIMEOUT' for r in report['runs']): raise SystemExit('Incomplete comparison: process timeout')

if __name__=='__main__': main()

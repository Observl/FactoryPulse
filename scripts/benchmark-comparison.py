"""Compare legacy and current comparison paths on an isolated frozen-data database."""
import os,sys,json,time,tempfile,sqlite3,subprocess
from pathlib import Path
from contextlib import closing
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
runtime=tempfile.TemporaryDirectory(prefix='factorypulse-comparison-');os.environ['FACTORYPULSE_DATA_DIR']=runtime.name
with closing(sqlite3.connect(ROOT/'outputs/final-runtime/factorypulse.sqlite3')) as source,closing(sqlite3.connect(Path(runtime.name)/'factorypulse.sqlite3')) as target:source.backup(target)
from backend import main
# Historical implementation is read as data from this repository, never from external input.
legacy=subprocess.check_output(['git','show','HEAD:backend/main.py'],cwd=ROOT).decode('utf-8');start=legacy.index('def _compare_strategies_consistent(');end=legacy.index('\n@app.',start);code=legacy[start:end].replace('def _compare_strategies_consistent(','def legacy_comparison(',1)
namespace=dict(main.__dict__);exec(compile(code,'legacy-comparison','exec'),namespace)
base=datetime.now().replace(second=0,microsecond=0).isoformat(sep=' ')
original_schedule=main.schedule_selected
def frozen_schedule(*args,**kwargs):
    kwargs["start_at"]=base
    return original_schedule(*args,**kwargs)
main.schedule_selected=frozen_schedule;namespace['schedule_selected']=frozen_schedule
main.snapshot();scenario=main.rows('scenarios')[0]['scenario_id'];result={}
for name,function in [('before',namespace['legacy_comparison']),('after',main._compare_strategies_consistent)]:
 t=time.perf_counter();comparison=function(scenario,persist=False,executable=True);elapsed=time.perf_counter()-t
 result[name]={'seconds':elapsed,'strategies':[]}
 for item in comparison['strategies']:
  chosen=item['selected'];constraints=item['constraints'];cost=sum(row['cost'] for row in chosen);hours=sum(row['hours'] for row in chosen)
  assert cost<=constraints['budget']+.00001 and hours<=constraints['max_downtime_h']+.00001
  result[name]['strategies'].append({'strategy':item['strategy'],'tasks':len(chosen),'priority_sum':round(sum(row['priority_score'] for row in chosen),5),'cost':cost,'hours':hours,'status':item['optimizer_status']})
result['speedup']=result['before']['seconds']/max(result['after']['seconds'],.00001);result['scope']='same frozen dataset and fixed scheduling origin; local sample, not load certification'
for before,after in zip(result['before']['strategies'],result['after']['strategies']):assert (before['strategy'],before['tasks'],before['priority_sum'],before['cost'],before['hours'])==(after['strategy'],after['tasks'],after['priority_sum'],after['cost'],after['hours']),(before,after)
(ROOT/'outputs/comparison-performance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))

import gc
gc.collect()
runtime.cleanup()

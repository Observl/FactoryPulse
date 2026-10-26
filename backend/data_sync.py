"""Authenticated, revisioned read cache. D1 remains the sole business database."""
import asyncio
import hashlib
import json
import re
from collections import OrderedDict
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

DATA_INPUTS = ('records/equipment','records/readings','records/demo_risks','records/maintenance_rules','records/maintenance_history','records/orders','settings/dataset')

def refresh_rule_baselines(state,risks,number):
    """A changed rule score must not retrain an otherwise unchanged model."""
    devices=state['devices'];changed=None
    for identifier,item in devices.items():
        rule=number(risks.get(identifier,{}).get('risk_score'))
        if item.get('rule_risk')==rule:continue
        if changed is None:changed=dict(devices)
        updated={**item,'rule_risk':rule}
        if item.get('model_risk') is None and item.get('ewma_risk') is None:updated['combined_risk']=rule
        changed[identifier]=updated
    if changed is not None:state['devices']=changed
    return state

def dependencies(path):
    path = path.split('?', 1)[0].removeprefix('/api')
    if path == '/model/replay': return (*DATA_INPUTS, 'computed', 'prediction_runs')
    if path == '/overview': return (*DATA_INPUTS, 'computed', 'alerts')
    if path in ('/data-quality', '/data/summary', '/sync/status', '/model/evaluation', '/model/replay'): return (*DATA_INPUTS, 'computed')
    if path == '/work-orders': return ('work_orders', 'settings/dataset')
    if re.fullmatch(r'/work-orders/[^/]+/flow',path):return ('work_orders','audit_events','maintenance_events','inventory_stock','inventory_reservations','settings/dataset')
    if path in ('/maintenance/timeline','/maintenance/time-readiness','/operations/resource-occupancy'):return (*DATA_INPUTS,'records/staff','records/scenarios','work_orders','inventory_stock','inventory_reservations','settings/business')
    if path == '/alerts': return ('alerts', 'settings/dataset')
    if path == '/data/versions': return ('dataset_versions', 'settings/dataset')
    if path == '/audit': return ('audit_events',)
    match = re.fullmatch(r'/records/([a-z_]+)', path)
    if match: return ('records/' + match[1],)
    match = re.fullmatch(r'/equipment/[^/]+/(history|operations)', path)
    if match: return (*DATA_INPUTS, 'computed', 'maintenance_events', 'work_orders')
    if path == '/resources/inventory':return ('inventory_stock','inventory_reservations','settings/dataset')
    match = re.fullmatch(r'/resources/(staff|orders|scenarios|requirements)', path)
    if match: return ('records/' + ('maintenance_rules' if match[1]=='requirements' else match[1]), 'work_orders', 'settings/business')
    return None

def signature(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:32]

def delta(old, new, path=None):
    """Explicit set/remove operations; unchanged subtrees are omitted."""
    path = [] if path is None else path
    if old == new: return []
    if isinstance(old, dict) and isinstance(new, dict):
        result = [{'op':'remove','path':path+[key]} for key in old.keys()-new.keys()]
        for key, value in new.items():
            result.extend(delta(old[key], value, path+[key]) if key in old else [{'op':'set','path':path+[key],'value':value}])
        return result
    if isinstance(old, list) and isinstance(new, list):
        result = []
        for i in range(min(len(old), len(new))): result.extend(delta(old[i], new[i], path+[i]))
        result.extend({'op':'remove','path':path+[i]} for i in range(len(old)-1,len(new)-1,-1))
        result.extend({'op':'set','path':path+[i],'value':new[i]} for i in range(len(old),len(new)))
        return result
    return [{'op':'set','path':path,'value':new}]

def schema_statements(tables):
    """Additive migration, also executable against isolated SQL test fixtures."""
    if 'database_schema' in tables:
        # V2 installs normalized-table revision triggers and projection views
        # atomically with the schema; AFTER triggers cannot attach to SQL views.
        return []
    statements = [
      "CREATE TABLE IF NOT EXISTS fp_resource_revisions(resource TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0)",
      "CREATE TABLE IF NOT EXISTS fp_computed_freshness(dataset_id TEXT NOT NULL,view_key TEXT NOT NULL,input_revision INTEGER NOT NULL,PRIMARY KEY(dataset_id,view_key))",
    ]
    dataset_keys = "'last_sync_at','sync_status','source_name','source_date','source_url','record_count','device_count','data_origin','import_filename','sensor_catalog','data_lineage','sync_error'"
    def resource(table, prefix):
        if table == 'records': return f"'records/'||{prefix}.table_name"
        if table == 'settings': return f"CASE WHEN {prefix}.key IN ({dataset_keys}) THEN 'settings/dataset' WHEN {prefix}.key='business_revision' THEN 'settings/business' ELSE 'settings/config' END"
        return "'"+('computed' if table=='fp_computed_views' else table)+"'"
    for table in ('records','settings','alerts','work_orders','dataset_versions','maintenance_events','audit_events','fp_computed_views','inventory_stock','inventory_reservations','prediction_runs'):
        if table not in tables: continue
        for event, prefix in (('INSERT','NEW'),('UPDATE','NEW'),('DELETE','OLD')):
            # Content-identical UPSERTs must not create false revisions.
            same = ''
            if event=='UPDATE':
                fields = tables[table]
                same = ' WHEN ' + ' OR '.join(f'OLD."{f}" IS NOT NEW."{f}"' for f in fields)
            bump = f"INSERT INTO fp_resource_revisions(resource,revision) VALUES({resource(table,prefix)},1) ON CONFLICT(resource) DO UPDATE SET revision=revision+1;"
            if event=='UPDATE' and table=='records':
                bump += " INSERT INTO fp_resource_revisions(resource,revision) SELECT 'records/'||OLD.table_name,1 WHERE OLD.table_name<>NEW.table_name ON CONFLICT(resource) DO UPDATE SET revision=revision+1;"
            if event=='UPDATE' and table=='settings':
                bump += f" INSERT INTO fp_resource_revisions(resource,revision) SELECT {resource(table,'OLD')},1 WHERE ({resource(table,'OLD')})<>({resource(table,'NEW')}) ON CONFLICT(resource) DO UPDATE SET revision=revision+1;"
            statements.append(f'CREATE TRIGGER IF NOT EXISTS fp_sync_{table}_{event.lower()} AFTER {event} ON "{table}"{same} BEGIN {bump} END')
    inputs = ','.join("'"+key+"'" for key in DATA_INPUTS)
    stamp = f'(SELECT COALESCE(SUM(revision),0) FROM fp_resource_revisions WHERE resource IN ({inputs}))'
    if 'prediction_runs' in tables:
        statements.append('CREATE INDEX IF NOT EXISTS fp_prediction_dataset_time ON prediction_runs(dataset_version,created_at DESC)')
    if 'records' in tables:
        statements.append('CREATE VIEW IF NOT EXISTS fp_v_record_counts AS SELECT table_name,COUNT(*) AS record_count FROM records GROUP BY table_name')
    if 'settings' in tables and 'records' in tables:
        statements.append("CREATE VIEW IF NOT EXISTS fp_v_data_source AS SELECT MAX(CASE WHEN key='last_sync_at' THEN value END) AS dataset_version,MAX(CASE WHEN key='source_name' THEN value END) AS source_name,MAX(CASE WHEN key='source_date' THEN value END) AS source_date,COALESCE((SELECT record_count FROM fp_v_record_counts WHERE table_name='readings'),0) AS record_count,COALESCE((SELECT record_count FROM fp_v_record_counts WHERE table_name='equipment'),0) AS device_count FROM settings")
    if 'fp_computed_views' in tables:
        statements.append(f'INSERT OR IGNORE INTO fp_computed_freshness SELECT dataset_id,view_key,{stamp} FROM fp_computed_views')
        for event in ('INSERT','UPDATE'):
            statements.append(f'CREATE TRIGGER IF NOT EXISTS fp_computed_stamp_{event.lower()} AFTER {event} ON fp_computed_views BEGIN INSERT INTO fp_computed_freshness VALUES(NEW.dataset_id,NEW.view_key,{stamp}) ON CONFLICT(dataset_id,view_key) DO UPDATE SET input_revision=excluded.input_revision; END')
        statements.append(f"CREATE VIEW IF NOT EXISTS fp_v_processed_results AS SELECT c.dataset_id,c.view_key,c.content FROM fp_computed_views c JOIN fp_computed_freshness f USING(dataset_id,view_key) WHERE c.dataset_id=(SELECT value FROM settings WHERE key='last_sync_at') AND f.input_revision={stamp}")
    return statements

class ReadSync:
    def __init__(self, connect):
        self.connect=connect; self.snapshots=OrderedDict(); self.locks={}
    def revisions(self):
        with self.connect() as db:
            sql="SELECT resource,revision FROM fp_resource_revisions UNION ALL SELECT '__source__',value FROM settings WHERE key='last_sync_at'"
            rows=db.query(sql)['results'] if hasattr(db,'query') else db.execute(sql)
            values={row['resource']:row['revision'] for row in rows}
            database=getattr(getattr(db,'store',None),'config',{}).get('database_id','isolated-sql-fixture')
            values['__source__']=int(signature([database,values.get('__source__','')])[:13],16)
            return values
    def precomputed(self, request):
        path=request.url.path; query=request.query_params
        key={'/api/overview':'overview','/api/data-quality':'data-quality'}.get(path)
        if not key: return None
        try:
            with self.connect() as db:
                if key=='data-quality' and getattr(db,'schema_v2',False):
                    from .sql_reports import data_quality
                    return data_quality(db)
                row=db.execute('SELECT content FROM fp_v_processed_results WHERE view_key=?',(key,)).fetchone()
                if not row:return None
                value=json.loads(row['content'])
                if key=='overview':
                    limit=int(query.get('limit','500'))
                    if not 1<=limit<=2000:return None
                    states={r['equipment_id']:dict(r) for r in db.execute("SELECT * FROM alerts WHERE dataset_version=(SELECT value FROM settings WHERE key='last_sync_at') ORDER BY updated_at")}
                    value['devices']=[{**d,'alert_status':states[d['equipment_id']]['status'],'alert_note':states[d['equipment_id']]['note']} if d['equipment_id'] in states else d for d in value['devices'][:limit]]
                    value['returned_devices']=len(value['devices'])
                    value['counts'].update({r['table_name']:r['record_count'] for r in db.execute('SELECT * FROM fp_v_record_counts')})
                return value
        except (ValueError,KeyError):return None

async def cached_business_response(request, handler):
    state=getattr(request.app.state,'data_sync',None)
    deps=dependencies(request.url.path)
    if not state or request.method!='GET' or deps is None:return await handler()
    deps=('__source__',*deps)
    # This helper is called only after the normal session/role middleware succeeds.
    from .security import principal
    user=principal() or {}
    identity=(str(user.get('user_id','isolated-test')),user.get('version'),user.get('role'))
    path=request.url.path+('?' + request.url.query if request.url.query else '')
    cache_key=(identity,path)
    lock=state.locks.setdefault(cache_key,asyncio.Lock())
    try:
      async with lock:
        revisions=await run_in_threadpool(state.revisions)
        subset={key:revisions.get(key,0) for key in deps}
        etag='"'+signature([identity,path,subset])+'"'
        headers={'ETag':etag,'Cache-Control':'private, no-cache','Vary':'Cookie','X-FP-Revisions':json.dumps(subset,separators=(',',':'))}
        if request.headers.get('if-none-match')==etag:return Response(status_code=304,headers=headers)
        versions=state.snapshots.get(cache_key,[])
        current=next((body for tag,body in versions if tag==etag),None)
        if current is None:
            try:current=await run_in_threadpool(state.precomputed,request)
            except Exception:current=None  # Older deployments can still use their normal endpoint.
            if current is None:
                response=await handler()
                if response.status_code!=200 or 'application/json' not in response.headers.get('content-type',''):return response
                if hasattr(response,'body_iterator'):
                    content=b''.join([chunk if isinstance(chunk,bytes) else chunk.encode() async for chunk in response.body_iterator])
                else:content=response.body
                current=json.loads(content)
            after=await run_in_threadpool(state.revisions)
            if any(after.get(key,0)!=subset[key] for key in deps):
                # Never label a mixed-generation computation as a reusable snapshot.
                return JSONResponse(current,headers={'Cache-Control':'no-store'})
            versions=[(etag,current)]+versions[:2]
            state.snapshots[cache_key]=versions;state.snapshots.move_to_end(cache_key)
            while len(state.snapshots)>96:state.snapshots.popitem(last=False)
            # Bound processed payload memory independently of the number of query URLs.
            while len(state.snapshots)>1 and sum(len(json.dumps(items)) for items in state.snapshots.values())>32_000_000:
                state.snapshots.popitem(last=False)
        base=request.headers.get('x-fp-delta-base')
        previous=next((body for tag,body in versions if tag==base),None)
        if previous is not None and base!=etag:
            patch={'format':'fp-delta-v1','base':base,'patch':delta(previous,current)}
            if len(json.dumps(patch))<len(json.dumps(current))*.85:
                headers['X-FP-Delta']='1';return JSONResponse(patch,headers=headers)
        return JSONResponse(current,headers=headers)
    except Exception as error:
        # Missing migration is not evidence of "unchanged". Preserve the old API behavior.
        if 'fp_resource_revisions' in str(error):return await handler()
        raise
    finally:
        if not lock.locked() and not getattr(lock,'_waiters',None):state.locks.pop(cache_key,None)

def install_data_sync(app,connect):
    state=ReadSync(connect);app.state.data_sync=state
    @app.get('/api/data/revisions')
    async def revisions(request:Request):
        try:values=await run_in_threadpool(state.revisions)
        except Exception:raise HTTPException(503,'数据版本视图尚未安装') from None
        from .security import principal
        user=principal() or {}
        identity=f"{user.get('user_id','isolated-test')}:{user.get('version')}:{user.get('role')}"
        tag='"'+signature([identity,values])+'"';headers={'ETag':tag,'Cache-Control':'private, no-cache','Vary':'Cookie'}
        if request.headers.get('if-none-match')==tag:return Response(status_code=304,headers=headers)
        return JSONResponse({'schema':1,'identity':identity,'resources':values},headers=headers)
    @app.get('/api/data/summary')
    def summary():
        with connect() as db:
            row=db.execute('SELECT * FROM fp_v_data_source').fetchone()
            return dict(row) if row else {}

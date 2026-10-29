"""SQL projections/writes for existing business APIs on the normalized V2 facts.

Legacy names are views, not duplicate storage. Deterministic calculations execute
inside SQL. Model artifacts are immutable historical computation evidence.
"""
from .database_v2 import INPUTS, OPERATIONS

AUXILIARY = {
 'settings':('business_settings', ['key','value'], ['key']),
 'fp_business_revision':('business_write_revision',['id','revision','commit_nonce'],['id']),
 'fp_business_guard':('business_write_guard',['id'],['id']),
 'fp_db_metadata':('database_metadata',['key','value'],['key']),
 'fp_resource_revisions':('data_resource_revisions',['resource','revision'],['resource']),
 'fp_datasets':('source_datasets',['dataset_id','manifest','source_date','ready'],['dataset_id']),
 'fp_dataset_records':('source_dataset_records',['dataset_id','table_name','row_index','equipment_id','content'],['dataset_id','table_name','row_index']),
 'fp_app_settings':('application_settings',['key','value'],['key']),
 'dataset_versions':('dataset_archives',['version','metadata','archived_at'],['version']),
 'archived_records':('dataset_archive_records',['version','table_name','row_index','content'],['version','table_name','row_index']),
 'import_jobs':('import_tasks',['job_id','content'],['job_id']),
 'agent_sessions':('assistant_sessions',['id','owner','content'],['id']),
 'agent_runs':('assistant_runs',['id','session_id','content'],['id']),
 'agent_permissions':('assistant_permission_requests',['id','session_id','content'],['id']),
 'agent_memory':('assistant_memories',['id','owner','content'],['id']),
 'schema_migrations':('schema_change_history',['version','name','applied_at','from_version'],['version']),
}
KEYS = {'records':['table_name','row_index']}
for old,(_,cols,_) in OPERATIONS.items():
 KEYS[old] = ['scope','part_name'] if old=='inventory_stock' else ['work_order_id','part_name'] if old=='inventory_reservations' else [cols[0]]
KEYS.update({old:keys for old,(_,_,keys) in AUXILIARY.items()})
KEYS['fp_computed_views']=['dataset_id','view_key']

def utc(expr):
 return f"CASE WHEN {expr} IS NULL OR {expr}='' THEN NULL ELSE strftime('%Y-%m-%dT%H:%M:%fZ',{expr},CASE WHEN {expr} GLOB '*Z' OR substr({expr},-6,1) IN ('+','-') THEN '+0 hours' ELSE '-8 hours' END) END"

def insert_sql(table, columns, values, keys, condition=''):
 nonkeys=[c for c in columns if c not in keys]
 update='DO NOTHING' if not nonkeys else 'DO UPDATE SET '+','.join(f'"{c}"=excluded."{c}"' for c in nonkeys)
 return f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join(values)}) ON CONFLICT({",".join(keys)}) {update}'+condition+';'

def runtime_statements():
 s=[
  "CREATE TABLE business_write_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,commit_nonce TEXT)",
  "INSERT INTO business_write_revision VALUES(1,0,NULL)",
  "CREATE TABLE business_write_guard(id INTEGER PRIMARY KEY CONSTRAINT fp_business_guard_revision CHECK(id=1))",
  "CREATE TABLE database_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
  "INSERT INTO database_metadata VALUES('user_version','1')",
  "CREATE TABLE data_resource_revisions(resource TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0)",
  "CREATE TABLE source_datasets(dataset_id TEXT PRIMARY KEY,manifest TEXT NOT NULL,source_date TEXT NOT NULL,ready INTEGER NOT NULL DEFAULT 0)",
  "CREATE TABLE source_dataset_records(dataset_id TEXT NOT NULL,table_name TEXT NOT NULL,row_index INTEGER NOT NULL,equipment_id TEXT,content TEXT NOT NULL,PRIMARY KEY(dataset_id,table_name,row_index))",
  "CREATE TABLE application_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
  "CREATE TABLE dataset_archives(version TEXT PRIMARY KEY,metadata TEXT NOT NULL,archived_at TEXT NOT NULL)",
  "CREATE TABLE dataset_archive_records(version TEXT NOT NULL,table_name TEXT NOT NULL,row_index INTEGER NOT NULL,content TEXT NOT NULL,PRIMARY KEY(version,table_name,row_index))",
  "CREATE TABLE import_tasks(job_id TEXT PRIMARY KEY,content TEXT NOT NULL)",
  "CREATE TABLE assistant_sessions(id TEXT PRIMARY KEY,owner TEXT NOT NULL,content TEXT NOT NULL)",
  "CREATE TABLE assistant_runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,content TEXT NOT NULL)",
  "CREATE TABLE assistant_permission_requests(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,content TEXT NOT NULL)",
  "CREATE TABLE assistant_memories(id TEXT PRIMARY KEY,owner TEXT NOT NULL,content TEXT NOT NULL)",
  "CREATE TABLE schema_change_history(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL,from_version INTEGER NOT NULL)",
  "CREATE TABLE calculation_history(artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,dataset_id TEXT NOT NULL,result_type TEXT NOT NULL,input_revision INTEGER NOT NULL,evidence TEXT NOT NULL CHECK(json_valid(evidence)),created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
  "CREATE INDEX calculation_history_lookup ON calculation_history(dataset_id,result_type,input_revision,artifact_id DESC)",
  "CREATE TABLE external_risk_inputs(equipment_id TEXT PRIMARY KEY,risk_score REAL CHECK(risk_score BETWEEN 0 AND 1),data_origin TEXT NOT NULL,attributes TEXT NOT NULL DEFAULT '{}')",
  """CREATE VIEW v_sensor_training_readings AS
   WITH previous AS (SELECT s.*,LAG(failure) OVER(PARTITION BY equipment_id ORDER BY timestamp,reading_id) AS previous_failure FROM sensor_readings s),
   windows AS (SELECT p.*,
    MAX(julianday(timestamp)) OVER(PARTITION BY equipment_id) AS observed_end,
    MIN(CASE WHEN failure=1 AND previous_failure=0 THEN julianday(timestamp) END)
      OVER(PARTITION BY equipment_id ORDER BY timestamp,reading_id ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS next_failure,
    COALESCE(json_extract(attributes,'$.prediction_horizon_hours'),168) AS horizon_hours
    FROM previous p)
   SELECT w.*,CASE WHEN failure=0 AND julianday(timestamp)+horizon_hours/24.0<=observed_end
     AND NOT EXISTS(SELECT 1 FROM sensor_readings unknown WHERE unknown.equipment_id=w.equipment_id AND unknown.failure IS NULL
       AND unknown.timestamp>w.timestamp AND julianday(unknown.timestamp)<=julianday(w.timestamp)+horizon_hours/24.0)
    THEN CASE WHEN next_failure>julianday(timestamp) AND next_failure<=julianday(timestamp)+horizon_hours/24.0 THEN 1 ELSE 0 END END AS future_failure
   FROM windows w""",
 ]
 inputs="'records/readings','settings/dataset'"
 stamp=f'(SELECT COALESCE(SUM(revision),0) FROM data_resource_revisions WHERE resource IN ({inputs}))'
 # Project typed columns and custom source inputs as API JSON, not extra tables.
 branches=[]
 times={'timestamp','window_start','window_end','failure_at','failure_end','maintenance_date','shift_start','shift_end','start_at','end_at','due_at'}
 for logical,(table,key,fields) in INPUTS.items():
  s.append(f'ALTER TABLE {table} ADD COLUMN record_index INTEGER')
  s.append(f'CREATE UNIQUE INDEX {table}_record_index ON {table}(record_index) WHERE record_index IS NOT NULL')
  parts=[]
  for col in fields:
   value=f't."{col}"'
   if col in times:value=f"strftime('%Y-%m-%d %H:%M:%S',t.\"{col}\",'+8 hours')"
   parts.extend(["'"+col+"'",value])
  if logical=='maintenance_rules':
   parts.extend(["'maintenance_hours'","COALESCE(t.duration_override_h,t.inspection_duration_h+t.repair_duration_h)","'maintenance_cost_cny'","COALESCE(t.cost_override_cny,t.inspection_cost_cny+t.repair_cost_cny)","'spare_parts'","json(COALESCE((SELECT json_group_array(json_object('part_name',p.part_name,'quantity',p.quantity,'available_quantity',COALESCE(a.available_to_allocate,0))) FROM maintenance_required_parts p LEFT JOIN v_current_spare_part_availability a USING(part_name) WHERE p.equipment_id=t.equipment_id),'[]'))"])
  if logical=='maintenance_history':parts.extend(["'downtime_hours'","COALESCE(t.observed_downtime_h,(julianday(t.failure_end)-julianday(t.failure_at))*24.0)"])
  if logical=='readings':parts.extend(["'future_failure'",'t.future_failure'])
  body=f"json_patch(t.attributes,json_object({','.join(parts)}))"
  source='v_sensor_training_readings' if logical=='readings' else table
  # All migrated/inserted samples receive record_index, so the training view
  # need not expose an implementation rowid.
  index='t.record_index' if logical=='readings' else 'COALESCE(t.record_index,t.rowid-1)'
  branches.append(f"SELECT '{logical}' AS table_name,{index} AS row_index,{body} AS content FROM {source} t")
  cols=[*fields,'record_index','attributes'];values=[]
  for col in fields:
   expr=f"json_extract(NEW.content,'$.{col}')"
   if col in times:expr=utc(expr)
   # Array skills are kept as JSON text by json_extract, as in original input.
   values.append(expr)
  values.append('NEW.row_index')
  extra=list(fields)
  if logical=='readings':extra.append('future_failure')
  if logical=='maintenance_rules':extra+=['spare_parts','maintenance_hours','maintenance_cost_cny']
  if logical=='maintenance_history':extra.append('downtime_hours')
  values.append("json_remove(NEW.content,"+','.join("'$."+c+"'" for c in extra)+')')
  if logical=='maintenance_rules':
   cols+=['duration_override_h','cost_override_cny']
   values += ["CASE WHEN json_extract(NEW.content,'$.maintenance_hours')=json_extract(NEW.content,'$.inspection_duration_h')+json_extract(NEW.content,'$.repair_duration_h') THEN NULL ELSE json_extract(NEW.content,'$.maintenance_hours') END", "CASE WHEN json_extract(NEW.content,'$.maintenance_cost_cny')=json_extract(NEW.content,'$.inspection_cost_cny')+json_extract(NEW.content,'$.repair_cost_cny') THEN NULL ELSE json_extract(NEW.content,'$.maintenance_cost_cny') END"]
  if logical=='maintenance_history':
   cols+=['observed_downtime_h'];values += ["json_extract(NEW.content,'$.downtime_hours')"]
  body_sql=insert_sql(table,cols,values,[key])
  if logical=='maintenance_rules':
   body_sql+=f"DELETE FROM maintenance_required_parts WHERE equipment_id=json_extract(NEW.content,'$.{key}'); INSERT INTO maintenance_required_parts SELECT json_extract(NEW.content,'$.{key}'),json_extract(value,'$.part_name'),json_extract(value,'$.quantity') FROM json_each(NEW.content,'$.spare_parts');"
  # Triggers installed after the records UNION view is defined.
  s.append((logical,table,key,body_sql))
 branches.append("SELECT 'demo_risks',COALESCE(e.record_index,e.rowid-1),json_object('equipment_id',e.equipment_id,'risk_score',COALESCE(x.risk_score,r.rule_risk),'data_origin',COALESCE(x.data_origin,'SQL_SENSOR_RULE_REFERENCE')) FROM equipment e LEFT JOIN v_equipment_rule_risk r USING(equipment_id) LEFT JOIN external_risk_inputs x USING(equipment_id) WHERE COALESCE(x.risk_score,r.rule_risk) IS NOT NULL")
 # D1 limits compound SELECT terms more tightly than desktop SQLite. Each
 # subquery stays below that bound; no extra physical storage is introduced.
 groups=['SELECT * FROM ('+' UNION ALL '.join(branches[i:i+4])+')' for i in range(0,len(branches),4)]
 s.append('CREATE VIEW records AS '+' UNION ALL '.join(groups))
 deferred=[x for x in s if isinstance(x,tuple)];s=[x for x in s if isinstance(x,str)]
 # Real source rule from model_validation_data, explicitly NOT a model probability.
 s.append("CREATE VIEW v_equipment_rule_risk AS SELECT equipment_id,CASE WHEN data_origin='SYNTHETIC_CNC_MODEL_VALIDATION_V1' AND vibration_mm_s IS NOT NULL AND motor_current_a IS NOT NULL THEN ROUND(MIN(0.98,0.04+MAX(0,vibration_mm_s-2.2)*0.12+MAX(0,motor_current_a-9)*0.05),4) END AS rule_risk FROM v_equipment_latest_reading")
 for logical,table,key,body_sql in deferred:
  s.append(f"CREATE TRIGGER records_insert_{logical} INSTEAD OF INSERT ON records WHEN NEW.table_name='{logical}' BEGIN {body_sql} END")
  deletion=f'DELETE FROM {table} WHERE {key}=json_extract(OLD.content,\'$.{key}\');'
  if logical=='maintenance_rules':deletion="DELETE FROM maintenance_required_parts WHERE equipment_id=json_extract(OLD.content,'$.equipment_id');"+deletion
  s.append(f"CREATE TRIGGER records_delete_{logical} INSTEAD OF DELETE ON records WHEN OLD.table_name='{logical}' BEGIN {deletion} END")
  s.append(f"CREATE TRIGGER records_update_{logical} INSTEAD OF UPDATE ON records WHEN OLD.table_name='{logical}' AND NEW.table_name='{logical}' BEGIN {body_sql} END")
 s.append("CREATE TRIGGER records_reject_unknown INSTEAD OF INSERT ON records WHEN NEW.table_name NOT IN ("+','.join("'"+x+"'" for x in INPUTS)+",'demo_risks') BEGIN SELECT RAISE(ABORT,'Unknown logical record type'); END")
 risk_body="INSERT INTO external_risk_inputs VALUES(json_extract(NEW.content,'$.equipment_id'),json_extract(NEW.content,'$.risk_score'),COALESCE(json_extract(NEW.content,'$.data_origin'),'EXTERNAL_SOURCE'),json_remove(NEW.content,'$.equipment_id','$.risk_score','$.data_origin')) ON CONFLICT(equipment_id) DO UPDATE SET risk_score=excluded.risk_score,data_origin=excluded.data_origin,attributes=excluded.attributes;"
 for event in ('INSERT','UPDATE'):
  s.append(f"CREATE TRIGGER records_{event.lower()}_external_risk INSTEAD OF {event} ON records WHEN NEW.table_name='demo_risks' AND COALESCE(json_extract(NEW.content,'$.data_origin'),'') NOT IN ('SYNTHETIC_SENSOR_THRESHOLD_BASELINE','SQL_SENSOR_RULE_REFERENCE') BEGIN {risk_body} END")
 s.append("CREATE TRIGGER records_delete_external_risk INSTEAD OF DELETE ON records WHEN OLD.table_name='demo_risks' BEGIN DELETE FROM external_risk_inputs WHERE equipment_id=json_extract(OLD.content,'$.equipment_id'); END")
 # Source/demo scores are derived, never insert a second backing risk table.
 for old,(table,cols,payload) in OPERATIONS.items():
  keys=KEYS[old];viewcols=list(cols)
  if payload:viewcols.insert(2 if old=='work_orders' else len(cols)-1,'content')
  if old=='alerts':viewcols=['alert_id','equipment_id','status','note','updated_at','dataset_version','prediction_at','defer_until','version']
  merge=','.join("'"+c+"',"+c for c in cols)
  select=','.join(f'json_patch({payload},json_object({merge})) AS content' if c=='content' else c for c in viewcols)
  s.append(f'CREATE VIEW {old} AS SELECT {select} FROM {table}')
  targetcols=[c for c in viewcols if c!='content']+([payload] if payload else [])
  vals=['NEW.'+c for c in targetcols]
  if payload:
   vals[-1]='json_remove(NEW.content,'+','.join("'$."+c+"'" for c in cols)+')'
   if old=='work_orders':
    expr=vals[-1]
    for field in ('start_at','end_at','actual_start_at','actual_finish_at','deleted_at'):
     expr=f"json_set({expr},'$.{field}',{utc(f'''json_extract(NEW.content,'$.{field}')''')})"
    vals[-1]=expr
  body=insert_sql(table,targetcols,vals,keys)
  for event in ('INSERT','UPDATE'):
   s.append(f'CREATE TRIGGER compat_{old}_{event.lower()} INSTEAD OF {event} ON {old} BEGIN {body} END')
  cond=' AND '.join(f'{k}=OLD.{k}' for k in keys)
  s.append(f'CREATE TRIGGER compat_{old}_delete INSTEAD OF DELETE ON {old} BEGIN DELETE FROM {table} WHERE {cond}; END')
 for old,(table,cols,keys) in AUXILIARY.items():
  projection=f'SELECT {",".join(cols)} FROM {table}'
  if old=='settings':
   projection += " UNION ALL SELECT 'record_count',CAST(COUNT(*) AS TEXT) FROM sensor_readings UNION ALL SELECT 'device_count',CAST(COUNT(*) AS TEXT) FROM equipment"
  s.append(f'CREATE VIEW {old} AS '+projection)
  body=insert_sql(table,cols,['NEW.'+c for c in cols],keys)
  if old=='fp_datasets':body=insert_sql(table,cols,['COALESCE(NEW.ready,0)' if c=='ready' else 'NEW.'+c for c in cols],keys)
  when=" WHEN NEW.key NOT IN ('record_count','device_count')" if old=='settings' else ''
  for event in ('INSERT','UPDATE'):
   s.append(f'CREATE TRIGGER compat_{old}_{event.lower()} INSTEAD OF {event} ON {old}{when} BEGIN {body} END')
  cond=' AND '.join(f'{k}=OLD.{k}' for k in keys)
  s.append(f'CREATE TRIGGER compat_{old}_delete INSTEAD OF DELETE ON {old} BEGIN DELETE FROM {table} WHERE {cond}; END')
 s += [
  f"CREATE VIEW fp_computed_views AS SELECT c.dataset_id,c.result_type AS view_key,c.evidence AS content FROM calculation_history c WHERE c.input_revision={stamp} AND c.artifact_id=(SELECT MAX(x.artifact_id) FROM calculation_history x WHERE x.dataset_id=c.dataset_id AND x.result_type=c.result_type AND x.input_revision=c.input_revision)",
  f"CREATE TRIGGER calculation_evidence_insert INSTEAD OF INSERT ON fp_computed_views BEGIN INSERT INTO calculation_history(dataset_id,result_type,input_revision,evidence) VALUES(NEW.dataset_id,NEW.view_key,{stamp},NEW.content); END",
  f"CREATE TRIGGER calculation_evidence_update INSTEAD OF UPDATE ON fp_computed_views BEGIN INSERT INTO calculation_history(dataset_id,result_type,input_revision,evidence) VALUES(NEW.dataset_id,NEW.view_key,{stamp},NEW.content); END",
  "CREATE VIEW fp_computed_freshness AS SELECT c.dataset_id,c.result_type AS view_key,c.input_revision FROM calculation_history c JOIN fp_computed_views v ON v.dataset_id=c.dataset_id AND v.view_key=c.result_type AND v.content=c.evidence GROUP BY c.dataset_id,c.result_type,c.input_revision",
  "CREATE VIEW fp_v_processed_results AS SELECT * FROM fp_computed_views WHERE dataset_id=(SELECT value FROM business_settings WHERE key='last_sync_at')",
  "CREATE VIEW fp_v_record_counts AS SELECT * FROM ("+' UNION ALL '.join(f"SELECT '{name}' AS table_name,COUNT(*) AS record_count FROM {table}" for name,(table,_,_) in list(INPUTS.items())[:4])+") UNION ALL SELECT * FROM ("+' UNION ALL '.join(f"SELECT '{name}' AS table_name,COUNT(*) AS record_count FROM {table}" for name,(table,_,_) in list(INPUTS.items())[4:])+" UNION ALL SELECT 'demo_risks',COUNT(*) FROM equipment e LEFT JOIN v_equipment_rule_risk r USING(equipment_id) LEFT JOIN external_risk_inputs x USING(equipment_id) WHERE COALESCE(x.risk_score,r.rule_risk) IS NOT NULL)",
  "CREATE VIEW fp_v_data_source AS SELECT (SELECT value FROM business_settings WHERE key='last_sync_at') AS dataset_version,(SELECT value FROM business_settings WHERE key='source_name') AS source_name,(SELECT value FROM business_settings WHERE key='source_date') AS source_date,(SELECT COUNT(*) FROM sensor_readings) AS record_count,(SELECT COUNT(*) FROM equipment) AS device_count",
 ]
 resources={table:'records/'+name for name,(table,_,_) in INPUTS.items()}
 resources.update({table:old for old,(table,_,_) in OPERATIONS.items()})
 resources['maintenance_required_parts']='records/maintenance_rules'
 resources['business_settings']='settings/dataset'
 resources['dataset_archives']='dataset_versions'
 resources['calculation_history']='computed'
 resources['external_risk_inputs']='records/demo_risks'
 for table,resource in resources.items():
  for event in ('INSERT','UPDATE','DELETE'):
   identity='OLD' if event=='DELETE' else 'NEW'
   resource_expr="'"+resource+"'"
   if table=='business_settings':resource_expr=f"CASE WHEN {identity}.key IN ('last_sync_at','source_date','data_origin','sensor_catalog','field_profile_config') THEN 'settings/dataset' WHEN {identity}.key='business_revision' THEN 'settings/business' ELSE 'settings/config' END"
   s.append(f"CREATE TRIGGER revision_{table}_{event.lower()} AFTER {event} ON {table} WHEN (SELECT migration_state FROM database_schema WHERE version=2)='ready' BEGIN INSERT INTO data_resource_revisions(resource,revision) VALUES({resource_expr},1) ON CONFLICT(resource) DO UPDATE SET revision=revision+1; END")
 from pathlib import Path
 analysis=Path(__file__).resolve().parents[1]/'deploy/d1-business-v2-analysis.sql'
 s.extend(part.strip() for part in analysis.read_text(encoding='utf-8').split(';') if part.strip())
 indexes=Path(__file__).resolve().parents[1]/'deploy/d1-read-indexes.sql'
 s.extend(part.strip() for part in indexes.read_text(encoding='utf-8').split(';') if part.strip())
 return s

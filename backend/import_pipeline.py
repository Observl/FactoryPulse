"""Staged, cancellable imports. Only an explicit commit replaces live records."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .smart_import import STANDARD_FIELDS, STANDARD_UNITS, iter_table_file, normalize_rows
from .field_profiles import PROFILES, custom_key, is_custom, is_sensor, leakage_column, future_outcome_column


class ColumnChoice(BaseModel):
    source_column:str
    target_field:str=""
    source_unit:str="standard"
    use_for_prediction:bool=True
    custom_unit:str=Field(default="",max_length=40)

class DeviceProfile(BaseModel):
    equipment_id:str=Field(min_length=1,max_length=100)
    profile_id:str="generic"
    feature_fields:list[str] | None=None


class PreviewRequest(BaseModel):
    upload_id:str
    mapping:list[ColumnChoice]
    default_equipment_id:str=Field(default="",max_length=100)
    profile_id:str="generic"
    device_profiles:list[DeviceProfile]=Field(default_factory=list,max_length=1000)


class CommitRequest(BaseModel):
    replace_existing:bool
    expected_dataset_version:str


class RestoreRequest(BaseModel):
    confirmed:bool
    expected_dataset_version:str


def convert_unit(value, target, unit):
    if target=="timestamp" and value not in (None,"") and unit in {"unix_s","unix_ms"}:
        return datetime.fromtimestamp(float(value)/(1000 if unit=="unix_ms" else 1),timezone.utc).isoformat()
    if value in (None,"") or unit in ("","standard",STANDARD_UNITS.get(target)): return value
    number=float(value)
    conversions={
        ("process_temperature_k","℃"):lambda x:x+273.15,
        ("oil_temperature_c","K"):lambda x:x-273.15,
        ("vibration_g","m/s²"):lambda x:x/9.80665,
        ("vibration_peak_g","m/s²"):lambda x:x/9.80665,
        ("vibration_mm_s","m/s"):lambda x:x*1000,
        ("motor_current_a","mA"):lambda x:x/1000,
        ("tool_wear_min","h"):lambda x:x*60,
        ("air_temperature_k","℃"):lambda x:x+273.15,
        ("voltage_v","mV"):lambda x:x/1000,
        ("power_kw","W"):lambda x:x/1000,
        ("flow_m3_h","L/min"):lambda x:x*.06,
        ("displacement_mm","m"):lambda x:x*1000,
        ("operating_hours","min"):lambda x:x/60,
    }
    if target in {"tp2_bar","tp3_bar","reservoirs_bar","pressure_bar"}:
        conversions.update({(target,"kPa"):lambda x:x/100,(target,"MPa"):lambda x:x*10})
    if (target,unit) not in conversions: raise ValueError(f"不支持将 {unit} 换算为 {target} 的标准单位")
    return conversions[(target,unit)](number)


def install_import_pipeline(app, connect, settings_get, lock, directory:Path):
    remote=os.environ.get("FACTORYPULSE_TEST_ALLOW_ANONYMOUS")!="1"
    from .d1_business import RemoteStage
    executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix="factorypulse-import")
    cancellations={}
    with connect() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS import_jobs (job_id TEXT PRIMARY KEY, content TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS dataset_versions (version TEXT PRIMARY KEY, metadata TEXT NOT NULL, archived_at TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS archived_records (version TEXT NOT NULL,table_name TEXT NOT NULL,row_index INTEGER NOT NULL,content TEXT NOT NULL,PRIMARY KEY(version,table_name,row_index))")
        for row in connection.execute("SELECT * FROM import_jobs"):
            job=json.loads(row["content"])
            missing_preview=job["status"]=="ready" and not (RemoteStage(job["job_id"]).exists() if remote else (directory/(job["job_id"]+"-stage.sqlite3")).is_file())
            if job["status"] in {"queued","validating"} or missing_preview:
                job.update(status="interrupted",message="导入预览临时文件缺失，请重新上传并校验；当前业务数据保留" if missing_preview else "服务重启中断了校验，请重新发起预览")
                connection.execute("UPDATE import_jobs SET content=? WHERE job_id=?",(json.dumps(job,ensure_ascii=False),row["job_id"]))

    def save(job):
        with lock,connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing=connection.execute("SELECT content FROM import_jobs WHERE job_id=?",(job["job_id"],)).fetchone()
            if existing:
                latest=json.loads(existing[0])
                if latest["status"]=="committed": return
                if latest["status"]=="cancelled":
                    job.update(status="cancelled",message=latest["message"])
            connection.execute("INSERT OR REPLACE INTO import_jobs VALUES (?,?)",(job["job_id"],json.dumps(job,ensure_ascii=False,default=str)))

    def get(identifier):
        try: identifier=str(uuid.UUID(identifier))
        except ValueError: raise HTTPException(422,"导入任务编号无效")
        with connect() as connection: row=connection.execute("SELECT content FROM import_jobs WHERE job_id=?",(identifier,)).fetchone()
        if not row: raise HTTPException(404,"导入任务不存在")
        return json.loads(row["content"])

    def work(job,source,payload):
        stage=directory/(job["job_id"]+"-stage.sqlite3")
        cancellation=cancellations[job["job_id"]]
        connection=None
        try:
            job.update(status="validating",message="逐批校验文件，尚未修改当前数据");save(job)
            connection=RemoteStage(job["job_id"]) if remote else sqlite3.connect(stage)
            # SQLite label derivation can outlast row parsing on large files.
            connection.set_progress_handler(lambda:int(cancellation.is_set()),1000)
            connection.execute("CREATE TABLE staged (row_index INTEGER PRIMARY KEY,equipment_id TEXT NOT NULL,timestamp TEXT NOT NULL,failure INTEGER,content TEXT NOT NULL,UNIQUE(equipment_id,timestamp))")
            choices={item.source_column:item.target_field for item in payload.mapping if item.target_field}
            default_features=[item.target_field for item in payload.mapping if item.use_for_prediction and is_sensor(item.target_field,STANDARD_FIELDS)]
            overrides={item.equipment_id:item for item in payload.device_profiles}
            count=0;errors=[];error_count=0;missing=0;checked=0
            for index,source_row in enumerate(iter_table_file(Path(source["upload_path"]),source["filename"])):
                if cancellation.is_set():
                    job.update(status="cancelled",message="已取消校验，当前数据未改变");save(job);return
                try:
                    prepared=dict(source_row)
                    for choice in payload.mapping:
                        if choice.target_field:
                            if choice.source_column not in source_row: raise ValueError(f"源字段 {choice.source_column} 不存在")
                            prepared[choice.source_column]=convert_unit(source_row.get(choice.source_column),choice.target_field,choice.source_unit)
                    row=normalize_rows([prepared],choices,payload.default_equipment_id)[0]
                    override=overrides.get(row["equipment_id"])
                    profile=override.profile_id if override else payload.profile_id
                    selected=(override.feature_fields if override and override.feature_fields is not None else
                              [field for field in default_features if profile=="generic" or field in PROFILES[profile]["fields"] or is_custom(field)] if override else default_features)
                    row.update(_equipment_profile=profile,_feature_fields=selected)
                    row["reading_id"]=f"IMPORT-{job['job_id'][:8]}-{index:09d}"
                    connection.execute("INSERT INTO staged VALUES (?,?,?,?,?)",(index,row["equipment_id"],row["timestamp"],row.get("failure"),json.dumps(row,ensure_ascii=False,allow_nan=False)))
                    for field in choices.values():
                        checked+=1
                        if row.get(field) in (None,""): missing+=1
                    count+=1
                except (ValueError,TypeError,sqlite3.IntegrityError) as exc:
                    error_count+=1
                    if len(errors)<30: errors.append({"line":index+2,"message":"设备和时间重复" if isinstance(exc,sqlite3.IntegrityError) else str(exc)[:300]})
                if (index+1)%500==0:
                    connection.commit();job.update(processed_rows=index+1,valid_rows=count,error_count=error_count,errors=errors);save(job)
            if cancellation.is_set():
                job.update(status="cancelled",message="已取消校验，当前数据未改变");save(job);return
            connection.commit()
            job.update(message="文件读取完成，正在校验故障时间窗口；尚未修改当前数据",processed_rows=count+error_count,valid_rows=count,error_count=error_count,errors=errors);save(job)
            # Derive event onsets only from observed transitions, and censor incomplete tails.
            connection.execute("CREATE TABLE onsets AS SELECT equipment_id,timestamp FROM (SELECT equipment_id,timestamp,failure,LAG(failure) OVER (PARTITION BY equipment_id ORDER BY timestamp) AS previous FROM staged) WHERE failure=1 AND previous=0")
            connection.execute("CREATE INDEX onset_time ON onsets(equipment_id,timestamp)")
            connection.execute("CREATE TABLE device_bounds AS SELECT equipment_id,MAX(timestamp) AS observed_end,SUM(failure IS NULL) AS unknown_labels FROM staged GROUP BY equipment_id")
            connection.execute("""UPDATE staged SET content=json_set(content,'$.future_failure',CASE
                WHEN failure IS NULL OR failure=1 OR (SELECT unknown_labels FROM device_bounds WHERE equipment_id=staged.equipment_id)>0
                  OR datetime(timestamp,'+168 hours')>(SELECT observed_end FROM device_bounds WHERE equipment_id=staged.equipment_id) THEN NULL
                ELSE EXISTS(SELECT 1 FROM onsets WHERE onsets.equipment_id=staged.equipment_id AND onsets.timestamp>staged.timestamp AND onsets.timestamp<=datetime(staged.timestamp,'+168 hours')) END)""")
            connection.execute("UPDATE staged SET content=json_set(content,'$.label_status',CASE WHEN json_type(content,'$.future_failure')='null' THEN 'unknown_or_already_failed' ELSE 'observed' END)")
            connection.commit()
            examples=[json.loads(row[0]) for row in connection.execute("SELECT content FROM staged ORDER BY timestamp LIMIT 10")]
            span=connection.execute("SELECT MIN(timestamp),MAX(timestamp),COUNT(DISTINCT equipment_id) FROM staged").fetchone()
            unknown=set(overrides)-{row[0] for row in connection.execute("SELECT DISTINCT equipment_id FROM staged")}
            if unknown:
                error_count+=len(unknown);errors.extend({"line":0,"message":"设备方案编号在文件中不存在："+value} for value in sorted(unknown)[:max(0,30-len(errors))])
            job.update(status="invalid" if error_count or not count else "ready",processed_rows=count+error_count,valid_rows=count,error_count=error_count,errors=errors,preview=examples,start_at=span[0],end_at=span[1],device_count=span[2],missing_rate=missing/max(checked,1),message="发现错误，修正源文件后重新校验；当前数据未改变" if error_count else "校验完成，请核对预览和数据替换范围后提交")
            if cancellation.is_set(): job.update(status="cancelled",message="已取消预览，当前数据未改变")
            save(job)
        except Exception as exc:
            if cancellation.is_set():job.update(status="cancelled",message="已取消校验，当前数据未改变")
            else:job.update(status="failed",message=f"校验失败，当前数据未改变：{type(exc).__name__}：{str(exc)[:200]}")
            save(job)
        finally:
            if connection: connection.close()
            cancellations.pop(job["job_id"],None)

    @app.post("/api/import/intelligent/preview")
    def preview(payload:PreviewRequest):
        try: upload_id=str(uuid.UUID(payload.upload_id))
        except ValueError: raise HTTPException(422,"上传会话无效")
        session=directory/(upload_id+".json")
        if not session.exists(): raise HTTPException(404,"上传会话不存在，请重新分析")
        source=json.loads(session.read_text(encoding="utf-8"))
        path=Path(source["upload_path"])
        if path.parent.resolve()!=directory.resolve() or not path.exists(): raise HTTPException(404,"上传文件不存在")
        targets=[item.target_field for item in payload.mapping if item.target_field]
        if payload.profile_id not in PROFILES or any(item.profile_id not in PROFILES for item in payload.device_profiles): raise HTTPException(422,"未知设备字段方案")
        if len({item.equipment_id for item in payload.device_profiles})!=len(payload.device_profiles): raise HTTPException(422,"同一设备只能配置一个字段方案")
        if len({item.source_column for item in payload.mapping})!=len(payload.mapping): raise HTTPException(422,"源字段不能重复配置")
        for item in payload.mapping:
            if item.target_field and item.target_field not in STANDARD_FIELDS and item.target_field!=custom_key(item.source_column): raise HTTPException(422,"存在未知目标字段")
            if item.target_field=="failure" and future_outcome_column(item.source_column): raise HTTPException(422,"未来结果或寿命字段不能映射为当前故障状态，请提供实际发生时的故障标记")
            if is_custom(item.target_field) and item.source_unit!="standard": raise HTTPException(422,"扩展指标保留原单位，请填写单位名称而非换算")
            if is_sensor(item.target_field,STANDARD_FIELDS) and item.use_for_prediction and leakage_column(item.source_column): raise HTTPException(422,"疑似结果或标签字段不能作为预测输入："+item.source_column)
        sensors={item.target_field for item in payload.mapping if is_sensor(item.target_field,STANDARD_FIELDS) and item.use_for_prediction}
        for item in payload.device_profiles:
            if item.feature_fields is not None and (len(item.feature_fields)!=len(set(item.feature_fields)) or not set(item.feature_fields)<=sensors): raise HTTPException(422,"设备方案只能选择已启用的数值指标")
        if "timestamp" not in targets: raise HTTPException(422,"必须指定采集时间字段")
        if "equipment_id" not in targets and not payload.default_equipment_id.strip(): raise HTTPException(422,"请指定设备编号字段，或填写这份单设备文件的设备编号")
        if len(targets)!=len(set(targets)): raise HTTPException(422,"同一指标不能映射多个源字段")
        identifier=str(uuid.uuid4())
        job={"job_id":identifier,"upload_id":upload_id,"filename":source["filename"],"status":"queued","processed_rows":0,"valid_rows":0,"error_count":0,"errors":[],"preview":[],"mapping":[item.model_dump() for item in payload.mapping],"profile_id":payload.profile_id,"device_profiles":[item.model_dump() for item in payload.device_profiles],"expected_dataset_version":settings_get("last_sync_at"),"created_at":datetime.now(timezone.utc).isoformat(),"message":"等待后台校验"}
        cancellations[identifier]=threading.Event();save(job);executor.submit(work,job,source,payload)
        return {"job_id":identifier,"status":"queued"}

    @app.get("/api/import/jobs/{identifier}")
    def job_status(identifier:str): return get(identifier)

    @app.post("/api/import/jobs/{identifier}/cancel")
    def cancel(identifier:str):
        job=get(identifier)
        with lock,connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest=json.loads(connection.execute("SELECT content FROM import_jobs WHERE job_id=?",(job["job_id"],)).fetchone()[0])
            if latest["status"]=="committed": raise HTTPException(409,"数据已提交，不能取消校验；请通过数据版本管理恢复")
            event=cancellations.get(job["job_id"])
            if event: event.set()
            latest.update(status="cancelled",message="已取消预览，当前数据未改变")
            connection.execute("UPDATE import_jobs SET content=? WHERE job_id=?",(json.dumps(latest,ensure_ascii=False),job["job_id"]))
        return {"status":"cancelled"}

    @app.post("/api/import/jobs/{identifier}/commit")
    def commit(identifier:str,payload:CommitRequest):
        job=get(identifier)
        if job["status"]=="committed": return job["result"]
        if job["status"]!="ready": raise HTTPException(409,"只有校验通过的预览才能提交")
        if not payload.replace_existing: raise HTTPException(422,"请明确确认替换当前监测数据")
        stage=directory/(job["job_id"]+"-stage.sqlite3")
        with lock,connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest=json.loads(connection.execute("SELECT content FROM import_jobs WHERE job_id=?",(job["job_id"],)).fetchone()[0])
            if latest["status"]=="committed": return latest["result"]
            if latest["status"]!="ready": raise HTTPException(409,"预览已取消或改变，请重新校验")
            if remote:
                checked=RemoteStage(job["job_id"])
                if not checked.exists(): raise HTTPException(409,"云端预览不存在，请重新校验")
                if checked.execute("SELECT COUNT(*) FROM staged").fetchone()[0]!=latest["valid_rows"]: raise HTTPException(409,"云端预览记录数已变化")
                connection.stage_prefix=checked.prefix
            else:
                if not stage.is_file(): raise HTTPException(409,"导入预览临时文件缺失，请重新上传并校验；当前数据未改变")
                try:
                    with closing(sqlite3.connect(stage.resolve().as_uri()+"?mode=ro",uri=True)) as checked:
                        if checked.execute("PRAGMA quick_check").fetchall()!=[("ok",)]: raise ValueError("预览文件完整性检查失败")
                        count=checked.execute("SELECT COUNT(*) FROM staged").fetchone()[0]
                        checked.execute("SELECT COUNT(*) FROM onsets").fetchone()
                        if count!=latest["valid_rows"]: raise ValueError("预览记录数已变化")
                except (sqlite3.Error,ValueError) as exc:
                    raise HTTPException(409,"导入预览临时文件损坏或不完整，请重新上传并校验；当前数据未改变") from exc
            current=connection.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
            current=current[0] if current else ""
            if current!=payload.expected_dataset_version or current!=job["expected_dataset_version"]: raise HTTPException(409,"当前数据已被更新，请重新预览以避免覆盖他人导入")
            now=datetime.now(timezone.utc).isoformat()
            metadata={row["key"]:row["value"] for row in connection.execute("SELECT * FROM settings WHERE key IN ('last_sync_at','source_name','source_date','data_origin','record_count','device_count','data_lineage','inventory_scope','sensor_catalog','field_profile_config')")}
            if current:
                connection.execute("INSERT OR IGNORE INTO dataset_versions VALUES (?,?,?)",(current,json.dumps(metadata,ensure_ascii=False),now))
                connection.execute("INSERT OR IGNORE INTO archived_records SELECT ?,table_name,row_index,content FROM records",(current,))
            if not remote:connection.execute("ATTACH DATABASE ? AS stage",(str(stage),))
            connection.execute("DELETE FROM records")
            connection.execute("INSERT INTO records SELECT 'readings',row_index,content FROM stage.staged")
            devices=connection.execute("SELECT equipment_id FROM stage.staged GROUP BY equipment_id ORDER BY equipment_id").fetchall()
            def insert(table,index,content): connection.execute("INSERT INTO records VALUES (?,?,?)",(table,index,json.dumps(content,ensure_ascii=False)))
            for index,device in enumerate(devices):
                identifier=device[0]
                last=json.loads(connection.execute("SELECT content FROM stage.staged WHERE equipment_id=? ORDER BY timestamp DESC LIMIT 1",(identifier,)).fetchone()[0])
                insert("equipment",index,{"equipment_id":identifier,"equipment_name":identifier,"equipment_type":last.get("equipment_type") or PROFILES[last.get("_equipment_profile","generic")]["label"],"field_profile":last.get("_equipment_profile","generic"),"prediction_features":last.get("_feature_fields",[]),"status":last.get("status") or ("故障" if last.get("failure")==1 else "待现场核对"),"production_line":last.get("production_line") or "未分配","data_origin":"USER_IMPORTED_OPERATIONAL"})
                insert("demo_risks",index,{"equipment_id":identifier,"risk_score":.98 if last.get("failure")==1 else .05,"data_origin":"OBSERVED_STATUS_BASELINE_NOT_PROBABILITY"})
                insert("maintenance_rules",index,{"equipment_id":identifier,"maintenance_cost_cny":None,"maintenance_hours":None,"configuration_status":"required","data_origin":"USER_INPUT_REQUIRED"})
            values={"sync_status":"synced","last_sync_at":now,"source_date":str(job.get("end_at") or "")[:10],"source_name":job["filename"],"source_url":"","record_count":job["valid_rows"],"device_count":len(devices),"sync_error":"","import_filename":job["filename"],"data_origin":"USER_IMPORTED_OPERATIONAL","data_lineage":"[]","restored_from":"","inventory_scope":now}
            values["sensor_catalog"]=json.dumps({item["target_field"]:{"label":STANDARD_FIELDS.get(item["target_field"],item["source_column"]),"unit":item.get("custom_unit","") if is_custom(item["target_field"]) else STANDARD_UNITS.get(item["target_field"],""),"source_column":item["source_column"]} for item in job["mapping"] if item["target_field"]},ensure_ascii=False)
            values["field_profile_config"]=json.dumps({"profile_id":job.get("profile_id","generic"),"devices":job.get("device_profiles",[])},ensure_ascii=False)
            connection.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)",[(key,str(value)) for key,value in values.items()])
            label_counts=connection.execute("SELECT COUNT(*),SUM(json_extract(content,'$.future_failure') IS NOT NULL),SUM(json_extract(content,'$.future_failure')=1) FROM stage.staged").fetchone()
            event_count=connection.execute("SELECT COUNT(*) FROM stage.onsets").fetchone()[0]
            suitability={"status":"not_validated","known_label_rows":int(label_counts[1] or 0),"positive_label_rows":int(label_counts[2] or 0),"observed_fault_onsets":event_count,"message":"尚未验证模型对本批设备的适用性；请在风险中心查看按时间划分的评估与证据限制。"}
            if not suitability["known_label_rows"]: suitability["message"]="没有可用于验证未来7天任务的完整观测标签；只能查看工况与规则证据，不能据此证明预测有效。"
            result={"success":True,"record_count":job["valid_rows"],"device_count":len(devices),"data_version":now,"start_at":job.get("start_at"),"end_at":job.get("end_at"),"model_suitability":suitability,"next_step":"先核对数据质量与模型适用性，再配置真实维护资源；导入成功不代表模型验证通过"}
            job.update(status="committed",result=result,message="数据已原子提交；旧版本已归档，工单与审计保留")
            connection.execute("UPDATE import_jobs SET content=? WHERE job_id=?",(json.dumps(job,ensure_ascii=False),job["job_id"]))
            connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("staged_import_committed",job["job_id"],json.dumps({"old_version":current,"new_version":now,"rows":job["valid_rows"],"mapping":job["mapping"]},ensure_ascii=False),now))
        return result

    @app.get("/api/data/versions")
    def versions():
        with connect() as connection:
            records=[]
            for row in connection.execute("SELECT * FROM dataset_versions ORDER BY archived_at DESC LIMIT 100"):
                metadata=json.loads(row["metadata"])
                records.append({"version":row["version"],"archived_at":row["archived_at"],"source_name":metadata.get("source_name","旧版本数据"),"source_date":metadata.get("source_date"),"record_count":metadata.get("record_count"),"device_count":metadata.get("device_count"),"data_origin":metadata.get("data_origin")})
        return {"current_version":settings_get("last_sync_at"),"records":records}

    @app.post("/api/data/versions/{version}/restore")
    def restore(version:str,payload:RestoreRequest):
        if not payload.confirmed: raise HTTPException(422,"请明确确认恢复这份历史数据")
        now=datetime.now(timezone.utc).isoformat()
        with lock,connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            saved=connection.execute("SELECT metadata FROM dataset_versions WHERE version=?",(version,)).fetchone()
            if not saved: raise HTTPException(404,"历史版本不存在")
            count=connection.execute("SELECT COUNT(*) FROM archived_records WHERE version=?",(version,)).fetchone()[0]
            if not count: raise HTTPException(409,"历史版本没有完整记录，不能恢复")
            current=connection.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
            current=current[0] if current else ""
            if current!=payload.expected_dataset_version: raise HTTPException(409,"当前数据已改变，请刷新版本列表后重试")
            metadata=json.loads(saved[0])
            metadata.setdefault("sensor_catalog","{}")
            metadata.setdefault("field_profile_config","{}")
            if current:
                old={row["key"]:row["value"] for row in connection.execute("SELECT * FROM settings WHERE key IN ('last_sync_at','source_name','source_date','data_origin','record_count','device_count','data_lineage','inventory_scope','sensor_catalog','field_profile_config')")}
                connection.execute("INSERT OR IGNORE INTO dataset_versions VALUES (?,?,?)",(current,json.dumps(old,ensure_ascii=False),now))
                connection.execute("INSERT OR IGNORE INTO archived_records SELECT ?,table_name,row_index,content FROM records",(current,))
            connection.execute("DELETE FROM records")
            connection.execute("INSERT INTO records SELECT table_name,row_index,content FROM archived_records WHERE version=?",(version,))
            lineage=[version]+json.loads(metadata.get("data_lineage","[]"))
            metadata.update(last_sync_at=now,sync_status="synced",sync_error="",source_url="",import_filename=metadata.get("source_name","历史数据恢复"),restored_from=version,data_lineage=json.dumps(list(dict.fromkeys(lineage))),inventory_scope=metadata.get("inventory_scope") or version)
            connection.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)",[(key,str(value)) for key,value in metadata.items()])
            connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("dataset_restored",now,json.dumps({"from":version,"replaced":current},ensure_ascii=False),now))
        return {"success":True,"data_version":now,"restored_from":version,"message":"历史数据已恢复；当前版本也已归档。请重新核对维护资源和排程，旧工单与审计未删除。"}

"""Exercise recovery in a new isolated folder; never replace the operator database."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from backend.backups import create_backup

TABLES=("records","work_orders","alerts","audit_events","inventory_stock","inventory_reservations","inventory_movements","maintenance_events","prediction_runs","operation_requests","auth_users")


def fingerprints(database):
    result={}
    with closing(sqlite3.connect(database.resolve().as_uri()+"?mode=ro",uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall()!=[("ok",)]: raise RuntimeError("恢复数据库完整性检查失败")
        available={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(TABLES).issubset(available): raise RuntimeError('备份缺少必要业务表')
        for table in sorted(available-{'auth_sessions'}):
            if table.startswith('sqlite_'):continue
            if not table.replace('_','').isalnum():raise RuntimeError('备份包含无法核对的表名')
            if table not in available: raise RuntimeError(f"缺少必要表：{table}")
            rows=sorted(json.dumps(row,ensure_ascii=False,separators=(",",":")) for row in connection.execute(f"SELECT * FROM {table}"))
            result[table]={"rows":len(rows),"sha256":hashlib.sha256("\n".join(rows).encode()).hexdigest()}
    return result


def compare_after_startup(backup,restored,before,after):
    if set(before)!=set(after):raise RuntimeError('恢复初始化后业务表集合变化')
    changed=[name for name in before if before[name]!=after[name]]
    if set(changed)-{'import_jobs'}:raise RuntimeError('恢复初始化后持久业务内容意外变化：'+','.join(changed))
    interrupted=0
    if 'import_jobs' in changed:
        def jobs(path):
            with closing(sqlite3.connect(path)) as connection:return {row[0]:json.loads(row[1]) for row in connection.execute('SELECT job_id,content FROM import_jobs')}
        old,new=jobs(backup),jobs(restored)
        if set(old)!=set(new):raise RuntimeError('恢复后导入任务丢失或增加')
        for identifier,item in old.items():
            latest=new[identifier]
            if item==latest:continue
            if item.get('status') not in {'queued','validating','ready'} or latest.get('status')!='interrupted' or not latest.get('message'):raise RuntimeError('恢复后导入任务出现非预期流转')
            if {key:value for key,value in item.items() if key not in {'status','message'}}!={key:value for key,value in latest.items() if key not in {'status','message'}}:raise RuntimeError('恢复后导入任务其他字段意外变化')
            interrupted+=1
    return interrupted


def exercise(database,destination):
    if not database.is_file(): raise ValueError("指定数据库不存在")
    now=datetime.now(timezone.utc)
    folder=destination/(now.strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    snapshot=create_backup(database,folder/"backup")
    backup=folder/"backup"/snapshot["filename"]
    expected=fingerprints(backup)
    restored=folder/"restored"/"factorypulse.sqlite3"
    restored.parent.mkdir()
    shutil.copy2(backup,restored)
    with closing(sqlite3.connect(restored)) as connection:
        old_sessions=connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0]
        connection.execute("DELETE FROM auth_sessions")
        connection.commit()
    if fingerprints(restored)!=expected: raise RuntimeError("恢复副本的业务内容与备份不一致")
    environment={**os.environ,"FACTORYPULSE_DATA_DIR":str(restored.parent.resolve()),"FACTORYPULSE_AUTO_BACKUP":"0","FACTORYPULSE_SERVE_UI":"0"}
    code="import json;from backend import main;main.init();print(json.dumps({'health':main.health(),'readiness':main.readiness()},ensure_ascii=False))"
    initialized=subprocess.run([sys.executable,"-c",code],cwd=ROOT,env=environment,capture_output=True,text=True,encoding="utf-8",timeout=60)
    if initialized.returncode: raise RuntimeError("恢复副本未能通过应用初始化；请在隔离目录检查兼容性")
    readiness=json.loads(initialized.stdout.strip().splitlines()[-1])
    after=fingerprints(restored)
    interrupted_jobs=compare_after_startup(backup,restored,expected,after)
    result={"generated_at":now.isoformat(),"status":"isolated_recovery_passed","backup":snapshot,"revoked_sessions":old_sessions,"tables":after,"application":readiness,"scope":"一致性快照、文件恢复、业务内容摘要、会话失效、应用初始化与数据库读写；未替换正式数据库，未启动网页，未验证现场业务或异地灾备"}
    result['interrupted_import_jobs']=interrupted_jobs
    (folder/"recovery-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"README.md").write_text(f"# 隔离恢复演练\n\n结果：通过。时间（UTC）：{now.isoformat()}。\n\n备份完整性与恢复后业务表摘要一致，旧会话已清除，应用初始化与数据库读写检查通过。\n\n{result['scope']}。\n\n详细结果见 recovery-result.json。恢复副本包含业务与账号敏感数据，仅用于本机受控演练，不应作为公开参赛附件上传。\n",encoding="utf-8")
    return folder,result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="在独立目录演练数据库恢复")
    parser.add_argument("--database",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"outputs/recovery-exercises")
    args=parser.parse_args()
    folder,result=exercise(args.database,args.output)
    print(json.dumps({"output":str(folder),"status":result["status"],"tables_checked":len(result["tables"]),"schema_version":result["application"]["readiness"]["schema_version"]},ensure_ascii=False))

"""Read uploaded SQLite tables into the existing staged sensor-import workflow."""
from __future__ import annotations
import asyncio,csv,io,json,sqlite3,uuid,os
from pathlib import Path
from contextlib import closing
from fastapi import File,HTTPException,UploadFile
from pydantic import BaseModel,Field

MAX_BYTES=100*1024*1024
MAX_ROWS=200000
BLOCKED={'auth_users','auth_sessions','auth_attempts','auth_onboarding','settings'}

def quote(name):return '"'+name.replace('"','""')+'"'

def readonly(path):
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    c.execute('PRAGMA query_only=ON');c.execute('PRAGMA trusted_schema=OFF')
    c.set_progress_handler(lambda:0,1000)
    return c

def table_names(c):
    return [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL%' ORDER BY name") if r[0] not in BLOCKED and not r[0].startswith('auth_')]

def load_dump(raw,path):
    c=sqlite3.connect(path)
    c.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,2*1024*1024)
    allowed={sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_INSERT,sqlite3.SQLITE_READ,sqlite3.SQLITE_SELECT,sqlite3.SQLITE_TRANSACTION}
    def authorize(action,a,b,db,trigger):
        if action==sqlite3.SQLITE_UPDATE and a=='sqlite_master':return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_PRAGMA and a=='foreign_keys':return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
    c.set_authorizer(authorize)
    import time
    deadline=time.monotonic()+10
    c.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    try:c.executescript(raw.decode('utf-8-sig'));c.commit()
    finally:c.close()

def export_table(path,table):
    with closing(readonly(path)) as c:
        if table not in table_names(c):raise ValueError('请选择可导入的数据表；账号与系统配置表不能导入')
        cursor=c.execute('SELECT * FROM '+quote(table)+' LIMIT '+str(MAX_ROWS+1))
        columns=[r[0] for r in cursor.description]
        if table=='records' and {'table_name','content'}.issubset(columns):
            selected=c.execute("SELECT content FROM records WHERE table_name='readings' LIMIT "+str(MAX_ROWS+1))
            records=[];keys=[]
            for (content,) in selected:
                row=json.loads(content)
                if not isinstance(row,dict):raise ValueError('监测记录格式无效')
                row={key:value for key,value in row.items() if not key.startswith('_') and not isinstance(value,(dict,list))}
                records.append(row)
                if len(records)>MAX_ROWS:raise ValueError('单次最多导入200000行')
                for key in row:
                    if key not in keys:keys.append(key)
                if len(keys)>1000:raise ValueError('监测字段超过1000列，请精简后导入')
            if not records:raise ValueError('该业务库没有可导入的监测记录')
            columns=keys;cursor=([row.get(key) for key in keys] for row in records)
        out=io.StringIO();writer=csv.writer(out);writer.writerow(columns)
        for index,row in enumerate(cursor):
            if index>=MAX_ROWS:raise ValueError('单次最多导入200000行，请按时间范围分批导出')
            if any(isinstance(value,bytes) for value in row):raise ValueError('数据表含二进制列，请导出设备监测数值表')
            writer.writerow(row)
            if out.tell()>MAX_BYTES:raise ValueError('展开后的数据超过100MB，请分批导入')
        if out.tell()==0:raise ValueError('表没有可导入数据')
        return out.getvalue().encode('utf-8-sig')

class Selection(BaseModel):
    upload_id:str
    table:str=Field(min_length=1,max_length=200)

def install_database_import(app,directory,analyze):
    @app.post('/api/import/database/inspect')
    async def inspect(file:UploadFile=File(...)):
        if os.environ.get('FACTORYPULSE_TEST_ALLOW_ANONYMOUS')!='1':
            raise HTTPException(422,'当前仅使用 Cloudflare D1，不会创建或打开本地数据库；请将监测表导出为 CSV / XLSX 后导入。')
        suffix=Path(file.filename or '').suffix.lower()
        if suffix not in {'.db','.sqlite','.sqlite3','.sql'}:raise HTTPException(422,'请选择 SQLite 数据库或兼容的 .sql 导出文件')
        identifier=str(uuid.uuid4());path=directory/(identifier+'-source.sqlite3')
        try:
            raw=await file.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise ValueError('数据库文件不能超过100MB')
            if suffix=='.sql':await asyncio.to_thread(load_dump,raw,path)
            else:
                if not raw.startswith(b'SQLite format 3\x00'):raise ValueError('文件不是 SQLite 数据库；MySQL/SQL Server 请先导出监测表为CSV')
                path.write_bytes(raw)
            with closing(readonly(path)) as c:names=table_names(c)
            if not names:raise ValueError('数据库没有可导入的普通数据表')
            return {'upload_id':identifier,'tables':names,'filename':Path(file.filename or '').name,'note':'只读取选中数据表；不会导入账号或替换业务数据库'}
        except (ValueError,sqlite3.Error,UnicodeError) as exc:
            path.unlink(missing_ok=True);raise HTTPException(422,'数据库解析失败：'+str(exc)[:160])
    @app.post('/api/import/database/analyze')
    async def select(payload:Selection):
        try:identifier=str(uuid.UUID(payload.upload_id))
        except ValueError:raise HTTPException(422,'上传会话无效')
        path=directory/(identifier+'-source.sqlite3')
        if not path.exists():raise HTTPException(404,'数据库上传已失效，请重新选择文件')
        try:raw=await asyncio.to_thread(export_table,path,payload.table)
        except (ValueError,sqlite3.Error) as exc:raise HTTPException(422,'读取数据表失败：'+str(exc)[:160])
        return await analyze(UploadFile(file=io.BytesIO(raw),filename=payload.table+'.csv'))

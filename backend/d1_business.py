"""Remote-only DB-API subset. Transaction workspaces and validation run on D1.

Writes are prepared in private D1 tables and published in one revision-guarded
batch. No SQLite connection, file, or in-memory database is used by this module.
"""
import json
import os
import re
import secrets
from itertools import islice
from contextvars import ContextVar
from pathlib import Path
from fastapi import HTTPException
from .d1_identity import D1Store

ROOT=Path(__file__).resolve().parents[1]
request_cache=ContextVar('d1_request_reads',default=None)

def configuration():
    path=Path(os.getenv('FACTORYPULSE_BUSINESS_CONFIG',ROOT/'.secrets/business.json'))
    try:
        config=json.loads(path.read_text(encoding='utf-8'))
        token=Path(config['token_file'])
        config['token_file']=str(token if token.is_absolute() else path.parent/token)
        if not re.fullmatch('[a-f0-9]{32}',config['account_id']) or not re.fullmatch('[a-f0-9-]{36}',config['database_id']):raise ValueError()
        return config
    except (OSError,KeyError,ValueError):raise RuntimeError('必须配置 Cloudflare 业务数据库；禁止回退到本地数据库') from None

class Row(dict):
    def __getitem__(self,key):return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

class Cursor:
    def __init__(self,result=None):
        result=result or {}
        self.rows=[Row(row) for row in result.get('results',[])]
        self.rowcount=result.get('meta',{}).get('changes',0)
        self.lastrowid=result.get('meta',{}).get('last_row_id')
    def fetchone(self):return self.rows.pop(0) if self.rows else None
    def fetchall(self):rows,self.rows=self.rows,[];return rows
    def __iter__(self):return iter(self.rows)

def identifiers(sql,mapping):
    # Quoted string values and comments must never be rewritten as identifiers.
    return re.sub(r"'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/|\b[A-Za-z_][A-Za-z_0-9]*\b",
                  lambda m:mapping.get(m[0],m[0]),sql)

class Connection:
    def __init__(self,store,revision_table='fp_business_revision',guard_table='fp_business_guard'):
        self.store=store;self.tables={};self.columns={};self.revision=None
        self.revision_table=revision_table;self.guard_table=guard_table
        self.prefix='_fp_tx_'+secrets.token_hex(10)+'_';self.closed=False
        self.schema_v2=bool(getattr(store,'schema_v2',False)) and revision_table=='fp_business_revision'
    def __enter__(self):return self
    def query(self,sql,params=()):
        cache=request_cache.get()
        key=(getattr(self.store,'url',id(self.store)),sql,json.dumps(list(params),ensure_ascii=False))
        readonly=sql.lstrip().upper().startswith('SELECT') and not self.tables
        if cache is not None and readonly and key in cache:return cache[key]
        result=self.store.batch([{'sql':sql,'params':list(params)}])[0]
        if cache is not None and readonly:cache[key]=result
        return result
    def baseline(self):
        if self.revision is None:self.revision=self.query(f'SELECT revision FROM {self.revision_table} WHERE id=1')['results'][0]['revision']
    def clone(self,name):
        if name in self.tables:return
        self.baseline()
        info=self.query(f'PRAGMA table_info("{name}")')['results']
        if not info:raise RuntimeError('Remote transaction target does not exist')
        if self.schema_v2:
            from .database_v2_runtime import KEYS
            for column in info:
                column['pk']=(KEYS.get(name,[]).index(column['name'])+1) if column['name'] in KEYS.get(name,[]) else column['pk']
        target=self.prefix+name
        fields=[f'"{r["name"]}" {r["type"] or "BLOB"}' for r in info]
        keys=sorted((r for r in info if r['pk']),key=lambda r:r['pk'])
        if not keys:raise RuntimeError('Remote writes require a primary key')
        fields.append('PRIMARY KEY('+','.join('"'+r['name']+'"' for r in keys)+')')
        self.store.batch([{'sql':f'CREATE TABLE "{target}" ({",".join(fields)})'}, {'sql':f'INSERT INTO "{target}" SELECT * FROM "{name}"'}])
        self.tables[name]=target;self.columns[name]=info
    def execute(self,sql,params=()):
        if self.closed:raise RuntimeError('Connection is closed')
        if getattr(self,'stage_prefix',None):sql=re.sub(r'\bstage\.(staged|onsets)\b',lambda m:'"'+self.stage_prefix+m[1]+'"',sql)
        text=sql.strip();keyword=text.split()[0].upper()
        if keyword=='BEGIN':self.baseline();return Cursor()
        if keyword in {'ATTACH','DETACH'}:raise HTTPException(422,'云端数据库模式不支持本地数据库附件')
        if re.match(r'PRAGMA\s+user_version',text,re.I):
            if '=' in text:
                version=int(text.split('=')[1]);self.query("INSERT INTO fp_db_metadata VALUES('user_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[str(version)]);return Cursor()
            rows=self.query("SELECT CAST(value AS INTEGER) AS user_version FROM fp_db_metadata WHERE key='user_version'")
            return Cursor(rows if rows['results'] else {'results':[{'user_version':0}]})
        if keyword in {'CREATE','ALTER','DROP'}:
            if self.tables:raise RuntimeError('Schema changes cannot follow business writes')
            return Cursor(self.query(sql,params))
        if keyword in {'INSERT','REPLACE','UPDATE','DELETE'}:
            match=re.match(r'(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+["`\[]?([A-Za-z_][A-Za-z_0-9]*)',text,re.I)
            if not match:raise RuntimeError('Unsupported remote write')
            self.clone(match[1])
        elif keyword in {'SELECT','WITH'}:self.baseline()
        rewritten=identifiers(sql,self.tables)
        return Cursor(self.query(rewritten,params))
    def executemany(self,sql,values):
        # Same transaction workspace, bounded API batches; never autocommit live data.
        values=iter(values)
        first=next(values,None)
        if first is None:return Cursor()
        result=self.execute(sql,first)
        insert=re.fullmatch(r'(\s*INSERT(?:\s+OR\s+\w+)?\s+INTO\s+.+?\s+VALUES)\s*(\(\s*\?(?:\s*,\s*\?)*\s*\))\s*',sql,re.I)
        if insert and len(first)>0:
            # D1 caps bound parameters per statement. Group simple VALUES inserts
            # without changing the enclosing transaction or conflict behavior.
            chunk=[];width=max(1,96//len(first))
            while True:
                group=list(islice(values,width))
                if not group:break
                if any(len(row)!=len(first) for row in group):raise ValueError('Inconsistent parameter count')
                grouped=insert[1]+' '+','.join(insert[2] for _ in group)
                chunk.append({'sql':identifiers(grouped,self.tables),'params':[item for row in group for item in row]})
                if len(chunk)>=40:self.store.batch(chunk);chunk=[]
            if chunk:self.store.batch(chunk)
            return result
        chunk=[]
        for value in values:
            chunk.append({'sql':identifiers(sql,self.tables),'params':list(value)})
            if len(chunk)>=40:self.store.batch(chunk);chunk=[]
        if chunk:self.store.batch(chunk)
        return result
    def commit(self):
        if not self.tables:self.revision=None;return
        nonce=secrets.token_hex(20)
        statements=([{'sql':'PRAGMA defer_foreign_keys=ON'}] if self.schema_v2 else [])+[{'sql':f'UPDATE {self.revision_table} SET revision=revision+1,commit_nonce=? WHERE id=1 AND revision=?','params':[nonce,self.revision]},
            {'sql':f'INSERT INTO {self.guard_table}(id) SELECT 0 WHERE NOT EXISTS(SELECT 1 FROM {self.revision_table} WHERE id=1 AND commit_nonce=?)','params':[nonce]}]
        for name,target in self.tables.items():
            info=self.columns[name];keys=[r['name'] for r in sorted(info,key=lambda r:r['pk']) if r['pk']]
            fields=[r['name'] for r in info];nonkeys=[f for f in fields if f not in keys]
            join=' AND '.join(f's."{k}"=a."{k}"' for k in keys)
            if self.schema_v2:
                keylist=','.join('"'+k+'"' for k in keys)
                statements.append({'sql':f'DELETE FROM "{name}" WHERE ({keylist}) NOT IN (SELECT {keylist} FROM "{target}")'})
            else:
                statements.append({'sql':f'DELETE FROM "{name}" AS a WHERE NOT EXISTS(SELECT 1 FROM "{target}" AS s WHERE {join})'})
            columns=','.join('"'+f+'"' for f in fields)
            conflict=','.join('"'+f+'"' for f in keys)
            update='DO NOTHING' if not nonkeys else 'DO UPDATE SET '+','.join(f'"{f}"=excluded."{f}"' for f in nonkeys)+' WHERE '+' OR '.join(f'"{name}"."{f}" IS NOT excluded."{f}"' for f in nonkeys)
            if self.schema_v2 and name in __import__('backend.database_v2_runtime',fromlist=['KEYS']).KEYS:
                same=' AND '.join(f'a."{f}" IS s."{f}"' for f in fields)
                selected=','.join('s."'+f+'"' for f in fields)
                statements.append({'sql':f'INSERT OR REPLACE INTO "{name}" ({columns}) SELECT {selected} FROM "{target}" s WHERE NOT EXISTS(SELECT 1 FROM "{name}" a WHERE {same})'})
            else:
                statements.append({'sql':f'INSERT INTO "{name}" ({columns}) SELECT {columns} FROM "{target}" WHERE 1 ON CONFLICT({conflict}) {update}'})
        try:self.store.batch(statements)
        except HTTPException as error:
            state=self.store.batch([{'sql':f'SELECT revision,commit_nonce FROM {self.revision_table} WHERE id=1'}])[0]['results'][0]
            if state['commit_nonce']==nonce:return
            if state['revision']!=self.revision:raise HTTPException(409,'云端数据已变化，请刷新后重试') from None
            raise error
        finally:
            cache=request_cache.get()
            if cache is not None:cache.clear()
            self.rollback()
    def rollback(self):
        for target in self.tables.values():self.query(f'DROP TABLE IF EXISTS "{target}"')
        self.tables={};self.columns={};self.revision=None
    def close(self):
        self.rollback();self.closed=True
    def __exit__(self,kind,error,tb):
        try:
            if kind is None:self.commit()
            else:self.rollback()
        finally:self.closed=True

def initialize(store):
    v2=store.batch([{'sql':"SELECT name FROM sqlite_master WHERE type='table' AND name='database_schema'"}])[0]['results']
    if v2:
        state=store.batch([{'sql':'SELECT version,migration_state FROM database_schema WHERE version=2'}])[0]['results']
        if not state or state[0]['migration_state']!='ready':raise RuntimeError('V2 数据库尚未完成迁移校验')
        store.schema_v2=True
        return
    existing=store.batch([{'sql':"SELECT name FROM sqlite_master WHERE type='table' AND name IN ('fp_business_revision','fp_business_guard','fp_db_metadata')"}])[0]['results']
    if len(existing)==3:return
    store.batch([
        {'sql':'CREATE TABLE IF NOT EXISTS fp_business_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,commit_nonce TEXT)'},
        {'sql':'INSERT OR IGNORE INTO fp_business_revision VALUES(1,0,NULL)'},
        {'sql':'CREATE TABLE IF NOT EXISTS fp_business_guard(id INTEGER PRIMARY KEY CONSTRAINT fp_business_guard_revision CHECK(id=1))'},
        {'sql':'CREATE TABLE IF NOT EXISTS fp_db_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)'},
    ])

def connection_factory():
    store=D1Store(configuration());initialize(store)
    return lambda:Connection(store)


def load_default_dataset():
    store=D1Store(configuration())
    meta=store.batch([{'sql':"SELECT d.* FROM fp_datasets d JOIN fp_app_settings s ON s.value=d.dataset_id WHERE s.key='default_dataset' AND d.ready=1"}])[0]['results']
    if not meta:raise HTTPException(503,'Cloudflare 默认测试集尚未完成校验')
    version=meta[0]['dataset_id'];tables={}
    counts=store.batch([{'sql':'SELECT table_name,COUNT(*) AS n FROM fp_dataset_records WHERE dataset_id=? GROUP BY table_name','params':[version]}])[0]['results']
    for item in counts:
        records=[]
        for start in range(0,item['n'],2000):
            batches=store.batch([{'sql':'SELECT content FROM fp_dataset_records WHERE dataset_id=? AND table_name=? ORDER BY row_index LIMIT 500 OFFSET ?','params':[version,item['table_name'],offset]} for offset in range(start,min(start+2000,item['n']),500)])
            for batch in batches:records.extend(json.loads(r['content']) for r in batch['results'])
        tables[item['table_name']]=records
    return tables,meta[0]['source_date']


class RemoteStage:
    """Per-upload staging tables on D1; never creates a local staging database."""
    def __init__(self,identifier):
        import uuid
        self.prefix='_fp_import_'+uuid.UUID(str(identifier)).hex+'_'
        self.store=D1Store(configuration())
        self.mapping={name:self.prefix+name for name in ('staged','onsets','device_bounds','onset_time')}
        self.pending=[]
    def execute(self,sql,params=()):
        statement={'sql':identifiers(sql,self.mapping),'params':list(params)}
        if re.match(r'\s*INSERT INTO staged VALUES',sql,re.I):
            self.pending.append(statement)
            if len(self.pending)>=40:self.commit()
            return Cursor()
        self.commit()
        return Cursor(self.store.batch([statement])[0])
    def exists(self):
        return bool(self.store.batch([{'sql':"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",'params':[self.prefix+'staged']}])[0]['results'])
    def commit(self):
        if self.pending:
            self.store.batch(self.pending);self.pending=[]
    def close(self):self.pending=[]
    def set_progress_handler(self,*args):pass

"""List project SQLite files and schemas without reading business/account rows."""
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone,timedelta
import collections,json,os,sqlite3
root=Path(__file__).resolve().parents[1]
roots=[root,Path(os.environ.get('LOCALAPPDATA',''))/'FactoryPulse',Path.home()/'.factorypulse']
files=[]
for directory in roots:
 if not directory.exists():continue
 for base,dirs,names in os.walk(directory):
  dirs[:]=[d for d in dirs if d not in {'node_modules','.venv','.git','.pnpm-store','pearl-chrome','__pycache__','.pytest_cache'}]
  for name in names:
   path=Path(base)/name
   if path.suffix.lower() not in {'.sqlite3','.sqlite','.db'}:continue
   try:
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
   except sqlite3.Error:continue
   value=str(path)
   if path==root/'.env.runtime/data/factorypulse.sqlite3':group='当前业务库'
   elif 'backups' in path.parts:group='恢复备份副本'
   elif path==Path.home()/'.factorypulse/factorypulse.sqlite3':group='旧默认目录业务库'
   elif 'final-runtime' in path.parts or 'deployment' in path.parts:group='隔离验收与部署验证库'
   elif 'tests' in path.parts or 'pytest-data' in path.parts or 'test-data' in path.parts:group='测试与导入暂存库'
   elif 'before.sqlite3'==name or 'before-fix' in name:group='修改前恢复快照'
   else:group='其他数据库副本'
   files.append({'path':value,'category':group,'bytes':path.stat().st_size,'tables':tables})
files.sort(key=lambda x:(x['category'],x['path']))
output=root/'outputs';output.mkdir(exist_ok=True)
(output/'database-inventory.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
counts=collections.Counter(item['category'] for item in files)
lines=['# FactoryPulse 数据库清单','', '盘点时间：'+datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'', '只读取 SQLite 文件的表结构与文件大小，没有导出账号或业务记录。项目使用 SQLite；以下绝大多数文件是备份、恢复快照或隔离测试副本，并非独立数据库服务。', '', '| 类别 | 文件数 |','| --- | --- |']
lines += [f'| {key} | {value} |' for key,value in sorted(counts.items())]
for group in sorted(counts):
 lines+=['','## '+group,'','| 路径 | 大小（MiB） | 数据表数 |','| --- | ---: | ---: |']
 for item in files:
  if item['category']==group:lines.append(f"| `{item['path']}` | {item['bytes']/1048576:.2f} | {len(item['tables'])} |")
current=next((item for item in files if item['category']=='当前业务库'),None)
if current:lines+=['','## 当前业务库的数据表','',', '.join('`'+name+'`' for name in current['tables']), '', '`sqlite_sequence` 为 SQLite 内部表；其余表共同属于一个业务数据库文件。']
(output/'database-inventory.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'database_files':len(files),'categories':dict(counts),'report':str(output/'database-inventory.md')},ensure_ascii=False))

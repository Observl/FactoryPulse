"""Minimize agent-package schema changes against the original export."""
from pathlib import Path
import copy,hashlib,json,zipfile
import yaml
ROOT=Path(__file__).resolve().parents[1]
source=Path(r'C:/Users/13485/Downloads/FactoryPulseAgent.ifpkg')
optimized=ROOT/'outputs/dify-efficient/FactoryPulseAgent.efficient-manifest-fixed.ifpkg'
with zipfile.ZipFile(source) as z:
    original_files={n:z.read(n) for n in z.namelist()}
    original=yaml.safe_load(original_files['app.yaml'])
with zipfile.ZipFile(optimized) as z:app=yaml.safe_load(z.read('app.yaml'))
manifest=copy.deepcopy(yaml.safe_load(original_files['manifest.yaml']))
nodes=app['workflow']['graph']['nodes']
bound=[n for n in nodes if n['data']['type']=='agent']
oldkeys=list(app['agent_packages'])
mapping={old:'agent_'+str(i+1) for i,old in enumerate(oldkeys)}
packages={};resources={};files={};nextfile=1
for oldkey,newkey in mapping.items():
    # The original package's nested schema, nullable model settings and other
    # defaults are retained. Only prompt text and deliberate tool removal vary.
    package=copy.deepcopy(original['agent_packages'][oldkey])
    package['soul']['prompt']['system_prompt']=app['agent_packages'][oldkey]['soul']['prompt']['system_prompt']
    if oldkey=='agent_2':
        package['soul']['prompt']['system_prompt']=package['soul']['prompt']['system_prompt'].replace('优先读取所附当前数据库指南；只有实际结构与指南冲突时核对一次sqlite_master，不枚举完整库。','当前业务库已为V2，ID不变。结构未知时只核对任务所需表或视图一次，不枚举完整库。')
    if oldkey in ['agent_3','agent_4']:
        package['soul']['tools']['cli_tools']=[]
        package['soul']['tools']['dify_tools']=[]
    resources[newkey]={}
    oldresources=manifest['agent_resources'].get(oldkey,{})
    byid={r['id']:r for r in oldresources.get('files',[])}
    for f in package['soul'].get('config_files',[]):
        if f.get('file_kind')!='upload_file':continue
        item=byid[f['file_id']];newid=f'f_{nextfile:06d}';nextfile+=1
        raw=original_files[item['path']];path=newid+'.md';files[path]=raw
        # Retain the original attachment hash semantics and byte content.
        f['file_id']=newid
        resource=copy.deepcopy(item);resource['id']=newid;resource['path']=path
        resources[newkey].setdefault('files',[]).append(resource)
    if oldkey in ['agent_8','agent_9']:
        package['soul']['prompt']['system_prompt']+='\n版本纠正：附件为2026-10-25历史说明，其中“V2尚未上线、需新库ID”等部署叙述已过期，不可据此判断当前部署。2026-10-27线上已迁移V2，业务库ID不变；实际查询前以受控工具核对当前结构。'
    packages[newkey]=package
for n in bound:n['data']['agent_binding']['package_ref']=mapping[n['data']['agent_binding']['package_ref']]
app['agent_packages']=packages
manifest['agent_resources']=resources
files['app.yaml']=yaml.safe_dump(app,allow_unicode=True,sort_keys=False,width=110).encode()
for item in manifest['apps']:
    raw=files[item['path']];item['size']=len(raw);item['sha256']=hashlib.sha256(raw).hexdigest()
files['manifest.yaml']=yaml.safe_dump(manifest,allow_unicode=True,sort_keys=False).encode()
out=ROOT/'outputs/dify-efficient/FactoryPulseAgent.efficient-compatible.ifpkg'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for name,raw in files.items():z.writestr(name,raw)
assert list(packages)==['agent_'+str(i+1) for i in range(len(packages))]
assert set(resources)==set(packages)=={n['data']['agent_binding']['package_ref'] for n in bound}
for old,new in mapping.items():
    before=original['agent_packages'][old];after=packages[new]
    for key in before['soul']:
        if key not in ['prompt','tools','config_files']:assert before['soul'][key]==after['soul'][key],(old,key)
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    for item in manifest['apps']+sum([r.get('files',[]) for r in resources.values()],[]):
        raw=z.read(item['path']);assert len(raw)==item['size'];assert hashlib.sha256(raw).hexdigest()==item['sha256']
report={'package':out.name,'agent_package_mapping':mapping,'agent_package_defaults_restored':True,'original_attachment_bytes_retained':True,'manifest_integrity':'passed','live_import_tested':False,'root_cause_confirmed':False}
(out.parent/'compatibility-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))

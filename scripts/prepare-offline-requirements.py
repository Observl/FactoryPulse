"""Capture a validated dependency closure from this interpreter; no network or installs."""
import argparse,hashlib,importlib.metadata,json,platform,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parents[1]

def dependency_closure(requirements,distribution=importlib.metadata.distribution):
    pending=[Requirement(line.strip()) for line in requirements.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    resolved={};extras={};visited=set()
    while pending:
        request=pending.pop()
        if request.marker and not request.marker.evaluate():continue
        if request.url:raise ValueError('离线清单不接受直接URL依赖')
        name=canonicalize_name(request.name)
        installed=distribution(name)
        if request.specifier and not request.specifier.contains(installed.version,prereleases=True):
            raise ValueError(f'{name}已安装版本{installed.version}不满足{request.specifier}')
        resolved[name]=installed.version
        extras.setdefault(name,set()).update(request.extras)
        key=(name,tuple(sorted(extras[name])))
        if key in visited:continue
        visited.add(key)
        for raw in installed.requires or []:
            dependency=Requirement(raw)
            if dependency.marker and not any(dependency.marker.evaluate({'extra':extra}) for extra in {''}|extras[name]):continue
            dependency.marker=None
            pending.append(dependency)
    return dict(sorted(resolved.items()))

def prepare(requirements,output):
    raw=requirements.read_bytes()
    packages=dependency_closure(raw.decode('utf-8-sig'))
    stamp=datetime.now(timezone.utc)
    folder=output/(stamp.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
    lock=''.join(f'{name}=={version}\n' for name,version in packages.items())
    (folder/'requirements-offline.txt').write_text(lock,'utf-8')
    metadata={'generated_at':stamp.isoformat(),'python':platform.python_version(),'platform':sys.platform,'machine':platform.machine(),'requirements_sha256':hashlib.sha256(raw).hexdigest(),'lock_sha256':hashlib.sha256(lock.encode()).hexdigest(),'packages':packages,'wheelhouse_complete':False,'installation_verified':False}
    (folder/'runtime.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),'utf-8')
    (folder/'README.md').write_text('# 离线依赖准备清单\n\n这是当前解释器中已安装依赖的精确闭包，未下载软件包、未安装环境、未验收离线部署。\n\n目标Windows、Python版本和架构必须与runtime.json核对；请在准备电脑收集清单中全部版本的wheel，并校验可信来源。某些已安装版本可能没有可用的目标平台wheel，清单生成成功不证明离线包齐全。\n\n安装时通过install-offline.ps1的-RequirementsFile参数指定本清单，避免重新按宽泛版本范围选择；依赖收集和目标机验收仍需单独完成。\n','utf-8')
    return folder,len(packages)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--requirements',type=Path,default=ROOT/'backend/requirements.txt');parser.add_argument('--output',type=Path,default=ROOT/'outputs/offline-requirements');args=parser.parse_args()
    try:
        folder,count=prepare(args.requirements,args.output)
        print(json.dumps({'directory':str(folder),'packages':count,'downloaded':False,'installed':False},ensure_ascii=False))
    except (ValueError,OSError,importlib.metadata.PackageNotFoundError) as error:
        parser.exit(2,'依赖清单生成失败：'+str(error)+'\n')

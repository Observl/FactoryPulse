"""Build an allowlisted source delivery ZIP; never include operator databases."""
import argparse,hashlib,json,sys,uuid,zipfile
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.build_artifact import validate_build

def package(root,output,include_demo=False):
    root=root.resolve();build=validate_build(root/'dist')
    files=set((root/'backend').glob('*.py'))
    files.add(root/'backend/requirements.txt')
    files.update(path for path in (root/'dist').rglob('*') if path.is_file())
    files.update(root/'scripts'/name for name in ('start-local.ps1','stop-local.ps1','install-offline.ps1','exercise-recovery.py','verify-local-deployment.py','export-prediction-evidence.py','final-acceptance.py'))
    files.update(root/'docs'/name for name in ('LOCAL-DEPLOYMENT.md','OPERATOR-GUIDE.md','BACKUP-RECOVERY.md','OPERATOR-TRIAL.md'))
    if include_demo:files.update((root/'data/model-validation'/name) for name in ('dataset.json','manifest.json'))
    if (root/'config/model-training.json').exists():files.add(root/'config/model-training.json')
    if (root/'backend/requirements.lock.txt').exists():files.add(root/'backend/requirements.lock.txt')
    for name in ('README.md','docs/FINAL-REVIEW-REMEDIATION.md'):
        if (root/name).exists():files.add(root/name)
    if not (root/'backend/main.py').is_file():raise ValueError('缺少后端入口')
    for path in files:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('交付文件缺失或越界：'+str(path))
    output.mkdir(parents=True,exist_ok=True)
    target=output/('FactoryPulse-local-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.zip')
    temporary=target.with_suffix('.zip.partial')
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'build':build,'demo_data_included':include_demo,'runtime_included':False,'wheelhouse_included':False,'installation_verified':False,'files':[]}
    try:
        with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(files):
                relative=path.relative_to(root).as_posix();digest=hashlib.sha256();size=0
                with path.open('rb') as source,archive.open(relative,'w') as destination:
                    while chunk:=source.read(65536):destination.write(chunk);digest.update(chunk);size+=len(chunk)
                manifest['files'].append({'path':relative,'size':size,'sha256':digest.hexdigest()})
            archive.writestr('delivery-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            archive.writestr('START-HERE.txt','FactoryPulse本地交付准备包\n\n不含Python运行环境、离线依赖包、当前业务数据库、密钥或日志。不是已验收的独立安装程序。\n先阅读docs/LOCAL-DEPLOYMENT.md，准备目标Windows运行环境和全部离线wheel。安装及恢复验收完成前不能视为现场可用。\n所含数据如有，仅为冻结的合成模型验证集，不是现场效果或实时数据。\n文件清单和摘要见delivery-manifest.json；摘要不是发布者签名。\n')
        temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)
    return target,manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'outputs/delivery');parser.add_argument('--include-demo-data',action='store_true');args=parser.parse_args()
    try:
        path,manifest=package(ROOT,args.output,args.include_demo_data)
        print(json.dumps({'archive':str(path),'files':len(manifest['files']),'runtime_included':False,'wheelhouse_included':False,'installation_verified':False},ensure_ascii=False))
    except (ValueError,OSError,zipfile.BadZipFile) as error:parser.exit(2,'交付打包失败：'+str(error)+'\n')

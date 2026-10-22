"""Verify delivery mode and hashes without launching or rendering a webpage."""
import hashlib,json
from pathlib import Path

def validate_build(directory):
    root=Path(directory).resolve(strict=True)
    manifest=json.loads((root/'factorypulse-build.json').read_text('utf-8'))
    if not isinstance(manifest,dict): raise ValueError('界面构建清单必须为对象，请重新构建')
    if manifest.get('schema_version')!=1 or manifest.get('app')!='FactoryPulse': raise ValueError('界面构建清单无效，请重新构建')
    if manifest.get('build_mode') not in {'local_service','full_service'} or manifest.get('asset_base')!='/' or manifest.get('api_prefix')!='/api': raise ValueError('当前不是本地服务版或统一完整界面，不能用于完整服务交付')
    files=manifest.get('files',[])
    if not isinstance(files,list) or any(not isinstance(entry,dict) for entry in files): raise ValueError('构建文件清单格式无效，请重新构建')
    if not files or 'index.html' not in {entry.get('path') for entry in files}: raise ValueError('构建清单缺少首页')
    seen=set()
    for entry in files:
        relative=entry.get('path','')
        path=(root/relative).resolve()
        if not relative or Path(relative).is_absolute() or not path.is_relative_to(root) or relative in seen: raise ValueError('构建清单包含重复或越界路径')
        seen.add(relative)
        if not path.is_file(): raise ValueError('构建文件缺失：'+relative)
        digest=hashlib.sha256()
        with path.open('rb') as handle:
            while chunk:=handle.read(65536): digest.update(chunk)
        if path.stat().st_size!=entry.get('size') or digest.hexdigest()!=entry.get('sha256'): raise ValueError('构建文件与清单不一致：'+relative)
    return {'status':'verified','version':manifest.get('version'),'build_mode':manifest['build_mode'],'files':len(files),'scope':'文件一致性与本地构建模式，不是代码签名、网页或排版验收'}

if __name__=='__main__':
    import argparse,sys
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    try: print(json.dumps(validate_build(args.directory),ensure_ascii=False))
    except (OSError,ValueError,TypeError,KeyError) as error:
        print('界面构建检查失败：'+str(error));sys.exit(2)

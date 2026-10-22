"""Package complete reviewable source, independent of Git tracking state."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
def package():
    files=[]
    for directory in ('src','backend','tests','scripts','config','docs','electron','.github','public','data/model-validation'):
        for path in (ROOT/directory).rglob('*'):
            if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts:continue
            if directory=='tests' and (path.parent!=ROOT/'tests' or path.suffix!='.py'):continue
            if directory=='backend' and (path.parent!=ROOT/'backend' or path.suffix not in ('.py','.txt')):continue
            if directory=='scripts' and path.name.startswith('apply-review-'):continue
            if path.suffix in ('.sqlite3','.db','.log','.pyc'):continue
            files.append(path)
    files.extend(ROOT/name for name in ('package.json','pnpm-lock.yaml','tsconfig.json','vite.config.ts','index.html','README.md','DESIGN.md','LICENSE','.gitignore','.env.example'))
    out=ROOT/'outputs/final-delivery';out.mkdir(exist_ok=True)
    target=out/'FactoryPulse-final-source.zip'
    manifest={'scope':'complete_project_source_with_single_frozen_acceptance_dataset','files':[]}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(set(files)):
            raw=path.read_bytes();name=path.relative_to(ROOT).as_posix();z.writestr(name,raw)
            manifest['files'].append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        z.writestr('source-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(target) as z:
        for item in manifest['files']:assert hashlib.sha256(z.read(item['path'])).hexdigest()==item['sha256']
    print(json.dumps({'archive':str(target),'files':len(manifest['files']),'verified':True},ensure_ascii=False))
if __name__=='__main__':package()

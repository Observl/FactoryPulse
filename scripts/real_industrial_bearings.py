"""Inspect downloaded NASA bearing archives; extract only data and documentation."""
from pathlib import Path
import zipfile,shutil,json,sys
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028/raw'
def inspect(name):
    p=ROOT/name
    archives=[p/'source.zip',p/'source.ranged.zip']
    f=next((x for x in archives if x.exists() and zipfile.is_zipfile(x)),None)
    if not f:raise FileNotFoundError(name+' archive not yet complete')
    p=p/'nested';p.mkdir(exist_ok=True)
    with zipfile.ZipFile(f) as z:
        for m in z.infolist():
            if m.filename.endswith(('.7z','.zip')):
                dest=p/Path(m.filename).name
                if not dest.exists() or dest.stat().st_size!=m.file_size:
                    with z.open(m) as src,dest.open('wb') as out:shutil.copyfileobj(src,out)
    for f in p.iterdir():
        if f.suffix=='.zip':
            with zipfile.ZipFile(f) as z:
                names=z.namelist();print(name,len(names),names[:30],flush=True)
                (p/'members.json').write_text(json.dumps(names,indent=2))
                for m in z.infolist():
                    if m.filename.lower().endswith(('.pdf','.txt','.md')) and m.file_size<2_000_000:
                        (p/Path(m.filename).name).write_bytes(z.read(m))
        if f.suffix=='.7z':
            import py7zr
            with py7zr.SevenZipFile(f) as z:
                names=z.getnames();print(name,len(names),names[:30],flush=True)
                (p/'members.json').write_text(json.dumps(names,indent=2))
                docs=[n for n in names if n.lower().endswith(('.pdf','.txt','.md')) or 'readme' in n.lower()]
                print('docs',docs,flush=True)
                for n in names:
                    if '..' in Path(n.replace('\\','/')).parts or Path(n).is_absolute():raise ValueError('Unsafe archive')
                z.extract(path=p/'docs',targets=docs)
    if name=='femto':
        with zipfile.ZipFile(p/'FEMTOBearingDataSet.zip') as z:
            for member in z.infolist():
                if member.filename not in ('Training_set.zip','Test_set.zip','Validation_Set.zip'):continue
                dest=p/member.filename
                if dest.exists() and dest.stat().st_size==member.file_size:continue
                with z.open(member) as src,dest.open('wb') as out:shutil.copyfileobj(src,out)
if __name__=='__main__':
    for name in sys.argv[1:] or ['nasa_ims','femto']:inspect(name)

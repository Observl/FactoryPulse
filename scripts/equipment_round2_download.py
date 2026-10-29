"""Round 2: industrial equipment bearing measurements only; local storage."""
import json,hashlib,time,zipfile,shutil,concurrent.futures
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028-round2'
BEARINGS=['K001','K002','K003','K004','K005','KA04','KA15','KA16','KA22','KA30','KI04','KI14','KI16','KI18','KI21']
def sources():
    rows=json.loads((ROOT/'cwru_file_catalog.json').read_text())
    for r in rows:
        yield dict(name='cwru',url=r['url'],filename=Path(r['url']).name,label=r['label'],source_page=r['source_page'],
            provenance='real motor test rig; EDM seeded faults; not naturally occurring field failures',license='Public research download; original acknowledgement required; no general commercial license asserted')
    yield dict(name='mfpt',url='https://codeload.github.com/mathworks/RollingElementBearingFaultDiagnosis-Data/zip/refs/heads/master',
        filename='source.zip',source_page='https://github.com/mathworks/RollingElementBearingFaultDiagnosis-Data',
        provenance='real bearing test rig; authorized MathWorks redistribution of Eric Bechhoefer/MFPT data',license='CC BY-NC-SA 4.0; local noncommercial research only; commercial permission not granted by this experiment')
    yield dict(name='skab',url='https://codeload.github.com/waico/SKAB/zip/refs/heads/master',filename='source.zip',
        source_page='https://github.com/waico/SKAB',provenance='real water-pump circulation-loop testbed; supervised detection of induced abnormal operating states',license='Repository GPL-3.0 notice retained; local research only, no redistribution')
    for bearing in BEARINGS:
        yield dict(name='paderborn',url='https://groups.uni-paderborn.de/kat/BearingDataCenter/'+bearing+'.rar',filename=bearing+'.rar',bearing=bearing,
            source_page='https://mb.uni-paderborn.de/kat/forschung/bearing-datacenter/data-sets-and-download',
            provenance='real electromechanical test rig; healthy bearings plus accelerated-lifetime damage',license='CC BY-NC 4.0; local noncommercial research only')
def fetch(item):
    folder=ROOT/'raw'/item['name'];folder.mkdir(parents=True,exist_ok=True);dest=folder/item['filename'];start=time.monotonic()
    try:
        for attempt in range(3):
            try:
                if not dest.exists():
                    with httpx.Client(follow_redirects=True,timeout=120) as c:
                        with c.stream('GET',item['url']) as r:
                            r.raise_for_status();expected=int(r.headers.get('content-length') or 0)
                            with dest.with_suffix(dest.suffix+'.part').open('wb') as out:
                                for chunk in r.iter_bytes(1024*1024):out.write(chunk)
                    tmp=dest.with_suffix(dest.suffix+'.part')
                    if expected and tmp.stat().st_size!=expected:raise ValueError('Incomplete download')
                    tmp.replace(dest)
                if dest.suffix=='.mat':
                    from scipy.io import loadmat
                    keys=loadmat(dest,variable_names=[])
                    if '__header__' not in keys:raise ValueError('Not a MATLAB data file')
                elif dest.suffix=='.rar':
                    with dest.open('rb') as f:
                        if not f.read(7).startswith(b'Rar!'):raise ValueError('Not a RAR data archive')
                elif dest.suffix=='.zip':
                    with zipfile.ZipFile(dest) as z:
                        for m in z.infolist():
                            rel=Path(m.filename)
                            if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe archive path')
                            if m.is_dir() or (rel.suffix.lower() not in ('.mat','.txt','.md','.csv') and rel.name.lower()!='license'):continue
                            if item['name']=='skab' and rel.suffix.lower()=='.csv' and '/data/' not in m.filename:continue
                            target=folder/'extracted'/rel;target.parent.mkdir(parents=True,exist_ok=True)
                            with z.open(m) as src,target.open('wb') as out:shutil.copyfileobj(src,out)
                break
            except Exception:
                if attempt==2:raise
        result={**item,'status':'downloaded','path':str(dest),'bytes':dest.stat().st_size,
            'sha256':hashlib.file_digest(dest.open('rb'),'sha256').hexdigest(),'seconds':round(time.monotonic()-start,2)}
        (folder/(item['filename']+'.manifest.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'source':item['name'],'file':item['filename'],'bytes':result['bytes'],'status':'downloaded'}),flush=True)
        return result
    except Exception as e:
        result={**item,'status':'unavailable','error':str(e)};print(json.dumps(result),flush=True);return result
if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True)
    # Same sources as prior round are explicitly not fetched or reused.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(fetch,[s for s in sources() if s['name']!='paderborn']))
    from equipment_round2_ranges import main as ranged_download
    ranged_download()

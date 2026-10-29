"""Resumable range downloads for large public NASA archives, local only."""
import concurrent.futures,hashlib,json,time,zipfile
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028/raw'
def get_archive(name,url,size):
    folder=ROOT/name;parts=folder/'ranges';parts.mkdir(parents=True,exist_ok=True)
    chunk=8*1024*1024
    def part(i):
        start=i*chunk;end=min(size-1,start+chunk-1);p=parts/f'{i:04}.part'
        if p.exists() and p.stat().st_size==end-start+1:return
        for attempt in range(3):
            try:
                with httpx.Client(timeout=120,follow_redirects=True) as client:
                    r=client.get(url,headers={'Range':f'bytes={start}-{end}'})
                r.raise_for_status()
                if r.status_code!=206 or len(r.content)!=end-start+1:raise ValueError('Range mismatch')
                p.write_bytes(r.content);return
            except Exception:
                if attempt==2:raise

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for count,_ in enumerate(pool.map(part,range((size+chunk-1)//chunk)),1):
            if count%16==0:print(name,count,'chunks',flush=True)
    target=folder/'source.ranged.zip'
    with target.open('wb') as out:
        for p in sorted(parts.glob('*.part')):
            with p.open('rb') as inp:
                import shutil;shutil.copyfileobj(inp,out)
    if target.stat().st_size!=size or not zipfile.is_zipfile(target):raise ValueError('Invalid archive')
    print(json.dumps({'name':name,'bytes':size,'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest(),
        'members':zipfile.ZipFile(target).namelist()}),flush=True)
if __name__=='__main__':
    for args in [('nasa_ims','https://phm-datasets.s3.amazonaws.com/NASA/4.+Bearings.zip',1075597174),
                 ('femto','https://phm-datasets.s3.amazonaws.com/NASA/10.+FEMTO+Bearing.zip',1157035288)]:
        get_archive(*args)

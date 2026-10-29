"""Bounded parallel range retrieval of official Paderborn bearing archives."""
import json,re,concurrent.futures,shutil
from pathlib import Path
import httpx
import equipment_round2_download as source
ROOT=source.ROOT;CHUNK=4*1024*1024
def main():
    items=[v for v in source.sources() if v['name']=='paderborn'];jobs=[];sizes={};counts={};completed={}
    limits=httpx.Limits(max_connections=16,max_keepalive_connections=16)
    with httpx.Client(follow_redirects=True,timeout=90,limits=limits) as client:
        def metadata(item):
            r=client.head(item['url']);r.raise_for_status()
            if r.headers.get('accept-ranges')!='bytes':raise ValueError('No range support')
            size=int(r.headers['content-length']);return item,size
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:headers=list(pool.map(metadata,items))
        for item,size in headers:
            b=item['bearing'];sizes[b]=size;counts[b]=(size+CHUNK-1)//CHUNK;completed[b]=0
            parts=ROOT/'raw/paderborn/ranges'/b;parts.mkdir(parents=True,exist_ok=True)
            first=ROOT/'raw/paderborn/K001.first-range.part'
            if b=='K001' and first.exists() and first.stat().st_size==CHUNK and not (parts/'0000.part').exists():shutil.copyfile(first,parts/'0000.part')
            jobs.extend((item,i,size) for i in range(counts[b]))
        def part(args):
            item,i,size=args;b=item['bearing'];start=i*CHUNK;end=min(size-1,start+CHUNK-1)
            p=ROOT/'raw/paderborn/ranges'/b/f'{i:04}.part'
            if p.exists() and p.stat().st_size==end-start+1:return item,i
            for attempt in range(3):
                try:
                    r=client.get(item['url'],headers={'Range':f'bytes={start}-{end}'})
                    r.raise_for_status()
                    if r.status_code!=206 or len(r.content)!=end-start+1 or not r.headers.get('content-range','').startswith(f'bytes {start}-{end}/'):raise ValueError('Range mismatch')
                    p.write_bytes(r.content);return item,i
                except Exception:
                    if attempt==2:raise
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futures=[pool.submit(part,j) for j in jobs]
            for number,future in enumerate(concurrent.futures.as_completed(futures),1):
                item,i=future.result();b=item['bearing'];completed[b]+=1
                if number%32==0:print(json.dumps({'chunks_completed':number,'chunks_total':len(jobs)}),flush=True)
                if completed[b]==counts[b]:
                    target=ROOT/'raw/paderborn'/item['filename']
                    with target.with_suffix('.assembling').open('wb') as out:
                        for p in sorted((ROOT/'raw/paderborn/ranges'/b).glob('*.part')):
                            with p.open('rb') as inp:shutil.copyfileobj(inp,out)
                    if target.with_suffix('.assembling').stat().st_size!=sizes[b]:raise ValueError('Assembled length mismatch')
                    target.with_suffix('.assembling').replace(target);result=source.fetch(item)
                    if result['status']!='downloaded':raise ValueError(result)
    manifests=[]
    for item in source.sources():
        p=ROOT/'raw'/item['name']/(item['filename']+'.manifest.json')
        if p.exists():manifests.append(json.loads(p.read_text()))
        else:manifests.append({**item,'status':'unavailable','error':'Missing completed source file'})
    (ROOT/'download_manifest.json').write_text(json.dumps({'sources':manifests,'scope':'Only real measured industrial bearing/motor condition data.'},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()

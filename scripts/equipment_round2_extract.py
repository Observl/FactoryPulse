"""Extract completed Paderborn bearing archives locally, without bundled executables."""
import json,time,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028-round2'
SEVEN=Path('C:/Program Files/7-Zip/7z.exe')
from equipment_round2_download import BEARINGS
def extract(bearing):
    base=ROOT/'raw/paderborn';archive=base/(bearing+'.rar');marker=base/(bearing+'.extracted.json')
    if marker.exists():return True
    if not archive.exists() or not (base/(bearing+'.rar.manifest.json')).exists():return False
    listing=subprocess.run([str(SEVEN),'l','-slt',str(archive)],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True).stdout
    for line in listing.splitlines():
        if not line.startswith('Path = '):continue
        path=line[7:]
        if path==str(archive):continue
        relative=Path(path)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive entry '+path)
    destination=base/'extracted';destination.mkdir(exist_ok=True)
    with (base/(bearing+'.extraction.log')).open('w',encoding='utf-8') as out:
        subprocess.run([str(SEVEN),'x',str(archive),'-o'+str(destination),'*.mat','*.pdf','*.txt','-r','-y'],stdout=out,stderr=subprocess.STDOUT,check=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    files=list(destination.rglob('*'+bearing+'*.mat'))
    if len(files)!=80:raise ValueError(f'{bearing}: expected 80 MATLAB recordings, got {len(files)}')
    marker.write_text(json.dumps({'bearing':bearing,'recordings':len(files),'verified_extractor_exit':0},indent=2))
    print(json.dumps({'extracted':bearing,'recordings':len(files)}),flush=True);return True
if __name__=='__main__':
    watch='--watch' in sys.argv
    while True:
        done=[extract(b) for b in BEARINGS]
        if all(done) or not watch:break
        time.sleep(10)

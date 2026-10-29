"""Download only public primary-source data to local ignored outputs; no cloud DB access."""
import concurrent.futures,hashlib,json,time,zipfile
from pathlib import Path
from datetime import datetime,timezone
import httpx
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028'
ROOT.mkdir(parents=True,exist_ok=True)
UCI='https://archive.ics.uci.edu'
SOURCES=[
 ('metropt3',UCI+'/static/public/791/metropt+3+dataset.zip',UCI+'/dataset/791/metropt+3+dataset','real_operational','CC BY 4.0'),
 ('hydraulic',UCI+'/static/public/447/condition+monitoring+of+hydraulic+systems.zip',UCI+'/dataset/447/condition+monitoring+of+hydraulic+systems','physical_test_rig','CC BY 4.0'),
 ('aps_scania',UCI+'/static/public/421/aps+failure+at+scania+trucks.zip',UCI+'/dataset/421/aps+failure+at+scania+trucks','real_operational','UCI CC BY 4.0; archive also contains Scania GPLv3 notice; retain both'),
 ('secom',UCI+'/static/public/179/secom.zip',UCI+'/dataset/179/secom','real_manufacturing','CC BY 4.0'),
 ('steel_faults',UCI+'/static/public/198/steel+plates+faults.zip',UCI+'/dataset/198/steel+plates+faults','real_inspection','CC BY 4.0'),
 ('robot_failures',UCI+'/static/public/138/robot+execution+failures.zip',UCI+'/dataset/138/robot+execution+failures','physical_robot_experiments_after_detection','CC BY 4.0'),
 ('nasa_milling','https://phm-datasets.s3.amazonaws.com/NASA/3.+Milling.zip','https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/','physical_milling_experiments','NASA repository attribution and donor notice; retain archive documentation'),
 ('nasa_ims','https://phm-datasets.s3.amazonaws.com/NASA/4.+Bearings.zip','https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/','physical_accelerated_life','NASA repository attribution and donor notice; retain archive documentation'),
 ('femto','https://phm-datasets.s3.amazonaws.com/NASA/10.+FEMTO+Bearing.zip','https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/','physical_accelerated_life','NASA repository attribution and donor notice; retain archive documentation'),
]

def download(source):
 name,url,page,kind,license=source
 folder=ROOT/'raw'/name;folder.mkdir(parents=True,exist_ok=True)
 target=folder/'source.zip';start=time.monotonic()
 try:
  if not target.exists() or not zipfile.is_zipfile(target):
   temporary=target.with_suffix('.part')
   with httpx.Client(follow_redirects=True,timeout=httpx.Timeout(120,read=120)) as client:
    with client.stream('GET',url) as r:
     r.raise_for_status();expected=int(r.headers.get('content-length') or 0)
     with temporary.open('wb') as out:
      for chunk in r.iter_bytes(4*1024*1024):out.write(chunk)
   if expected and temporary.stat().st_size!=expected:raise ValueError('Incomplete download')
   if not zipfile.is_zipfile(temporary):raise ValueError('Not a ZIP archive')
   temporary.replace(target)
  digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
  with zipfile.ZipFile(target) as z:
   members=[{'name':i.filename,'bytes':i.file_size} for i in z.infolist()]
   # Do not execute bundled programs or blindly extract third-party archive paths.
   for member in z.infolist():
    relative=Path(member.filename.replace('\\','/'))
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive path')
    if member.is_dir() or member.file_size>800_000_000:continue
    if relative.suffix.lower() not in ('.csv','.txt','.data','.nna','.mat','.pdf','.md','.json') and relative.name not in ('Faults27x7_var','secom_labels','secom_data'):continue
    if name in ('nasa_ims','femto') and relative.suffix.lower() not in ('.txt','.pdf','.md'):continue
    destination=folder/'extracted'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists() and destination.stat().st_size==member.file_size:continue
    with z.open(member) as inp,destination.open('wb') as out:
     import shutil;shutil.copyfileobj(inp,out)
  result={'name':name,'status':'downloaded','archive':str(target),'download_url':url,'source_page':page,'provenance':kind,'license':license,
   'bytes':target.stat().st_size,'sha256':digest,'members':members,'seconds':round(time.monotonic()-start,2)}
  print(json.dumps({k:v for k,v in result.items() if k not in ('members','license')},ensure_ascii=False),flush=True)
  (folder/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  return result
 except Exception as error:
  result={'name':name,'status':'unavailable','download_url':url,'source_page':page,'error':str(error)}
  print(json.dumps(result,ensure_ascii=False),flush=True);return result

if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:results=list(executor.map(download,SOURCES))
 (ROOT/'download_manifest.json').write_text(json.dumps({'downloaded_at':datetime.now(timezone.utc).isoformat(),'sources':results,
 'excluded':[{'name':'AI4I / C-MAPSS / naval propulsion condition','reason':'synthetic or simulated; not eligible as real industrial evidence'},
 {'name':'All worldwide industrial datasets','reason':'not an enumerable or exhaustively accessible universe; catalogue limited to the explicitly verified public primary sources'}]},ensure_ascii=False,indent=2),encoding='utf-8')

"""Create dedicated remote acceptance databases; never modify production data."""
import hashlib,json,secrets,sys,argparse
from datetime import datetime,timezone
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.d1_identity import configuration,D1Store

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    source=configuration()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)
    if args.resume:
        candidates=sorted((ROOT/'.secrets').glob('acceptance-*/manifest.json'),key=lambda p:p.stat().st_mtime)
        if not candidates:raise RuntimeError('No isolated acceptance environment to resume')
        private=candidates[-1].parent;manifest=json.loads(candidates[-1].read_text());stamp=manifest['stamp']
        if manifest['scope']!='isolated_cloudflare_acceptance':raise RuntimeError('Invalid acceptance scope')
    else:
        private=ROOT/'.secrets'/('acceptance-'+stamp);private.mkdir()
        manifest={'scope':'isolated_cloudflare_acceptance','stamp':stamp,'databases':{},'private_directory':str(private)}
    manifest_path=private/'manifest.json'
    token=Path(source['token_file']).read_text(encoding='utf-8').strip()
    for kind in ('identity','business'):
        if kind in manifest['databases']:
            cfg=json.loads((private/(kind+'.json')).read_text());cfg['persistent_connection']=True
            (private/(kind+'.json')).write_text(json.dumps(cfg,indent=2),encoding='utf-8')
            continue
        name='fp-acceptance-'+kind+'-'+stamp.lower()
        response=httpx.post(f"https://api.cloudflare.com/client/v4/accounts/{source['account_id']}/d1/database",headers={'Authorization':'Bearer '+token},json={'name':name},timeout=30)
        body=response.json()
        if not response.is_success or not body.get('success'):raise RuntimeError('Unable to create isolated D1: '+str(response.status_code))
        identifier=body['result']['uuid']
        manifest['databases'][kind]={'name':name,'id':identifier}
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        cfg={'account_id':source['account_id'],'database_id':identifier,'token_file':source['token_file'],'persistent_connection':True}
        (private/(kind+'.json')).write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        print(kind+' isolated D1 created',flush=True)
    identity=D1Store(json.loads((private/'identity.json').read_text()))
    schema=(ROOT/'deploy/d1-identity-schema.sql').read_text(encoding='utf-8')
    identity.batch([{'sql':sql} for sql in schema.split(';') if sql.strip()])
    password=secrets.token_urlsafe(30)
    (private/'credentials.json').write_text(json.dumps({'user_id':'10001','password':password}),encoding='utf-8')
    identity.batch([{'sql':'INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash,active,version) VALUES(10001,?,?,?,?,1,1) ON CONFLICT(user_id) DO UPDATE SET password_hash=excluded.password_hash','params':['全流程隔离验收','开发者',0,hashlib.sha256(password.encode()).hexdigest()]}])
    pointer=ROOT/'.secrets/acceptance-current.json'
    pointer.write_text(json.dumps({'directory':str(private)},indent=2),encoding='utf-8')
    public=ROOT/'outputs/full-acceptance';public.mkdir(exist_ok=True)
    (public/'remote-environment.json').write_text(json.dumps({'stamp':stamp,'scope':manifest['scope'],'databases':manifest['databases']},indent=2),encoding='utf-8')
    print('Isolated Cloudflare environment ready; credentials remain private.',flush=True)

if __name__=='__main__':main()

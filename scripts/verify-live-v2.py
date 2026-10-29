"""Read-only live V2 smoke checks; uses an existing credential, never resets it."""
import hashlib
import json
import sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.d1_identity import D1Store

def main():
    base='https://factorypulse.griffonage2077.workers.dev'
    path=ROOT/'.secrets/identity.json'
    config=json.loads(path.read_text(encoding='utf-8'))
    config['token_file']=str(path.parent/config['token_file'])
    password=(ROOT/'.secrets/cloud-admin-password').read_text(encoding='utf-8').strip()
    candidates=D1Store(config).batch([{'sql':'SELECT user_id FROM auth_users WHERE active=1 AND password_hash=? LIMIT 1','params':[hashlib.sha256(password.encode()).hexdigest()]}])[0]['results']
    checks=[]
    with httpx.Client(base_url=base,headers={'Origin':base},timeout=90) as c:
        for p in ['/','/api/health','/api/auth/status']:
            r=c.get(p);v=r.json() if 'json' in r.headers.get('content-type','') else {}
            checks.append({'path':p,'status':r.status_code,'schema_configured':v.get('business_schema_configured')})
        if candidates:
            r=c.post('/api/auth/login',json={'username':str(candidates[0]['user_id']),'password':password})
            checks.append({'path':'/api/auth/login','status':r.status_code})
            if r.status_code!=200:raise RuntimeError('Existing credential failed; no reset attempted')
            for p in ['/api/overview','/api/data/summary','/api/data-quality','/api/work-orders','/api/resources/inventory','/api/analysis/equipment?limit=1']:
                r=c.get(p);v=r.json()
                check={'path':p,'status':r.status_code,'schema_version':v.get('schema_version'),'computed_by':v.get('computed_by')}
                if r.status_code!=200:check['detail']=v.get('detail')
                if p=='/api/overview':check.update({'devices':len(v.get('devices',[])),'total':v.get('metrics',{}).get('total')})
                if p=='/api/data-quality':check['readings']=v.get('reading_count')
                checks.append(check);print(json.dumps(check,ensure_ascii=False),flush=True)
            c.post('/api/auth/logout',json={})
        else:
            checks.append({'authenticated_checks':'not_run','reason':'No stored credential matches an active account; no password changed'})
    report=ROOT/'outputs/database-v2/live-verification.json'
    report.write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False,indent=2),flush=True)
    if any(x.get('status',200)!=200 for x in checks):sys.exit(1)

if __name__=='__main__':main()

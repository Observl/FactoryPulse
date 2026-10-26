// Fast, isolated forwarding checks: no Cloudflare writes or Python computation.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
const origin='https://factorypulse.griffonage2077.workers.dev';
const seen=[];
const mf=new Miniflare({
 modules:true,scriptPath:new URL('./worker.mjs',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1'),
 compatibilityDate:'2026-08-06',d1Databases:{DB:'isolated-proxy-identities'},
 bindings:{ALLOWED_ORIGINS:origin,BUSINESS_API_ORIGIN:'https://compute.example.invalid'},
 outboundService:async request=>{
  seen.push({url:request.url,method:request.method,origin:request.headers.get('Origin'),cookie:request.headers.get('Cookie'),body:await request.text()});
  return new Response(JSON.stringify({detail:'simulated solver validation conflict'}),{status:409,headers:{'Content-Type':'application/json'}});
 },
});
try{
 const db=await mf.getD1Database('DB');
 const schema=await readFile(new URL('../../deploy/d1-identity-schema.sql',import.meta.url),'utf8');
 for(const sql of schema.split(';').filter(s=>s.trim()))await db.prepare(sql).run();
 await db.prepare('INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash) VALUES(10001,?,?,0,?)').bind('Isolated developer','开发者','not-a-live-password').run();
 const token='isolated-forwarding-session';
 await db.prepare('INSERT INTO auth_sessions VALUES(?,?,?)').bind(createHash('sha256').update(token).digest('hex'),'10001','2099-01-01T00:00:00+00:00').run();
 const payload=JSON.stringify({scenario_id:'TEST',request_id:'isolated-request'});
 const response=await mf.dispatchFetch(origin+'/api/schedule/generate?preview=true',{method:'POST',headers:{Origin:origin,Cookie:'factorypulse_session='+token,'Content-Type':'application/json'},body:payload});
 assert.equal(response.status,409);assert.equal((await response.json()).detail,'simulated solver validation conflict');
 assert.equal(response.headers.get('Access-Control-Allow-Origin'),origin);
 assert.equal(seen.length,1);assert.equal(seen[0].url,'https://compute.example.invalid/api/schedule/generate?preview=true');
 assert.equal(seen[0].method,'POST');assert.equal(seen[0].origin,origin);assert.equal(seen[0].body,payload);assert.equal(seen[0].cookie,'factorypulse_session='+token);
 const anonymous=await mf.dispatchFetch(origin+'/api/strategies/compare');assert.equal(anonymous.status,401);assert.equal(seen.length,1);
 const foreign=await mf.dispatchFetch(origin+'/api/schedule/generate',{method:'POST',headers:{Origin:'https://untrusted.invalid',Cookie:'factorypulse_session='+token},body:payload});assert.equal(foreign.status,403);assert.equal(seen.length,1);
 console.log('Business proxy passed: authenticated body/cookie forwarding, backend status, CORS and blocked unauthorized requests.');
}finally{await mf.dispose()}

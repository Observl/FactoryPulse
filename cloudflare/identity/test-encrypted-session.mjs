import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
const base=new URL('./',import.meta.url),origin='https://session.test';
const files=['worker.mjs','business.mjs','data-sync.mjs','sql-analysis.mjs','quality-query.mjs','statistics.mjs','result-runtime.mjs','model-replay.mjs','work-orders.mjs','auth-runtime.mjs','dify.mjs'];
const wrapper=`import worker from './worker.mjs';export {IdentityRuntime} from './auth-runtime.mjs';let blocked=false;export default {fetch(r,e,c){if(new URL(r.url).pathname==='/test/block'){blocked=new URL(r.url).searchParams.get('value')==='1';return new Response('ok')}const raw=e.DB;return worker.fetch(r,{...e,DB:{prepare(...a){if(blocked)throw Error('Unexpected D1 read');return raw.prepare(...a)},batch(...a){if(blocked)throw Error('Unexpected D1 batch');return raw.batch(...a)}}},c)}}`;
const modules=[{type:'ESModule',path:'entry.mjs',contents:wrapper},...await Promise.all(files.map(async path=>({type:'ESModule',path,contents:await readFile(new URL(path,base),'utf8')})))];
const mf=new Miniflare({modules,compatibilityDate:'2026-08-06',d1Databases:{DB:'encrypted-session-test'},durableObjects:{IDENTITY_RUNTIME:{className:'IdentityRuntime',useSQLite:true}},bindings:{ALLOWED_ORIGINS:origin}});
let jar='';
const block=value=>mf.dispatchFetch(origin+'/test/block?value='+Number(value));
async function call(path,data){const response=await mf.dispatchFetch(origin+'/api'+path,{method:data?'POST':'GET',headers:{Origin:origin,Cookie:jar,'Content-Type':'application/json'},...(data?{body:JSON.stringify(data)}:{})});const cookie=response.headers.get('Set-Cookie');if(cookie)jar=cookie.split(';')[0];return {status:response.status,body:await response.json()}}
try{
 const db=await mf.getD1Database('DB');for(const sql of (await readFile(new URL('../../deploy/d1-identity-schema.sql',base),'utf8')).split(';').filter(x=>x.trim()))await db.prepare(sql).run();
 const password='isolated-encrypted-password',hash=createHash('sha256').update(password).digest('hex');
 await db.prepare("INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash) VALUES(10001,'Owner','开发者',0,?)").bind(hash).run();
 assert.equal((await call('/auth/login',{username:'10001',password})).status,200);const first=jar;
 assert.match(jar,/factorypulse_session=v2\./);assert.ok(!jar.includes('Owner'));
 assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM auth_sessions').first()).n,0);
 await block(true);
 assert.equal((await call('/auth/status')).body.user.role,'developer','valid encrypted claims need no D1 reads');
 const parts=jar.split('.');parts[2]=(parts[2][0]==='a'?'b':'a')+parts[2].slice(1);jar=parts.join('.');
 assert.equal((await call('/unknown')).status,401,'modified ciphertext must fail closed');jar=first;
 await block(false);
 assert.equal((await call('/auth/profile',{display_name:'Renamed',version:1})).status,200);
 assert.equal((await call('/unknown')).status,401,'profile/version changes revoke previous permissions');
 assert.equal((await call('/auth/login',{username:'10001',password})).status,200);const second=jar;
 await block(true);assert.equal((await call('/auth/status')).body.user.display_name,'Renamed');
 assert.equal((await call('/auth/logout',{})).status,200);jar=second;
 assert.equal((await call('/unknown')).status,401,'logout revokes copied encrypted cookies');
 await block(false);assert.equal((await call('/auth/login',{username:'10001',password})).status,200);const owner=jar;
 const created=await call('/auth/users',{display_name:'Viewer',role:'viewer',staff_id:-1,password});assert.equal(created.status,200);
 assert.equal((await call('/auth/login',{username:created.body.user_id,password})).status,200);const viewer=jar;jar=owner;
 assert.equal((await call('/auth/users/'+created.body.user_id,{display_name:'Viewer',role:'viewer',staff_id:-1,active:false,version:1})).status,200);
 jar=viewer;assert.equal((await call('/unknown')).status,401,'disabled accounts lose encrypted permissions');jar=owner;
 const changedPassword=password+'-changed';assert.equal((await call('/auth/password',{current_password:password,new_password:changedPassword})).status,200);
 jar=owner;assert.equal((await call('/unknown')).status,401,'password changes revoke all old permissions');
 assert.equal((await call('/auth/login',{username:'10001',password:changedPassword})).status,200);

 console.log('Encrypted session checks passed: zero D1 reads after login, no D1 session writes, tamper rejection, version invalidation and logout revocation.');
}finally{await mf.dispose()}

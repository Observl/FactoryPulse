import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
const base=new URL('./',import.meta.url),origin='https://identity.test';
const wrapper=`import worker from './worker.mjs';export {IdentityRuntime} from './auth-runtime.mjs';export default {fetch(r,e,c){const raw=e.DB;const wrap=(sql,params=[])=>({sql,params,bind(...p){return wrap(sql,p)}});return worker.fetch(r,{...e,DB:{prepare(sql){const stmt=wrap(sql);stmt.first=(...args)=>raw.prepare(sql).first(...args);return stmt},batch(q){if(q.some(x=>!/^SELECT\\b/i.test(x.sql)))throw Error("D1 free tier daily row write limit 7500");return raw.batch(q.map(x=>raw.prepare(x.sql).bind(...x.params)))}}},c)}}`;
const modules=[{type:'ESModule',path:'entry.mjs',contents:wrapper},...await Promise.all(['worker.mjs','business.mjs','auth-runtime.mjs','work-orders.mjs','data-sync.mjs','sql-analysis.mjs','quality-query.mjs','statistics.mjs','result-runtime.mjs','model-replay.mjs','dify.mjs'].map(async path=>({type:'ESModule',path,contents:await readFile(new URL(path,base),'utf8')})))];
const mf=new Miniflare({modules,compatibilityDate:'2026-08-06',d1Databases:{DB:'runtime-test'},durableObjects:{IDENTITY_RUNTIME:{className:'IdentityRuntime',useSQLite:true}},bindings:{ALLOWED_ORIGINS:origin}});
let jar='',checks=0;
async function call(path,method='GET',data){const r=await mf.dispatchFetch(origin+'/api/auth/'+path,{method,headers:{Origin:origin,Cookie:jar,'Content-Type':'application/json'},...(data?{body:JSON.stringify(data)}:{})});const cookie=r.headers.get('Set-Cookie');if(cookie)jar=cookie.split(';')[0];return {status:r.status,body:await r.json()}}
function check(result,status){checks++;assert.equal(result.status,status,JSON.stringify(result.body));return result.body}
try{
 const db=await mf.getD1Database('DB');for(const sql of (await readFile(new URL('../../deploy/d1-identity-schema.sql',base),'utf8')).split(';').filter(x=>x.trim()))await db.prepare(sql).run();
 const password='isolated-runtime-password',hash=createHash('sha256').update(password).digest('hex');
 await db.prepare("INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash) VALUES(10001,'Test','开发者',0,?)").bind(hash).run();
 check(await call('login','POST',{username:'10001',password:'wrong'}),401);
 check(await call('login','POST',{username:'10001',password}),200);const signed=jar;
 assert.equal(check(await call('status'),200).user.user_id,'10001');
 assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM auth_sessions').first()).n,0);
 check(await call('onboarding','POST',{step:5}),409);check(await call('onboarding','POST',{step:1}),200);
 assert.equal(check(await call('status'),200).onboarding.step,1);
 check(await call('profile','POST',{display_name:'New',version:1}),503);
 check(await call('logout','POST'),200);jar=signed;assert.equal(check(await call('status'),200).user,null);
 check(await call('login','POST',{username:'10001',password}),200);
 await db.prepare('UPDATE auth_users SET version=version+1 WHERE user_id=10001').run();const runtime=await mf.getDurableObjectNamespace('IDENTITY_RUNTIME');const stub=runtime.get(runtime.idFromName('identity-runtime-v1'));await stub.fetch('https://identity.internal/invalidate-user',{method:'POST',body:JSON.stringify({user_id:'10001'})});assert.equal(check(await call('status'),200).user,null);
 check(await call('login','POST',{username:'10001',password}),200);
 await db.prepare('UPDATE auth_users SET active=0 WHERE user_id=10001').run();await stub.fetch('https://identity.internal/invalidate-user',{method:'POST',body:JSON.stringify({user_id:'10001'})});assert.equal(check(await call('status'),200).user,null);
 for(let i=0;i<5;i++)check(await call('login','POST',{username:'99999',password}),401);
 check(await call('login','POST',{username:'99999',password}),429);
 const privateRoute=await mf.dispatchFetch(origin+'/sign-in',{method:'POST',body:'{}'});assert.notEqual(privateRoute.status,200);
 console.log(checks+' private Cloudflare session checks passed with all D1 writes denied.');
}finally{await mf.dispose()}

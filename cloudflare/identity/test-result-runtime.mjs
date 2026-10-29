import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
const base=new URL('./',import.meta.url);
const wrapper=`import {BusinessResults} from './result-runtime.mjs';import {syncedRead} from './data-sync.mjs';import {sqlRead} from './sql-analysis.mjs';import {workOrders} from './work-orders.mjs';import {business} from './business.mjs';
export class TestResults extends BusinessResults{constructor(ctx,env){const queries=[];const db=env.BUSINESS_DB;super(ctx,{...env,BUSINESS_DB:{prepare(sql){queries.push(sql);return db.prepare(sql)},batch(q){return db.batch(q)}}});this.queries=queries}fetch(r){if(new URL(r.url).pathname==='/test/queries')return Response.json(this.queries);return super.fetch(r)}}
export default {fetch(r,e){const user={user_id:r.headers.get('X-Test-User')||'A',version:1,role:'viewer'};return syncedRead(r,e,user,async()=>await sqlRead(r,e,user)||await workOrders(r,e,user)||await business(r,e,user))}}`;
const files=['worker.mjs','business.mjs','data-sync.mjs','sql-analysis.mjs','quality-query.mjs','statistics.mjs','result-runtime.mjs','model-replay.mjs','work-orders.mjs','auth-runtime.mjs','dify.mjs'];
const modules=[{type:'ESModule',path:'entry.mjs',contents:wrapper},...await Promise.all(files.map(async path=>({type:'ESModule',path,contents:await readFile(new URL(path,base),'utf8')})))];
const mf=new Miniflare({modules,compatibilityDate:'2026-08-06',d1Databases:{BUSINESS_DB:'result-test'},durableObjects:{BUSINESS_RESULTS:{className:'TestResults',useSQLite:true}},bindings:{BUSINESS_SCHEMA_VERSION:'2',BUSINESS_DATABASE_ID:'result-test'}});
try{
 const db=await mf.getD1Database('BUSINESS_DB'),fixture=JSON.parse(await readFile(new URL('../../outputs/database-v2/inplace-fixture.json',base),'utf8'));
 await db.batch(fixture.source.map(x=>db.prepare(x.sql).bind(...(x.params||[]))));await db.batch(fixture.plan.map(x=>db.prepare(x.sql).bind(...(x.params||[]))));
 for(const sql of (await readFile(new URL('../../deploy/d1-read-indexes.sql',base),'utf8')).split(';').filter(x=>x.trim()))await db.prepare(sql).run();
 await db.prepare('INSERT INTO records VALUES(?,?,?)').bind('readings',0,JSON.stringify({equipment_id:'E1',reading_id:'R1',timestamp:'2026-01-01T00:00:00Z',motor_current_a:9,_feature_fields:['motor_current_a']})).run();
 const call=(path,user='A')=>mf.dispatchFetch('https://test'+path,{headers:{'X-Test-User':user}});
 const namespace=await mf.getDurableObjectNamespace('BUSINESS_RESULTS');
 const queries=async name=>await (await namespace.get(namespace.idFromName(name)).fetch('https://results.internal/test/queries')).json();
 const first=await call('/api/data-quality');assert.equal(first.status,200);const firstBody=await first.json();assert.equal(first.headers.get('X-FP-Result-Cache'),'miss');
 const second=await call('/api/data-quality','B');assert.equal(second.status,200);assert.equal(second.headers.get('X-FP-Result-Cache'),'hit');assert.deepEqual(await second.json(),firstBody);
 assert.equal((await queries('result-test|shared|/api/data-quality')).filter(sql=>sql.includes('WITH sensor_readings AS MATERIALIZED')).length,1);
 const filtered=await call('/api/analysis/quality?equipment_id=E1');assert.equal(filtered.status,200);assert.deepEqual((await filtered.json()).records,firstBody.equipment_quality);
 assert.equal((await queries('result-test|shared|/api/data-quality')).filter(sql=>sql.includes('WITH sensor_readings AS MATERIALIZED')).length,1,'analysis must reuse the complete quality JSON');
 assert.equal((await call('/api/overview')).status,200);const before=await queries('statistics:result-test');assert.equal(before.filter(sql=>sql==='SELECT COUNT(*) AS n FROM sensor_readings').length,1);
 const summary=await call('/api/data/summary');assert.equal(summary.status,200);assert.equal((await summary.json()).record_count,1);
 const after=await queries('statistics:result-test');assert.equal(after.filter(sql=>sql==='SELECT COUNT(*) AS n FROM sensor_readings').length,1,'summary must not recount unchanged readings');
 await db.prepare('INSERT INTO records VALUES(?,?,?)').bind('staff',0,JSON.stringify({staff_id:'NEW',staff_name:'New'})).run();
 const overviewAfter=await call('/api/overview');assert.equal(overviewAfter.status,200);const overviewBody=await overviewAfter.json();assert.ok(overviewBody.counts.staff>=1);
 const afterStaff=await queries('statistics:result-test');assert.equal(afterStaff.filter(sql=>sql==='SELECT COUNT(*) AS n FROM sensor_readings').length,1,'staff changes must not recount readings');
 await db.prepare('INSERT INTO records VALUES(?,?,?)').bind('readings',1,JSON.stringify({equipment_id:'E1',reading_id:'R2',timestamp:'2026-01-01T01:00:00Z',motor_current_a:10,_feature_fields:['motor_current_a']})).run();
 const changed=await call('/api/data-quality');assert.equal(changed.headers.get('X-FP-Result-Cache'),'miss');assert.equal((await changed.json()).reading_count,2);
 const unchanged=await call('/api/data-quality');assert.equal(unchanged.headers.get('X-FP-Result-Cache'),'hit');
 const orderA=await call('/api/work-orders','A');assert.equal(orderA.status,200);const orderB=await call('/api/work-orders','B');assert.equal(orderB.headers.get('X-FP-Result-Cache'),'miss','personal result scopes must not share cached objects');
 console.log('Durable JSON checks passed: cross-user shared reports, one quality calculation, quality-field reuse, selective recount, input invalidation and personal scope isolation.');
}finally{await mf.dispose()}

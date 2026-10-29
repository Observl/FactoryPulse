import assert from 'node:assert/strict';
import {Miniflare} from 'miniflare';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {workOrders} from './work-orders.mjs';
const mf=new Miniflare({modules:true,scriptPath:new URL('./worker.mjs',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1'),compatibilityDate:'2026-08-06',d1Databases:{BUSINESS_DB:'work-orders-test',DB:'work-order-identities'}});
const admin={user_id:'10001',display_name:'Owner',role:'developer',staff_id:'0'},viewer={...admin,user_id:'10002',role:'viewer'},worker={...admin,user_id:'10003',role:'user',staff_id:'1'};
let checks=0,seq=0;
try{
 const db=await mf.getD1Database('BUSINESS_DB'),env={BUSINESS_DB:db};
 const schemas=[
 'CREATE TABLE fp_business_revision(id INTEGER PRIMARY KEY,revision INTEGER,commit_nonce TEXT)',"INSERT INTO fp_business_revision VALUES(1,0,'initial')",'CREATE TABLE fp_business_guard(id INTEGER PRIMARY KEY CHECK(id=1))','CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)',
 'CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT,PRIMARY KEY(table_name,row_index))',
 'CREATE TABLE work_orders(work_order_id TEXT PRIMARY KEY,equipment_id TEXT,content TEXT,status TEXT,updated_at TEXT)',
 'CREATE TABLE inventory_stock(scope TEXT,part_name TEXT,on_hand INTEGER CHECK(on_hand>=0),version INTEGER,counted_at TEXT,source TEXT,PRIMARY KEY(scope,part_name))',
 'CREATE TABLE inventory_reservations(work_order_id TEXT,scope TEXT,part_name TEXT,quantity INTEGER,state TEXT,PRIMARY KEY(work_order_id,part_name))',
 'CREATE TABLE inventory_movements(movement_id TEXT PRIMARY KEY,scope TEXT,part_name TEXT,work_order_id TEXT,movement_type TEXT,quantity INTEGER,note TEXT,created_at TEXT)',
 'CREATE TABLE dataset_versions(version TEXT PRIMARY KEY,metadata TEXT,archived_at TEXT)',
 'CREATE TABLE alerts(alert_id TEXT PRIMARY KEY,equipment_id TEXT,status TEXT,note TEXT,updated_at TEXT,dataset_version TEXT,prediction_at TEXT,defer_until TEXT,version INTEGER)',
 'CREATE TABLE operation_requests(request_id TEXT PRIMARY KEY,request_content TEXT,response TEXT)',
 'CREATE TABLE audit_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT,entity_id TEXT,content TEXT,created_at TEXT)',
 'CREATE TABLE maintenance_events(work_order_id TEXT PRIMARY KEY,dataset_version TEXT,equipment_id TEXT,content TEXT,verified_at TEXT)',
 'CREATE TABLE archived_records(version TEXT,table_name TEXT,row_index INTEGER,content TEXT)',
 'CREATE TABLE fp_computed_views(dataset_id TEXT,view_key TEXT,content TEXT,PRIMARY KEY(dataset_id,view_key))'];
 const selectedSchemas=process.env.FACTORYPULSE_V2_SCHEMA_FILE?JSON.parse(await readFile(process.env.FACTORYPULSE_V2_SCHEMA_FILE,'utf8')):schemas;
 for(const sql of selectedSchemas){try{await db.prepare(sql).run()}catch(error){console.error('Schema statement failed:',sql.slice(0,180));throw error}}
 if(process.env.FACTORYPULSE_V2_SCHEMA_FILE)await db.prepare("UPDATE database_schema SET migration_state='ready'").run();
 for(const [key,value] of Object.entries({last_sync_at:'fixture',business_revision:'0',source_name:'isolated',data_origin:'synthetic'}))await db.prepare('INSERT INTO settings VALUES(?,?)').bind(key,value).run();
 const start=Date.now()+86400000,at=n=>new Date(start+n*3600000).toISOString();
 const data={equipment:[{equipment_id:'E1',equipment_name:'One'},{equipment_id:'E2',equipment_name:'Two'}],maintenance_rules:['E1','E2'].map(equipment_id=>({equipment_id,maintenance_hours:2,maintenance_cost_cny:100,required_skill:'mechanic',required_staff_count:1,window_start:at(0),window_end:at(12),spare_parts:[{part_name:'part',quantity:1,available_quantity:4}]})),staff:[{staff_id:'1',staff_name:'Worker',skills:'mechanic',available_hours:10,shift_start:at(0),shift_end:at(12)}],orders:[{order_id:'P1',equipment_id:'E1',start_at:at(0),end_at:at(2),due_at:at(2)}],scenarios:[{scenario_id:'S1',maintenance_budget_cny:1000,available_staff_count:1,max_downtime_h:10}]};
 for(const [name,rows] of Object.entries(data))for(const [i,row] of rows.entries())await db.prepare('INSERT INTO records VALUES(?,?,?)').bind(name,i,JSON.stringify(row)).run();
 await db.prepare("INSERT INTO inventory_stock VALUES('fixture','part',4,1,?,'manual_count')").bind(at(0)).run();
 await db.prepare('INSERT INTO fp_computed_views VALUES(?,?,?)').bind('fixture','overview',JSON.stringify({devices:[{equipment_id:'E1',prediction_at:'2026-10-20 20:00:00'}]})).run();
 async function call(path,p,user=admin,status=200){const r=await workOrders(new Request('https://test.invalid/api'+path,{method:p?'POST':'GET',...(p?{body:JSON.stringify(p)}:{})}),env,user);assert.ok(r,'handled '+path);const b=await r.json();assert.equal(r.status,status,JSON.stringify(b));checks++;return b}
 const key=()=>({request_id:'test-operation-'+(++seq)});
 await call('/maintenance-requests',{equipment_id:'E1',action:'inspect',...key()},viewer,403);
 const confirm=await call('/alerts/E1/action',{action:'confirm',expected_dataset_version:'fixture',prediction_at:'2026-10-20 20:00:00',version:0,...key()});
 const draft=await call('/alerts/E1/action',{action:'work_order',expected_dataset_version:'fixture',prediction_at:'2026-10-20 20:00:00',version:confirm.version,...key()});
 await call('/maintenance-requests',{equipment_id:'E1',action:'duplicate',...key()},admin,409);
 const payload={scenario_id:'S1',...key()},scheduled=await call('/schedule/generate',payload);assert.equal(scheduled.scheduled.length,1);assert.ok(Date.parse(scheduled.scheduled[0].start_at.replace(' ','T')+'+08:00')>=start+2*3600000);assert.deepEqual(await call('/schedule/generate',payload),scheduled);
 const id=draft.work_order_id,flow=async()=> (await call('/work-orders/'+id+'/flow')).record;
 let o=await flow();await call('/work-orders/'+id+'/approval',{decision:'approve',version:0,...key()},admin,422);
 await call('/work-orders/'+id+'/approval',{decision:'approve',version:o.version,...key()},viewer,403);
 const preview={version:o.version,staff_ids:['1'],start_at:o.start_at,end_at:o.end_at,scenario_id:'S1',note:'timeline preview',apply:false,...key()};const checked=await call('/work-orders/'+id+'/timeline',preview);assert.ok(checked.preview);
 await call('/work-orders/'+id+'/timeline',{...preview,apply:true,state_fingerprint:'stale'},admin,409);
 await call('/work-orders/'+id+'/timeline',{...preview,apply:true,state_fingerprint:checked.state_fingerprint});o=await flow();
 const approve={decision:'approve',version:o.version,...key()};await call('/work-orders/'+id+'/approval',approve);await call('/work-orders/'+id+'/approval',approve);
 assert.equal((await db.prepare("SELECT SUM(quantity) AS n FROM inventory_reservations WHERE state='reserved'").first()).n,1);
 for(const action of ['accept','start','pause','resume','finish','verify']){
  o=await flow();const p={action,version:o.version,note:'isolated lifecycle check',actor:'forged client actor',...key(),...(action==='finish'?{actual_hours:2,actual_cost_cny:90}:{}),...(action==='verify'?{actual_parts:[{part_name:'part',quantity:1}]}:{})};
  if(action==='verify')await call('/work-orders/'+id+'/transition',p,worker,403);
  const result=await call('/work-orders/'+id+'/transition',p,action==='verify'?admin:worker);assert.deepEqual(await call('/work-orders/'+id+'/transition',p,action==='verify'?admin:worker),result);
 }
 assert.equal((await flow()).status,'已完成');assert.equal((await db.prepare("SELECT on_hand FROM inventory_stock").first()).on_hand,3);assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM maintenance_events').first()).n,1);
 o=await flow();await call('/work-orders/'+id+'/manage',{action:'archive',version:o.version,note:'archive completed',...key()});assert.equal((await call('/work-orders')).records.length,0);o=await flow();await call('/work-orders/'+id+'/manage',{action:'restore',version:o.version,note:'restore completed',...key()});
 await call('/resources/staff/2',{staff_name:'Invalid',skills:['mechanic'],available_hours:12,shift_start:at(0),shift_end:at(1)},admin,422);
 await call('/resources/inventory/part',{on_hand:3,version:2,note:'stock recount'});assert.equal((await call('/resources/inventory')).records[0].on_hand,3);
 await call('/maintenance/timeline');await call('/maintenance/time-readiness');await call('/operations/resource-occupancy');await call('/equipment/E1/operations');
 // A read must not load unrelated business tables.
 const reads=[];const scopedDB={prepare(sql){reads.push(sql);return db.prepare(sql)},batch(statements){return db.batch(statements)}};
 await workOrders(new Request('https://test/api/resources/staff'),{BUSINESS_DB:scopedDB},admin);
 assert.ok(reads.some(sql=>sql.includes('FROM records')));
 assert.ok(!reads.some(sql=>/FROM (work_orders|alerts|inventory_stock|inventory_reservations|dataset_versions)/.test(sql)));
 reads.length=0;await workOrders(new Request('https://test/api/work-orders/'+id+'/flow'),{BUSINESS_DB:scopedDB},admin);
 assert.ok(reads.some(sql=>sql.includes('work_order_id=?')));assert.ok(!reads.some(sql=>sql.includes('FROM records')));
 const page=await workOrders(new Request('https://test/api/work-orders?limit=1'),env,admin);const paged=await page.json();assert.ok(paged.records.length<=1);
 // Two writes that read the same revision cannot both commit.
 const req=id=>new Request('https://test.invalid/api/maintenance-requests',{method:'POST',body:JSON.stringify({equipment_id:'E2',action:'concurrent request',request_id:id})});
 const races=await Promise.all([workOrders(req('concurrent-01'),env,admin),workOrders(req('concurrent-02'),env,admin)]);assert.deepEqual(races.map(x=>x.status).sort(),[200,409]);checks++;
 assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM work_orders WHERE equipment_id='E2'").first()).n,1);
 const identity=await mf.getD1Database('DB');for(const sql of (await readFile(new URL('../../deploy/d1-identity-schema.sql',import.meta.url),'utf8')).split(';').filter(x=>x.trim()))await identity.prepare(sql).run();
 const password='isolated-worker-integration';await identity.prepare("INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash) VALUES(10001,'Owner','开发者',0,?)").bind(createHash('sha256').update(password).digest('hex')).run();
 const login=await mf.dispatchFetch('https://test.invalid/api/auth/login',{method:'POST',headers:{Origin:'https://test.invalid','Content-Type':'application/json'},body:JSON.stringify({username:'10001',password})});assert.equal(login.status,200);
 const integrated=await mf.dispatchFetch('https://test.invalid/api/maintenance-requests',{method:'POST',headers:{Origin:'https://test.invalid',Cookie:login.headers.get('Set-Cookie').split(';')[0],'Content-Type':'application/json'},body:JSON.stringify({equipment_id:'E1',action:'real identity role integration',...key()})});assert.equal(integrated.status,200,await integrated.text());checks++;
 console.log(checks+' native Workers/D1 work-order checks passed: lifecycle, roles, schedule, production exclusion, timeline, inventory, idempotency and concurrent atomicity.');
}finally{await mf.dispose()}

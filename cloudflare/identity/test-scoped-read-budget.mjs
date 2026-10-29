import assert from 'node:assert/strict';
import {Miniflare} from 'miniflare';
import {workOrders} from './work-orders.mjs';
const mf=new Miniflare({modules:true,script:'export default {fetch(){return new Response("test")}}',compatibilityDate:'2026-08-06',d1Databases:{DB:'scoped-budget'}});
try{
 const db=await mf.getD1Database('DB');
 const schema=['CREATE TABLE fp_business_revision(id INTEGER PRIMARY KEY,revision INTEGER)','INSERT INTO fp_business_revision VALUES(1,1)','CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)',"INSERT INTO settings VALUES('last_sync_at','v1')",'CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT,PRIMARY KEY(table_name,row_index))','CREATE TABLE work_orders(work_order_id TEXT PRIMARY KEY,equipment_id TEXT,content TEXT,status TEXT,updated_at TEXT)','CREATE TABLE inventory_stock(scope TEXT,part_name TEXT,on_hand INTEGER)','CREATE TABLE inventory_reservations(scope TEXT,part_name TEXT,state TEXT)','CREATE TABLE dataset_versions(version TEXT,metadata TEXT)','CREATE TABLE alerts(alert_id TEXT,equipment_id TEXT,dataset_version TEXT)','CREATE TABLE audit_events(event_id INTEGER PRIMARY KEY,entity_id TEXT,content TEXT)','CREATE INDEX audit_by_entity ON audit_events(entity_id,event_id)'];
 for(const sql of schema)await db.prepare(sql).run();
 await db.prepare('INSERT INTO records VALUES(?,?,?)').bind('staff',0,JSON.stringify({staff_id:'1',staff_name:'Only staff'})).run();
 for(let offset=0;offset<300;offset+=30){const batch=[];for(let n=offset;n<offset+30;n++){
  batch.push(db.prepare('INSERT INTO records VALUES(?,?,?)').bind('equipment',n,JSON.stringify({equipment_id:'E'+n})));
  batch.push(db.prepare('INSERT INTO work_orders VALUES(?,?,?,?,?)').bind('W'+n,'E'+n,JSON.stringify({dataset_version:'v1',version:1}),'草稿·待排程','2026-01-01'));
  batch.push(db.prepare('INSERT INTO inventory_stock VALUES(?,?,?)').bind('v1','P'+n,1));batch.push(db.prepare('INSERT INTO inventory_reservations VALUES(?,?,?)').bind('v1','P'+n,'reserved'));
  batch.push(db.prepare('INSERT INTO dataset_versions VALUES(?,?)').bind('old'+n,'{}'));batch.push(db.prepare('INSERT INTO alerts VALUES(?,?,?)').bind('A'+n,'E'+n,'v1'));
 }await db.batch(batch)}
 const oldQueries=['SELECT revision FROM fp_business_revision WHERE id=1','SELECT key,value FROM settings',"SELECT * FROM records WHERE table_name IN ('equipment','maintenance_rules','staff','orders','scenarios')",'SELECT * FROM work_orders','SELECT * FROM inventory_stock','SELECT * FROM inventory_reservations','SELECT * FROM dataset_versions','SELECT * FROM alerts'];
 const baseline=(await db.batch(oldQueries.map(sql=>db.prepare(sql)))).reduce((sum,result)=>sum+result.meta.rows_read,0);
 let reads=0;const wrap=raw=>({raw,bind(...params){return wrap(raw.bind(...params))},async all(){const result=await raw.all();reads+=result.meta.rows_read;return result},async first(){return (await this.all()).results[0]||null}});
 const tracked={prepare(sql){return wrap(db.prepare(sql))},async batch(statements){const result=await db.batch(statements.map(x=>x.raw));reads+=result.reduce((sum,r)=>sum+r.meta.rows_read,0);return result}};
 const user={user_id:'1',role:'admin'};
 let response=await workOrders(new Request('https://test/api/resources/staff'),{BUSINESS_DB:tracked},user);assert.equal(response.status,200);assert.equal((await response.json()).records.length,1);const staffReads=reads;assert.ok(staffReads<baseline/10);
 reads=0;response=await workOrders(new Request('https://test/api/work-orders/W1/flow'),{BUSINESS_DB:tracked},user);assert.equal(response.status,200);assert.equal((await response.json()).record.work_order_id,'W1');const flowReads=reads;assert.ok(flowReads<baseline/10);
 const responsePage=await workOrders(new Request('https://test/api/work-orders?limit=2'),{BUSINESS_DB:db},user),page=await responsePage.json();assert.equal(page.records.length,2);assert.ok(page.next_cursor);
 const cursor=new URLSearchParams({limit:'2',before_updated_at:page.next_cursor.updated_at,before_id:page.next_cursor.work_order_id});const nextPage=await (await workOrders(new Request('https://test/api/work-orders?'+cursor),{BUSINESS_DB:db},user)).json();assert.equal(nextPage.records.length,2);assert.ok(!nextPage.records.some(row=>page.records.some(previous=>previous.work_order_id===row.work_order_id)));
 console.log(JSON.stringify({old_full_state_rows:baseline,staff_read_rows:staffReads,single_work_order_flow_rows:flowReads,cursor_pages_have_no_duplicates:true}));
}finally{await mf.dispose()}

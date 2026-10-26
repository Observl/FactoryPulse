import assert from 'node:assert/strict';
import {Miniflare} from 'miniflare';
import {business} from './business.mjs';
const mf=new Miniflare({modules:true,script:'export default {fetch(){return new Response("test")}}',compatibilityDate:'2026-08-06',d1Databases:{BUSINESS_DB:'isolated-business'}});
let checks=0;
try{
 const db=await mf.getD1Database('BUSINESS_DB');
 for(const sql of [
  'CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)',
  'CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT,PRIMARY KEY(table_name,row_index))',
  'CREATE TABLE fp_computed_views(dataset_id TEXT,view_key TEXT,content TEXT,PRIMARY KEY(dataset_id,view_key))',
  'CREATE TABLE alerts(equipment_id TEXT,dataset_version TEXT,status TEXT,note TEXT,updated_at TEXT)',
  'CREATE TABLE work_orders(work_order_id TEXT,content TEXT,status TEXT,updated_at TEXT)',
 ])await db.prepare(sql).run();
 await db.prepare("INSERT INTO settings VALUES('last_sync_at','remote-fixture')").run();
 const overview={metrics:{total:1},devices:[{equipment_id:'D1-DEVICE',alert_status:'待确认'}],sync:{},analytics:{xgboost:'ready',evaluation:{f1:0.5}}};
 await db.prepare('INSERT INTO fp_computed_views VALUES(?,?,?)').bind('remote-fixture','overview',JSON.stringify(overview)).run();
 await db.prepare('INSERT INTO records VALUES(?,?,?)').bind('equipment',0,JSON.stringify({equipment_id:'D1-DEVICE'})).run();
 await db.prepare('INSERT INTO alerts VALUES(?,?,?,?,?)').bind('D1-DEVICE','remote-fixture','已确认','cloud note','2026-10-23').run();
 const env={BUSINESS_DB:db,BUSINESS_DATABASE_ID:'isolated-business'};
 const call=async(path,method='GET')=>business(new Request('https://test.invalid/api'+path,{method}),env,{role:'viewer'});
 let response=await call('/overview'),data=await response.json();assert.equal(response.status,200);assert.equal(data.devices[0].equipment_id,'D1-DEVICE');assert.equal(data.devices[0].alert_status,'已确认');assert.equal(data.storage_provider,'cloudflare_d1');checks++;
 response=await call('/records/equipment');data=await response.json();assert.equal(data.total,1);assert.equal(data.records[0].equipment_id,'D1-DEVICE');checks++;
 assert.equal((await call('/records/auth_users')).status,404);checks++;
 assert.equal((await call('/records/equipment?limit=-1')).status,400);checks++;
 response=await call('/model/evaluation');data=await response.json();assert.equal(data.status,'ready');assert.equal(data.evaluation.f1,0.5);checks++;
 assert.equal((await call('/schedule/generate','POST')).status,403);checks++;
 await db.prepare("UPDATE settings SET value='new-version' WHERE key='last_sync_at'").run();
 assert.equal((await call('/overview')).status,503);checks++;
 console.log(`${checks} business D1 checks passed: remote source, alert overlay, table allowlist, validation, model evidence and stale-version rejection`);
}finally{await mf.dispose()}

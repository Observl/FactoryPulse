import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
import {modelReplay,eventTimeline} from './model-replay.mjs';
const mf=new Miniflare({modules:true,script:'export default {fetch(){return new Response("test")}}',compatibilityDate:'2026-08-06',d1Databases:{DB:'replay-budget'}});
try{
 const db=await mf.getD1Database('DB'),fixture=JSON.parse(await readFile(new URL('../../outputs/database-v2/inplace-fixture.json',import.meta.url),'utf8'));
 await db.batch(fixture.source.map(x=>db.prepare(x.sql).bind(...(x.params||[]))));await db.batch(fixture.plan.map(x=>db.prepare(x.sql).bind(...(x.params||[]))));
 for(const sql of (await readFile(new URL('../../deploy/d1-read-indexes.sql',import.meta.url),'utf8')).split(';').filter(x=>x.trim()))await db.prepare(sql).run();
 const version=(await db.prepare("SELECT value FROM business_settings WHERE key='last_sync_at'").first()).value;
 const series=[{equipment_id:'E1',timestamp:'2026-01-01T08:00:00Z',alert:false},{equipment_id:'E1',timestamp:'2026-01-04T08:00:00Z',alert:true}];
 await db.prepare('INSERT INTO prediction_runs(run_id,dataset_version,model_version,content,created_at) VALUES(?,?,?,?,?)').bind('RUN',version,'MODEL',JSON.stringify({replay:series,summary:{xgboost:'ready',evaluation:{events:[]}}}),'2026-01-01').run();
 for(let offset=0;offset<300;offset+=50)await db.batch(Array.from({length:50},(_,i)=>db.prepare('INSERT INTO maintenance_history(maintenance_id,equipment_id,maintenance_date,maintenance_type) VALUES(?,?,?,?)').bind('M'+(offset+i),'E1','2020-01-01T00:00:00Z','old')));
 await db.prepare('INSERT INTO maintenance_history(maintenance_id,equipment_id,maintenance_date,maintenance_type) VALUES(?,?,?,?)').bind('CURRENT','E1','2026-01-02T00:00:00Z','Relevant').run();
 const all=await db.prepare("SELECT content FROM records WHERE table_name='maintenance_history' ORDER BY row_index").all();const expected=eventTimeline(series,[],all.results.map(x=>JSON.parse(x.content)));
 let reads=0;const queries=[];const wrap=(raw,sql)=>({bind(...params){return wrap(raw.bind(...params),sql)},async first(){const result=await raw.all();reads+=result.meta.rows_read;return result.results[0]||null},async all(){const result=await raw.all();reads+=result.meta.rows_read;return result}});
 const tracked={prepare(sql){queries.push(sql);return wrap(db.prepare(sql),sql)}};
 const replay=await modelReplay(tracked,version,true);assert.deepEqual(replay.timeline,expected);assert.equal(replay.timeline.filter(x=>x.kind==='maintenance').length,1);
 assert.ok(reads<all.meta.rows_read/5,`scoped replay must avoid scanning history: ${all.meta.rows_read} -> ${reads}`);
 const plan=await db.prepare('EXPLAIN QUERY PLAN SELECT * FROM model_run_history WHERE dataset_version=? ORDER BY created_at DESC,run_id DESC LIMIT 1').bind(version).all();assert.ok(plan.results.some(x=>x.detail.includes('model_run_history_dataset_created')));
 console.log(JSON.stringify({old_maintenance_history_rows:all.meta.rows_read,new_replay_total_rows:reads,timeline_results_unchanged:true,latest_run_uses_index:true}));
}finally{await mf.dispose()}

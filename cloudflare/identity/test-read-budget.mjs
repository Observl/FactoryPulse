import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
import {qualityQuery} from './quality-query.mjs';
import {sqlRead} from './sql-analysis.mjs';
assert.equal(qualityQuery,(await readFile(new URL('../../deploy/d1-quality-report.sql',import.meta.url),'utf8')).replace(/\r\n/g,'\n').trim().replace(/;$/,''));
const fixture=JSON.parse(await readFile(new URL('../../outputs/database-v2/inplace-fixture.json',import.meta.url),'utf8'));
const mf=new Miniflare({modules:true,script:'export default {fetch(){return new Response("test")}}',compatibilityDate:'2026-08-06',d1Databases:{DB:'read-budget'}});
try{
 const db=await mf.getD1Database('DB');
 await db.batch(fixture.source.map(x=>db.prepare(x.sql).bind(...(x.params||[]))));
 await db.batch(fixture.plan.map(x=>db.prepare(x.sql).bind(...(x.params||[]))));
 for(let offset=0;offset<400;offset+=50)await db.batch(Array.from({length:50},(_,i)=>{const n=offset+i;return db.prepare('INSERT INTO records VALUES(?,?,?)').bind('readings',n,JSON.stringify({reading_id:'R'+n,equipment_id:'E1',timestamp:new Date(Date.UTC(2026,0,1)+n*60000).toISOString(),motor_current_a:n%9===0?null:9,_feature_fields:['motor_current_a']}))}));
 const old=await db.prepare('SELECT * FROM v_quality_report').all();
 const oldFields=await db.prepare("SELECT DISTINCT json_extract(attributes,'$._feature_fields') AS fields FROM sensor_readings").all();
 const oldGaps=await db.prepare('SELECT * FROM v_sampling_interruptions ORDER BY equipment_id,start_at LIMIT 100').all();
 const next=await db.prepare(qualityQuery).all();const report=JSON.parse(next.results[0].report);assert.ok(Math.abs(report.data_age_hours-old.results[0].data_age_hours)<.01);delete report.data_age_hours;const previous={...old.results[0]};delete previous.data_age_hours;assert.deepEqual(report,previous);
 const before=old.meta.rows_read+oldFields.meta.rows_read+oldGaps.meta.rows_read,after=next.meta.rows_read;
 assert.ok(after<before,`quality reads must decrease: ${before} -> ${after}`);
 const statements=[];const tracked={prepare(sql){statements.push(sql);return db.prepare(sql)}};
 const overview=await sqlRead(new Request('https://test/api/overview'),{BUSINESS_DB:tracked,BUSINESS_SCHEMA_VERSION:'2'},{});
 assert.equal(overview.status,200);assert.equal(statements.filter(sql=>sql.includes('v_dashboard_devices')).length,1);
 console.log(JSON.stringify({quality_rows_read_before:before,quality_rows_read_after:after,reduction_percent:Math.round((1-after/before)*100),overview_complex_view_evaluations:1}));
}finally{await mf.dispose()}

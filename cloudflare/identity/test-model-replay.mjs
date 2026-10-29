import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {eventTimeline,modelReplay} from './model-replay.mjs';
const series=[{equipment_id:'E1',reading_id:'R1',timestamp:'2026-01-01T00:00:00',alert:true,score:.7,observed_future_failure:1},{equipment_id:'E1',timestamp:'2026-01-02T00:00:00',alert:true,score:.8},{equipment_id:'E1',timestamp:'2026-01-03T00:00:00',alert:false,score:.2},{equipment_id:'E1',timestamp:'2026-01-04T00:00:00',alert:true,score:.8,observed_future_failure:0}];
const faults=[{equipment_id:'E1',failure_at:'2026-01-03T12:00:00',detected:true,lead_hours:84}];
const maintenance=[{equipment_id:'E1',maintenance_date:'2026-01-03T13:00:00',maintenance_type:'检修'},{equipment_id:'OTHER',maintenance_date:'2026-01-02'}];
const timeline=eventTimeline(series,faults,maintenance);
assert.equal(timeline.filter(x=>x.kind==='alert').length,2);assert.equal(timeline.filter(x=>x.kind==='maintenance').length,1);assert.equal(timeline.filter(x=>x.kind==='failure').length,1);
const row={run_id:'RUN1',dataset_version:'V1',model_version:'MODEL1',content:JSON.stringify({replay:series,summary:{xgboost:'ready',evaluation:{threshold:.6,events:faults}}})};
let maintenanceQueries=0;
const db={prepare(sql){return {bind(value){if(sql.includes('prediction_runs')){assert.equal(value,'V1');return {async first(){return row}}}maintenanceQueries++;const bounds=JSON.parse(value);assert.equal(bounds.length,1);assert.equal(bounds[0].equipment_id,'E1');assert.match(sql,/JOIN records/);return {async all(){return {results:maintenance.map(value=>({content:JSON.stringify(value)}))}}}}}}};
let result=await modelReplay(db,'V1');assert.equal(result.run_id,'RUN1');assert.equal(maintenanceQueries,1);assert.deepEqual(result.series,series);assert.deepEqual(result.events,faults);assert.equal(result.evaluation.threshold,.6);
result=await modelReplay({prepare(){return {bind(){return {async first(){return null}}}}}},'V2');assert.deepEqual(result.series,[]);assert.equal(result.status,'unavailable');
if(process.argv[2]){const fixture=JSON.parse(await readFile(process.argv[2],'utf8'));const actual=eventTimeline(fixture.series,fixture.faults,fixture.maintenance);assert.deepEqual(actual.map(x=>({...x,title:x.kind==='failure'?'真实故障开始':x.title})),fixture.expected);console.log('Production frozen replay parity passed:',fixture.series.length,'points,',actual.length,'timeline events')}
console.log('Model replay tests passed: real evidence fields, alert episodes, maintenance boundaries, missing version');

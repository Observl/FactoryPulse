import fs from 'node:fs';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source=fs.readFileSync(new URL('../src/operational-tasks.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText;
const {operationalTasks,personalTasks}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const now=Date.parse('2026-10-20T10:00:00Z');
const devices=[{equipment_id:'E1',equipment_name:'设备1',risk_score:.7,prediction_at:'2026-10-20T08:00:00Z'},{equipment_id:'E2',equipment_name:'未知',risk_score:.9,risk_available:false}];
const alert={alert_id:'A1',equipment_id:'E1',dataset_version:'v1',prediction_at:devices[0].prediction_at,status:'已延期',defer_until:'2026-10-20T11:00:00Z'};
assert.equal(operationalTasks(devices,[],[alert],'v1',now).length,0);
const due=operationalTasks(devices,[],[{...alert,defer_until:'2026-10-20T09:00:00Z'}],'v1',now);
assert.equal(due.length,1);assert.equal(due[0].overdue,true);assert.equal(due[0].status,'延期复核到期');
assert.equal(operationalTasks(devices,[],[{...alert,dataset_version:'old',status:'已转工单'}],'v1',now).length,1);
const orders=[{work_order_id:'W1',equipment_id:'E1',dataset_version:'old',status:'已批准',staff_id:'T1',end_at:'2026-10-20T09:00:00Z'},{work_order_id:'W2',equipment_id:'E1',status:'待验收',staff_id:'T1'},{work_order_id:'W3',equipment_id:'E1',status:'执行中',staff_id:'T2'},{work_order_id:'W4',equipment_id:'E1',status:'已完成',staff_id:'T1'}];
const technician=operationalTasks(devices,orders,[],'v1',now,'T1');
assert.deepEqual(technician.map(task=>task.id),['W1']);assert.equal(technician[0].oldVersion,true);
assert.equal(operationalTasks([],orders,[],'v1',now).some(task=>task.id==='W4'),false);
assert.equal(operationalTasks(devices,[],[{...alert,status:'已确认'}],'v1',now)[0].status,'已确认·待决定维护');
for(const changed of [{risk_score:.01},{risk_available:false}]){
 const pending=operationalTasks([{...devices[0],...changed}],[],[{...alert,defer_until:'2026-10-20T09:00:00Z'}],'v1',now);
 assert.equal(pending.length,1);assert.equal(pending[0].status,'延期复核到期');assert.equal(pending[0].overdue,true);
}
assert.equal(operationalTasks([{...devices[0],risk_score:.01}],[],[{...alert,dataset_version:'old',defer_until:'2026-10-20T09:00:00Z'}],'v1',now).length,0);
const newer=[{...devices[0],prediction_at:'2026-10-20T09:30:00Z',risk_score:.01}];
const oldDue={...alert,defer_until:'2026-10-20T09:00:00Z'};
assert.equal(operationalTasks(newer,[],[oldDue],'v1',now)[0].alertId,'A1');
assert.equal(operationalTasks(newer,[],[{...oldDue,status:'已确认'}],'v1',now).length,0);
assert.equal(operationalTasks(newer,[],[{...oldDue,dataset_version:'old'}],'v1',now).length,0);
console.log('12 operational task checks passed (no browser/network).');

assert.equal(personalTasks(devices,orders,[],"v1",now,{role:"viewer"}).length,0);
assert.deepEqual(personalTasks(devices,orders,[],"v1",now,{role:"user",staff_id:"T1"}).map(t=>t.id),["W1"]);
assert.equal(personalTasks(devices,orders,[],"v1",now,{role:"user"}).length,0);
for(const role of ["developer","admin"]){
 const mine=personalTasks(devices,orders,[],"v1",now,{role});
 assert.equal(mine.some(t=>t.id==="W2"),true);
 assert.equal(mine.some(t=>["W1","W3"].includes(t.id)),false);
 assert.equal(mine.some(t=>t.category==="预警复核"),true);
}
assert.equal(personalTasks(devices,orders,[],"v1",now,{role:"unknown"}).length,0);
console.log("10 personal queue role checks passed.");

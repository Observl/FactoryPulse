// Execute the production route with an in-memory snapshot; no database writes.
import {readFileSync} from 'node:fs';
import {performance} from 'node:perf_hooks';
import {scheduleComparisonRoute} from '../cloudflare/identity/work-orders.mjs';
const f=JSON.parse(readFileSync(0,'utf8'));
Date.now=()=>Date.parse(f.now+'+08:00');
const s={payload:{start_at:f.start_at,scenario_id:'bench',request_id:'comparison'},user:{role:'admin',user_id:'bench'},version:'bench',scope:'bench',businessRevision:'0',
 data:{equipment:f.tasks.map(t=>({equipment_id:t.equipment_id})),maintenance_rules:f.tasks.map(t=>({...t,maintenance_hours:t.hours,maintenance_cost_cny:t.cost,required_staff_count:t.people})),staff:f.staff,orders:f.orders,scenarios:[{scenario_id:'bench',maintenance_budget_cny:f.budget,max_downtime_h:f.max_hours,available_staff_count:f.staff_limit}]},
 orders:f.tasks.map((t,i)=>({work_order_id:t.equipment_id,equipment_id:t.equipment_id,status:'草稿·待排程',dataset_version:'bench',priority:t.priority,created_at:String(i).padStart(4,'0')})),
 available:name=>({source:'manual_count',available_to_allocate:f.stock[name]??0}),receipt:async()=>null,save(){},recordReceipt(){},async commit(){}};
const begin=performance.now();
const result=await scheduleComparisonRoute({method:'POST'},s,new URL('https://benchmark.invalid/api/schedule/generate'));
console.log(JSON.stringify({...result,algorithm_ms:performance.now()-begin}));

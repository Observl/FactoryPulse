/** Versioned JSON artifacts. This private binding is never exposed as a public route. */
import {sqlRead} from './sql-analysis.mjs';
import {business} from './business.mjs';
import {workOrders} from './work-orders.mjs';
import {revisions} from './data-sync.mjs';
const same=(vector,current)=>Object.entries(vector).every(([key,value])=>(current[key]||0)===value);
const tables={equipment:'equipment',readings:'sensor_readings',maintenance_rules:'maintenance_requirements',maintenance_history:'maintenance_history',staff:'maintenance_staff',orders:'production_orders',scenarios:'maintenance_scenarios'};
export class BusinessResults{
 constructor(ctx,env){this.ctx=ctx;this.env=env;this.pending=new Map()}
 async fetch(request){
  const payload=await request.json();
  if(payload.operation==='statistics')return this.statistics();
  const key=JSON.stringify(payload.vector);
  if(!this.pending.has(key)){const pending=this.result(payload).finally(()=>this.pending.delete(key));this.pending.set(key,pending)}
  const value=await this.pending.get(key);return new Response(value.content,{status:value.status,headers:value.headers});
 }
 async result({url,user,vector}){
  const previous=await this.ctx.storage.get('head');
  if(previous&&JSON.stringify(previous.vector)===JSON.stringify(vector)){
   const names=Array.from({length:previous.chunks},(_,i)=>'chunk:'+i),chunks=await this.ctx.storage.get(names);
   if(names.every(name=>chunks.has(name)))return {status:200,content:names.map(name=>chunks.get(name)).join(''),headers:{'Content-Type':'application/json','X-FP-Result-Cache':'hit'}};
  }
  const request=new Request(url),response=await sqlRead(request,this.env,user)||await workOrders(request,this.env,user)||await business(request,this.env,user);
  const content=await response.text(),headers=Object.fromEntries(response.headers);
  if(response.status!==200)return {status:response.status,content,headers};
  const current=await revisions(this.env);
  if(same(vector,current)){
   // Split by Unicode code points so each stored value is at most 64 KiB.
   const characters=Array.from(content),chunks=[];for(let i=0;i<characters.length;i+=16000)chunks.push(characters.slice(i,i+16000).join(''));
   await this.ctx.storage.transaction(async tx=>{
    for(let i=0;i<chunks.length;i++)await tx.put('chunk:'+i,chunks[i]);
    for(let i=chunks.length;i<(previous?.chunks||0);i++)await tx.delete('chunk:'+i);
    await tx.put('head',{vector,chunks:chunks.length});
   });
  }
  return {status:200,content,headers:{...headers,'X-FP-Result-Cache':'miss'}};
 }
 async statistics(){
  // Serialize refreshes to avoid recounting the same changed input for concurrent views.
  if(!this.statsPending)this.statsPending=this.computeStatistics().finally(()=>{this.statsPending=null});
  return Response.json(await this.statsPending);
 }
 async computeStatistics(){
  const env=this.env,db=env.BUSINESS_DB,vector=await revisions(env),saved=await this.ctx.storage.get('statistics')||{},counts={},stamps={},queries=[],names=[];
  for(const [name,table] of Object.entries(tables)){
   const stamp=JSON.stringify([vector.__source__,vector['records/'+name]||0]);stamps[name]=stamp;
   if(saved.stamps?.[name]===stamp)counts[name]=saved.counts[name];
   else{names.push(name);queries.push(db.prepare('SELECT COUNT(*) AS n FROM '+table))}
  }
  const riskStamp=JSON.stringify([vector.__source__,vector['records/equipment']||0,vector['records/readings']||0,vector['records/demo_risks']||0]);stamps.demo_risks=riskStamp;
  if(saved.stamps?.demo_risks===riskStamp)counts.demo_risks=saved.counts.demo_risks;
  else{names.push('demo_risks');queries.push(db.prepare('SELECT COUNT(*) AS n FROM equipment e LEFT JOIN v_equipment_rule_risk r USING(equipment_id) LEFT JOIN external_risk_inputs x USING(equipment_id) WHERE COALESCE(x.risk_score,r.rule_risk) IS NOT NULL'))}
  const results=queries.length?await db.batch(queries):[];names.forEach((name,i)=>counts[name]=results[i].results[0].n);
  const settings=Object.fromEntries((await db.prepare("SELECT key,value FROM business_settings WHERE key IN ('last_sync_at','source_name','source_date')").all()).results.map(x=>[x.key,x.value]));
  const source={dataset_version:settings.last_sync_at,source_name:settings.source_name,source_date:settings.source_date,record_count:counts.readings,device_count:counts.equipment};
  const after=await revisions(env);if(same(vector,after))await this.ctx.storage.put('statistics',{stamps,counts});
  return {counts,source,stable:same(vector,after)};
 }
}

// Native Workers work-order lifecycle. D1 row writes share Python's revision guard.
const ACTIVE=new Set(['待审批','已批准','已接单','执行中','已暂停','待验收']);
const FORMAL=new Set(['已批准','已接单','执行中','已暂停','待验收']);
const FINAL=new Set(['已完成','已取消']);
class Problem extends Error{constructor(status,message){super(message);this.status=status}}
const fail=(status,message)=>{throw new Problem(status,message)};
const encode=JSON.stringify,now=()=>new Date().toISOString();
const stable=x=>encode(x,(_k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const hash=async x=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stable(x)))),v=>v.toString(16).padStart(2,'0')).join('');
const uid=prefix=>prefix+crypto.randomUUID().replaceAll('-','').slice(0,12).toUpperCase();
const number=(x,min=0,max=Infinity)=>{if(typeof x!=='number'||!Number.isFinite(x)||x<min||x>max)fail(422,'数值超出允许范围');return x};
const text=(x,min=1,max=1000)=>{if(typeof x!=='string'||x.trim().length<min||x.length>max)fail(422,'请填写有效内容');return x.trim()};
const date=x=>{if(typeof x!=='string'||!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(x))fail(422,'请填写完整日期与时间');const v=Date.parse(/[Zz]|[+-]\d{2}:\d{2}$/.test(x)?x:x.replace(' ','T')+'+08:00');if(!Number.isFinite(v))fail(422,'日期时间无效');return v};
const stamp=x=>new Date(x+8*3600000).toISOString().slice(0,19).replace('T',' ');
const team=o=>(o.staff_ids||[o.staff_id]).filter(x=>x!==undefined&&x!==null).map(String);
const overlap=(a,b,c,d)=>a<d&&b>c;
const skills=x=>new Set(String(x||'').split(/[,，;；、\s]+/).filter(Boolean));
const quantities=parts=>{const out={};for(const p of parts||[]){text(p.part_name,1,100);number(p.quantity);if(!Number.isInteger(p.quantity)||Object.hasOwn(out,p.part_name))fail(422,'备件数量必须是整数且名称不得重复');out[p.part_name]=p.quantity}return out};
const admin=u=>{if(!['developer','admin'].includes(u.role))fail(403,'此操作需要管理员权限')};
const actor=u=>({actor_user_id:String(u.user_id),actor_role:u.role});

class State{
 constructor(db,user){this.db=db;this.user=user;this.writes=[];this.changed=new Set()}
 async load(request,url,normalized=false){
  const settingsQuery=this.db.prepare(`SELECT key,value FROM ${normalized?'business_settings':'settings'} WHERE key IN ('last_sync_at','inventory_scope','business_revision','source_name','data_origin')`);
  let initial;
  if(request.method==='GET')initial=await settingsQuery.all();
  else{const baseline=await this.db.batch([settingsQuery,this.db.prepare('SELECT revision FROM fp_business_revision WHERE id=1')]);initial=baseline[0];this.revision=baseline[1].results[0].revision}
  this.settings=Object.fromEntries(initial.results.map(x=>[x.key,x.value]));
  this.version=this.settings.last_sync_at;this.scope=this.settings.inventory_scope||this.version;this.businessRevision=this.settings.business_revision||'0';
  if(!this.version)fail(503,'请先配置业务数据');
  const path=url.pathname,get=request.method==='GET',flow=/^\/api\/work-orders\/([^/]+)\/flow$/.exec(path),op=/^\/api\/equipment\/([^/]+)\/operations$/.exec(path),resource=/^\/api\/resources\/(staff|orders|scenarios|requirements)$/.exec(path);
  let tables=['equipment','maintenance_rules','staff','orders','scenarios'],orders=true,stock=true,reservations=true,datasets=true,alerts=true;
  if(get){
   tables=[];orders=false;stock=false;reservations=false;datasets=false;alerts=false;
   if(path==='/api/work-orders'||flow)orders=true;
   if(resource)tables=[resource[1]==='requirements'?'maintenance_rules':resource[1]];
   if(path==='/api/resources/inventory'){stock=true;reservations=true}
   if(path==='/api/maintenance/time-readiness')tables=['maintenance_rules','staff'];
   if(path==='/api/maintenance/timeline'){tables=['equipment','staff','orders','scenarios'];orders=true;datasets=true}
   if(op){tables=['orders'];orders=true}
   if(path==='/api/operations/resource-occupancy'){tables=['staff','orders'];orders=true}
  }else{
   const raw=await request.clone().text();if(raw.length>65536)fail(413,'表单过长');try{this.payload=JSON.parse(raw)}catch{fail(422,'表单格式无效')}if(!this.payload||typeof this.payload!=='object'||Array.isArray(this.payload))fail(422,'表单格式无效');
   datasets=false;alerts=path.startsWith('/api/alerts/');
   const mutation=/^\/api\/resources\/(staff|orders|scenarios|requirements|inventory)\//.exec(path);
   if(mutation){const kind=mutation[1];tables=kind==='inventory'?[]:[kind==='requirements'?'maintenance_rules':kind];if(['orders','requirements'].includes(kind))tables.push('equipment');orders=false;stock=['inventory','requirements'].includes(kind);reservations=false}
   if(alerts){tables=[];stock=false;reservations=false;this.orderEquipment=decodeURIComponent(path.split('/')[3])}
   if(path==='/api/maintenance-requests'){tables=['equipment'];stock=false;reservations=false;this.orderEquipment=this.payload.equipment_id}
   const work=/^\/api\/work-orders\/([^/]+)\/(approval|transition|manage)$/.exec(path);
   if(work){tables=[];this.targetOrder=decodeURIComponent(work[1]);this.workOperation=work[2];if(work[2]==='manage'||(work[2]==='transition'&&!['accept','start','verify','cancel'].includes(this.payload.action))){stock=false;reservations=false}}
  }
  const queries=[],labels=[];
  const add=(name,sql,params=[])=>{labels.push(name);queries.push(this.db.prepare(sql).bind(...params))};
  if(tables.length){let sql='SELECT * FROM records WHERE table_name IN ('+tables.map(()=>'?').join(',')+')',params=[...tables];if(op){sql+=" AND json_extract(content,'$.equipment_id')=?";params.push(decodeURIComponent(op[1]))}add('raw',sql,params)}
  if(orders){
   const filters=[],params=[];
   if(flow){filters.push('work_order_id=?');params.push(decodeURIComponent(flow[1]))}
   if(this.orderEquipment){filters.push('equipment_id=?');params.push(this.orderEquipment)}
   if(this.targetOrder){
    if(this.workOperation==='manage'){filters.push('equipment_id=(SELECT equipment_id FROM work_orders WHERE work_order_id=?)');params.push(this.targetOrder)}
    else if(this.workOperation==='approval'||['accept','start'].includes(this.payload.action)){filters.push("(work_order_id=? OR status IN ('已批准','已接单','执行中','已暂停','待验收'))");params.push(this.targetOrder)}
    else{filters.push('work_order_id=?');params.push(this.targetOrder)}
   }
   if(!get&&path==='/api/schedule/generate'){filters.push("json_extract(content,'$.deleted_at') IS NULL AND (status IN ('待审批','已批准','已接单','执行中','已暂停','待验收') OR (status='草稿·待排程' AND json_extract(content,'$.dataset_version')=?))");params.push(this.version)}
   if(op){filters.push('equipment_id=?');params.push(decodeURIComponent(op[1]))}
   if(get&&path==='/api/work-orders'){
    if(url.searchParams.get('include_deleted')!=='true')filters.push("json_extract(content,'$.deleted_at') IS NULL");
    for(const [parameter,column] of [['dataset_version',"json_extract(content,'$.dataset_version')"],['equipment_id','equipment_id'],['status','status']])if(url.searchParams.has(parameter)){filters.push(column+'=?');params.push(url.searchParams.get(parameter))}
    const before=url.searchParams.get('before_updated_at'),beforeId=url.searchParams.get('before_id');
    if(Boolean(before)!==Boolean(beforeId))fail(422,'翻页需要同时提供更新时间与工单编号');
    if(before){filters.push('(updated_at<? OR (updated_at=? AND work_order_id<?))');params.push(before,before,beforeId)}
   }
   let sql='SELECT * FROM work_orders'+(filters.length?' WHERE '+filters.join(' AND '):'')+' ORDER BY updated_at DESC,work_order_id DESC';
   if(get&&path==='/api/work-orders'&&url.searchParams.has('limit')){const limit=Number(url.searchParams.get('limit'));if(!Number.isInteger(limit)||limit<1||limit>1000)fail(422,'limit须在1到1000之间');sql+=' LIMIT ?';params.push(limit+1);this.pageLimit=limit}
   add('orders',sql,params);
  }
  if(stock)add('stock','SELECT * FROM inventory_stock'+(get?' WHERE scope=?':''),get?[this.scope]:[]);
  if(reservations)add('reservations',"SELECT * FROM inventory_reservations"+(get?" WHERE scope=? AND state='reserved'":""),get?[this.scope]:[]);
  if(datasets)add('datasets','SELECT * FROM dataset_versions');
  if(alerts)add('alerts','SELECT * FROM alerts WHERE dataset_version=? AND equipment_id=?',[this.version,this.orderEquipment]);
  const values=queries.length?await this.db.batch(queries):[],loaded=Object.fromEntries(labels.map((name,i)=>[name,values[i].results]));
  this.data={};this.raw=loaded.raw||[];
  for(const x of this.raw)(this.data[x.table_name]??=[]).push({...JSON.parse(x.content),_index:x.row_index});
  this.orders=(loaded.orders||[]).map(x=>({...JSON.parse(x.content),work_order_id:x.work_order_id,equipment_id:x.equipment_id,status:x.status,updated_at:x.updated_at}));
  this.stock=loaded.stock||[];this.reservations=loaded.reservations||[];this.datasets=loaded.datasets||[];this.alerts=loaded.alerts||[];
  return this;
 }
 write(sql,...params){this.writes.push(this.db.prepare(sql).bind(...params))}
 get(id){const o=this.orders.find(x=>x.work_order_id===id);if(!o)fail(404,'工单不存在');return o}
 check(o,version){if(!Number.isInteger(version)||version<1)fail(422,'请提供工单版本');if((o.version||1)!==version)fail(409,'工单已变化，请刷新');if(o.deleted_at)fail(409,'工单已在回收站，请先恢复')}
 audit(type,id,body){this.write('INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES(?,?,?,?)',type,id,encode({...body,...actor(this.user)}),now())}
 save(o,action,note,previous){o.version=(o.version||1)+1;o.updated_at=now();(o.execution_history??=[]).push({from:previous,to:o.status,action,actor:this.user.display_name,note:note||'',at:o.updated_at,...actor(this.user)});const content={...o};delete content.status;delete content.updated_at;this.write('INSERT OR REPLACE INTO work_orders(work_order_id,equipment_id,content,status,updated_at) VALUES(?,?,?,?,?)',o.work_order_id,o.equipment_id,encode(content),o.status,o.updated_at);this.audit('work_order_'+action,o.work_order_id,{from:previous,to:o.status,note});this.changed.add(o.work_order_id)}
 async receipt(id,signature){text(id,8,100);const r=await this.db.prepare('SELECT request_content,response FROM operation_requests WHERE request_id=?').bind(id).first();if(!r)return null;if(r.request_content!==signature)fail(409,'请求编号已用于不同操作或其他账号');return JSON.parse(r.response)}
 recordReceipt(id,signature,response){this.write('INSERT INTO operation_requests VALUES(?,?,?)',id,signature,encode(response))}
 async commit(){if(!this.writes.length)return;const nonce=crypto.randomUUID();try{await this.db.batch([this.db.prepare('UPDATE fp_business_revision SET revision=revision+1,commit_nonce=? WHERE id=1 AND revision=?').bind(nonce,this.revision),this.db.prepare('INSERT INTO fp_business_guard(id) SELECT 0 WHERE NOT EXISTS(SELECT 1 FROM fp_business_revision WHERE id=1 AND commit_nonce=?)').bind(nonce),...this.writes])}catch(e){const latest=await this.db.prepare('SELECT revision,commit_nonce FROM fp_business_revision WHERE id=1').first();if(latest.commit_nonce===nonce)return;if(latest.revision!==this.revision)fail(409,'资源或工单已变化，请刷新后重试');throw e}}
 available(name,scope=this.scope,except=''){const stock=this.stock.find(x=>x.scope===scope&&x.part_name===name);const held=this.reservations.filter(x=>x.scope===scope&&x.part_name===name&&x.state==='reserved'&&x.work_order_id!==except).reduce((n,x)=>n+x.quantity,0);return {...stock,reserved_quantity:held,available_to_allocate:Math.max(0,(stock?.on_hand||0)-held)}}
 release(id){this.write("UPDATE inventory_reservations SET state='released' WHERE work_order_id=? AND state='reserved'",id);for(const p of this.reservations)if(p.work_order_id===id&&p.state==='reserved')p.state='released'}
 reserve(o){const scope=o.inventory_scope||o.dataset_version;for(const [name,q] of Object.entries(quantities(o.spare_parts))){const stock=this.available(name,scope,o.work_order_id);if(!stock.source||stock.source==='legacy_unverified'||stock.available_to_allocate<q)fail(409,'备件库存尚未核对或不足：'+name);this.write("INSERT OR REPLACE INTO inventory_reservations VALUES(?,?,?,?,?)",o.work_order_id,scope,name,q,'reserved');const row={work_order_id:o.work_order_id,scope,part_name:name,quantity:q,state:'reserved'};this.reservations=this.reservations.filter(x=>!(x.work_order_id===o.work_order_id&&x.part_name===name));this.reservations.push(row)}}
 consume(o,parts){const plan=quantities(o.spare_parts),actual=quantities(parts);if(stable(Object.keys(plan).sort())!==stable(Object.keys(actual).sort()))fail(422,'请逐项确认实际备件耗用，未使用填写0');const scope=o.inventory_scope||o.dataset_version;for(const [name,q] of Object.entries(actual)){const s=this.available(name,scope,o.work_order_id);if(!s.source||s.source==='legacy_unverified'||q>s.available_to_allocate)fail(409,'实际库存不足或未核对');this.write('UPDATE inventory_stock SET on_hand=on_hand-?,version=version+1,counted_at=? WHERE scope=? AND part_name=?',q,now(),scope,name);this.write('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?)',crypto.randomUUID(),scope,name,o.work_order_id,'consume',-q,'工单验收实际耗用',now());s.on_hand-=q;const row=this.stock.find(x=>x.scope===scope&&x.part_name===name);row.on_hand-=q}this.write("UPDATE inventory_reservations SET state='consumed' WHERE work_order_id=? AND state='reserved'",o.work_order_id);for(const row of this.reservations)if(row.work_order_id===o.work_order_id&&row.state==='reserved')row.state='consumed';o.actual_parts=parts}
 conflicts(o,formalOnly=true){const a=date(o.start_at),b=date(o.end_at),t=team(o);if(b<=a||!t.length||new Set(t).size!==t.length)fail(409,'排程时间或人员无效');for(const x of this.orders){if(x.work_order_id===o.work_order_id||x.deleted_at||!(formalOnly?FORMAL:ACTIVE).has(x.status))continue;const shared=x.equipment_id===o.equipment_id||team(x).some(p=>t.includes(p));if(!shared)continue;if(!x.start_at||!x.end_at||overlap(a,b,date(x.start_at),date(x.end_at)))fail(409,'与工单 '+x.work_order_id+' 的设备或人员占用冲突')}}
 async fingerprint(){return hash({revision:this.revision,version:this.version,businessRevision:this.businessRevision})}
}

function candidate(s,id){
 const e=(s.data.equipment||[]).find(x=>x.equipment_id===id),r=(s.data.maintenance_rules||[]).find(x=>x.equipment_id===id);if(!e||!r||r.configuration_status==='required')fail(422,'请先配置设备检修条件：'+id);
 const hours=number(r.maintenance_hours,Number.MIN_VALUE,10000),cost=number(r.maintenance_cost_cny),people=r.required_staff_count??1;number(people,1,100);if(!Number.isInteger(people))fail(422,'维修人数必须是整数');text(r.required_skill);if(date(r.window_end)<=date(r.window_start))fail(422,'设备停机窗口无效');quantities(r.spare_parts);
 return {equipment_id:id,equipment_name:e.equipment_name,hours,cost,people,required_skill:r.required_skill,window_start:r.window_start,window_end:r.window_end,spare_parts:structuredClone(r.spare_parts||[]),risk:0,priority_score:.6,priority_basis:'人工确认的维护需求',risk_available:false};
}
function scenario(s,id){const x=(s.data.scenarios||[]).find(x=>x.scenario_id===id)||(!id?s.data.scenarios?.[0]:null);if(!x)fail(422,'排程情景不存在');return {id:x.scenario_id,budget:number(x.maintenance_budget_cny),max_downtime_h:number(x.max_downtime_h,Number.MIN_VALUE),staff_count:number(x.available_staff_count,1,1000),risk_threshold:x.risk_threshold??.35}}
function combinations(values,n){const result=[];function walk(start,p){if(p.length===n){result.push(p);if(result.length>10000)fail(422,'人员组合过多，请缩小本轮人员或任务范围');return}for(let i=start;i<=values.length-(n-p.length);i++)walk(i+1,[...p,values[i]])}walk(0,[]);return result}
// Explicit feasible plan, never advertised as CP-SAT or a proof of global optimality.
// Every start boundary is checked; earliest feasible finish wins for each team.
function place(s,c,limits,bookings,startAt,explicitTeam){
 const duration=Math.ceil(c.hours*60)*60000,required=skills(c.required_skill);
 const people=(s.data.staff||[]).filter(p=>(!explicitTeam||explicitTeam.includes(String(p.staff_id)))&&[...required].every(k=>skills(p.skills).has(k))&&Number(p.available_hours)*3600000>=duration);
 if(people.length<c.people)fail(422,'具备所需技能及工时的人员不足');
 let best=null;
 for(const members of combinations(people,c.people)){
  const ids=members.map(p=>String(p.staff_id));if(explicitTeam&&(ids.length!==explicitTeam.length||!ids.every(id=>explicitTeam.includes(id))))continue;
  let lower=Math.ceil(Math.max(Date.now(),date(c.window_start),startAt?date(startAt):0,...members.map(p=>date(p.shift_start)))/60000)*60000;
  const upper=Math.floor(Math.min(date(c.window_end),...members.map(p=>date(p.shift_end)))/60000)*60000;
  const intervals=[];
  for(const p of s.data.orders||[])if(p.equipment_id===c.equipment_id){const a=date(p.start_at),b=date(p.end_at);if(b<=a)fail(422,'生产订单时间无效');intervals.push([a,b])}
  for(const b of bookings){if(!b.start_at||!b.end_at)fail(422,'已有工单缺少占用时间，请先核对');if(b.equipment_id===c.equipment_id||team(b).some(id=>ids.includes(id)))intervals.push([date(b.start_at),date(b.end_at)])}
  if(members.some(p=>bookings.filter(b=>team(b).includes(String(p.staff_id))).reduce((sum,b)=>sum+(date(b.end_at)-date(b.start_at)),0)+duration>Number(p.available_hours)*3600000))continue;
  const points=new Set([lower,...intervals.map(x=>Math.ceil(x[1]/60000)*60000),...bookings.map(b=>Math.ceil(date(b.end_at)/60000)*60000)]);
  for(const a of [...points].filter(x=>x>=lower).sort((x,y)=>x-y)){
   const end=a+duration;if(end>upper||intervals.some(([x,y])=>overlap(a,end,x,y)))continue;
   const events=[[a,ids.length],[end,-ids.length]];for(const b of bookings)if(overlap(a,end,date(b.start_at),date(b.end_at))){events.push([Math.max(a,date(b.start_at)),team(b).length],[Math.min(end,date(b.end_at)),-team(b).length])}events.sort((x,y)=>x[0]-y[0]||x[1]-y[1]);let count=0;if(events.some(x=>(count+=x[1])>limits.staff_count))continue;
   if(!best||a<best.start)best={start:a,end,members,ids};break;
  }
 }
 if(!best)fail(422,'人员班次、生产订单或设备窗口内没有可用安排');
 return {...c,start_at:stamp(best.start),end_at:stamp(best.end),hours:duration/3600000,staff_ids:best.ids,staff_id:best.ids[0],staff_name:best.members.map(p=>p.staff_name).join('、'),status:'待审批',optimizer_status:'feasible',scheduler_method:'workers_earliest_feasible',order_impact:'避开已录入生产占用',assumptions:[]};
}

async function route(request,s,url){
 const path=url.pathname,method=request.method;
 if(method==='GET'){
  if(path==='/api/work-orders'){
   const records=s.pageLimit?s.orders.slice(0,s.pageLimit):s.orders,last=records.at(-1);return {records,next_cursor:s.pageLimit&&s.orders.length>s.pageLimit?{updated_at:last.updated_at,work_order_id:last.work_order_id}:null};
  }
  const flow=/^\/api\/work-orders\/([^/]+)\/flow$/.exec(path);
  if(flow){const o=s.get(decodeURIComponent(flow[1]));const events=await s.db.prepare('SELECT * FROM audit_events WHERE entity_id=? OR entity_id=? ORDER BY event_id').bind(o.work_order_id,o.source_alert_id||o.work_order_id).all();return {record:o,owner:['已批准','已接单','执行中','已暂停'].includes(o.status)?o.staff_name:'设备总管',next_step:o.deleted_at?'已移入回收站，可恢复':'按工单当前状态处理，操作留存审计',events:events.results.map(x=>({...x,content:JSON.parse(x.content)}))}}
  if(path==='/api/maintenance/timeline'){
   const scope=url.searchParams.get('dataset_version')||s.version,metadata=new Map(s.datasets.map(x=>[x.version,JSON.parse(x.metadata)]));metadata.set(s.version,{source_name:s.settings.source_name,data_origin:s.settings.data_origin});const versions=new Set([...metadata.keys(),...s.orders.map(x=>x.dataset_version)]);
   let data=s.data;if(scope!==s.version){data={};for(const x of (await s.db.prepare("SELECT table_name,content FROM archived_records WHERE version=? AND table_name IN ('equipment','staff','orders','scenarios') ORDER BY row_index").bind(scope).all()).results)(data[x.table_name]??=[]).push(JSON.parse(x.content))}
   return {dataset_version:scope,current:scope===s.version,datasets:[...versions].filter(Boolean).sort().reverse().map(v=>({version:v,name:metadata.get(v)?.source_name||'历史数据源',origin:metadata.get(v)?.data_origin||'',current:v===s.version,count:s.orders.filter(x=>x.dataset_version===v&&!x.deleted_at).length})),equipment:data.equipment||[],staff:data.staff||[],orders:data.orders||[],scenarios:data.scenarios||[],work_orders:s.orders.filter(x=>x.dataset_version===scope&&(url.searchParams.get('include_deleted')==='true'||!x.deleted_at))};
  }
  if(path==='/api/maintenance/time-readiness'){const groups=[['requirements',s.data.maintenance_rules||[],'equipment_id','window_start','window_end','设备停机窗口'],['staff',s.data.staff||[],'staff_id','shift_start','shift_end','人员班次']].map(([kind,rows,key,a,b,title])=>({kind,title,records:rows.length,issues:rows.flatMap(r=>{try{const start=date(r[a]),end=date(r[b]);return end<=start||end<=Date.now()?[{id:r[key],reason:'时间无效或已过期'}]:[]}catch{return [{id:r[key],reason:'时间缺失或无法识别'}]}})}));return {checked_at:now(),groups,issue_count:groups.reduce((n,g)=>n+g.issues.length,0),scope:'仅检查时间条件，不代表联合排程通过'}}
  if(path==='/api/resources/inventory')return {records:s.stock.filter(x=>x.scope===s.scope).map(x=>({...x,...s.available(x.part_name),shortfall:Math.max(0,s.available(x.part_name).reserved_quantity-x.on_hand)})),meaning:'实盘库存扣除未完成工单预留'};
  const resource=/^\/api\/resources\/(staff|orders|scenarios|requirements)$/.exec(path);if(resource)return {records:s.data[resource[1]==='requirements'?'maintenance_rules':resource[1]]||[]};
  const op=/^\/api\/equipment\/([^/]+)\/operations$/.exec(path);if(op)return {equipment_id:decodeURIComponent(op[1]),dataset_version:s.version,orders:(s.data.orders||[]).filter(x=>x.equipment_id===decodeURIComponent(op[1])),work_orders:s.orders.filter(x=>x.equipment_id===decodeURIComponent(op[1])).map(x=>({...x,current_dataset:x.dataset_version===s.version}))};
  if(path==='/api/operations/resource-occupancy'){const active=s.orders.filter(x=>!x.deleted_at&&ACTIVE.has(x.status));return {dataset_version:s.version,staff:(s.data.staff||[]).map(p=>({...p,bookings:active.filter(x=>team(x).includes(String(p.staff_id)))})),orders:(s.data.orders||[]).map(o=>({...o,related_work_orders:active.filter(x=>x.equipment_id===o.equipment_id)})),note:'待审批为计划占用'}}
  return null;
 }
 if(method!=='POST')return null;
 const p=s.payload;
 const transition=/^\/api\/work-orders\/([^/]+)\/transition$/.test(path);
 if(transition){if(!['developer','admin','user'].includes(s.user.role))fail(403,'只读账号不能处理工单')}else admin(s.user);
 const signature=stable({path,p:{...p,request_id:undefined},...actor(s.user)}),requestId=p.request_id||'auto-'+await hash(path==='/api/schedule/generate'?{signature,version:s.version,drafts:s.orders.filter(x=>!x.deleted_at&&x.status==='草稿·待排程').map(x=>[x.work_order_id,x.version]),business:s.businessRevision}:signature);
 const prior=await s.receipt(requestId,signature);if(prior)return prior;
 let result;
 const alert=/^\/api\/alerts\/([^/]+)\/action$/.exec(path);
 if(alert){
  const id=decodeURIComponent(alert[1]),mapping={confirm:'已确认',reject:'已驳回',defer:'已延期',work_order:'已转工单',undo:'待确认'};if(!mapping[p.action])fail(422,'未知预警操作');if(['reject','undo'].includes(p.action))text(p.note);
  if(p.expected_dataset_version!==s.version)fail(409,'数据版本已变化，请重新核对预警');
  const v=await s.db.prepare("SELECT content FROM fp_computed_views WHERE dataset_id=? AND view_key='overview'").bind(s.version).first();const device=v&&JSON.parse(v.content).devices.find(x=>x.equipment_id===id);if(!device)fail(404,'当前设备评分证据不存在');
  let prediction=device.prediction_at||'';let old=s.alerts.find(x=>x.equipment_id===id&&x.dataset_version===s.version&&x.prediction_at===prediction);
  if(p.alert_id&&p.alert_id!==old?.alert_id){const historical=s.alerts.find(x=>x.alert_id===p.alert_id&&x.equipment_id===id&&x.dataset_version===s.version);if(historical){if(p.action==='work_order')fail(409,'历史预警不能直接创建当前工单');text(p.note);old=historical;prediction=old.prediction_at}else if(p.alert_id!==device.alert_id)fail(409,'预警对象已变化')}
  if(p.prediction_at!==prediction||p.version!==(old?.version||0))fail(409,'预警记录已变化，请刷新');
  const namespace=Uint8Array.from('6ba7b8119dad11d180b400c04fd430c8'.match(/../g),x=>parseInt(x,16)),name=new TextEncoder().encode(s.version+'/'+id+'/'+prediction),bytes=new Uint8Array(namespace.length+name.length);bytes.set(namespace);bytes.set(name,16);const digest=new Uint8Array(await crypto.subtle.digest('SHA-1',bytes));digest[6]=(digest[6]&15)|80;digest[8]=(digest[8]&63)|128;const alertId=old?.alert_id||'ALERT-'+Array.from(digest.slice(0,16),x=>x.toString(16).padStart(2,'0')).join('').slice(0,20);
  if(p.defer_until&&(date(p.defer_until)<=Date.now()))fail(422,'延期时间必须在未来');if(p.action==='defer'&&!p.defer_until)fail(422,'请填写延期时间');
  const linked=s.orders.filter(x=>x.source_alert_id===alertId);if(p.action==='undo'&&(!old||linked.some(x=>x.status==='已完成'||x.actual_start_at||(!x.deleted_at&&x.status!=='已取消'))))fail(409,'预警已关联维修事实或未完成工单，不能撤回');
  let work=null;
  if(p.action==='work_order'){
   work=linked.find(x=>!x.deleted_at&&!FINAL.has(x.status));if(!work){const existing=s.orders.find(x=>x.equipment_id===id&&x.dataset_version===s.version&&!x.deleted_at&&!FINAL.has(x.status));if(existing&&(existing.status!=='草稿·待排程'||existing.source_alert_id))fail(409,'设备已有未完成工单');work=existing||{work_order_id:uid('WO-DRAFT-'),equipment_id:id,equipment_name:device.equipment_name,maintenance_action:p.note||device.recommended_action,priority:'中',dataset_version:s.version,created_at:now(),version:0,status:'草稿·待排程'};work.source_alert_id=alertId;if(!existing)s.orders.push(work);s.save(work,existing?'link_alert':'alert_request',p.note||'',existing?.status||'')}
  }
  s.write('INSERT OR REPLACE INTO alerts(alert_id,equipment_id,status,note,updated_at,dataset_version,prediction_at,defer_until,version) VALUES(?,?,?,?,?,?,?,?,?)',alertId,id,mapping[p.action],p.note||'',now(),s.version,prediction,p.defer_until||null,(old?.version||0)+1);
  result={success:true,alert_id:alertId,equipment_id:id,status:mapping[p.action],version:(old?.version||0)+1,work_order_id:work?.work_order_id||null,note:p.note||'',updated_at:now(),next_step:work?'维护中心':'处理记录'};s.audit('alert_action',alertId,{equipment_id:id,...p,...result});
 }else if(path==='/api/maintenance-requests'){
  const e=(s.data.equipment||[]).find(x=>x.equipment_id===p.equipment_id);if(!e)fail(404,'设备不存在');text(p.action,2);if(!['高','中','低'].includes(p.priority||'中'))fail(422,'维护优先级无效');if(s.orders.some(x=>x.equipment_id===p.equipment_id&&x.dataset_version===s.version&&!x.deleted_at&&!FINAL.has(x.status)))fail(409,'该设备已有未完成工单');
  let evidence=null;if(Boolean(p.prediction_run_id)!==Boolean(p.evidence_reading_id))fail(422,'历史需求需同时提供运行和原始记录编号');if(p.prediction_run_id){const run=await s.db.prepare('SELECT * FROM prediction_runs WHERE run_id=?').bind(p.prediction_run_id).first();if(!run)fail(404,'预测证据不存在');if(run.dataset_version!==s.version)fail(409,'历史证据属于其他数据版本');const point=JSON.parse(run.content).replay?.find(x=>String(x.reading_id)===p.evidence_reading_id&&x.equipment_id===p.equipment_id);if(!point)fail(422,'原始记录不属于指定设备及运行');evidence={kind:'historical_replay_manual_request',run_id:p.prediction_run_id,reading_id:p.evidence_reading_id,timestamp:point.timestamp,model_version:run.model_version,dataset_version:run.dataset_version,score:point.score,alert:point.alert}}
  const o={work_order_id:uid('WO-DRAFT-'),equipment_id:p.equipment_id,equipment_name:e.equipment_name,maintenance_action:p.action,priority:p.priority||'中',dataset_version:s.version,created_at:now(),version:0,status:'草稿·待排程',source:'manual_confirmed_request'};if(evidence)o.source_evidence=evidence;s.orders.push(o);s.save(o,'manual_request',p.action,'');result={success:true,work_order_id:o.work_order_id,status:o.status,next_step:'核对检修条件、人员班次、生产占用和预算后生成安排'};
 }else if(path==='/api/schedule/generate'){
  const limits=scenario(s,p.scenario_id),active=s.orders.filter(x=>!x.deleted_at&&ACTIVE.has(x.status)),drafts=s.orders.filter(x=>!x.deleted_at&&x.dataset_version===s.version&&x.status==='草稿·待排程');
  const scheduled=[],conflicts=[];let spent=active.filter(x=>x.dataset_version===s.version).reduce((n,x)=>n+(x.cost||0),0),hours=active.filter(x=>x.dataset_version===s.version).reduce((n,x)=>n+(x.hours||0),0);const parts={};
  for(const o of drafts.sort((a,b)=>({'高':3,'中':2,'低':1}[b.priority]||0)-({'高':3,'中':2,'低':1}[a.priority]||0)||a.created_at.localeCompare(b.created_at))){try{
   const c=candidate(s,o.equipment_id);if(active.some(x=>x.equipment_id===o.equipment_id))fail(422,'已有未完成安排');if(spent+c.cost>limits.budget||hours+c.hours>limits.max_downtime_h)fail(422,'超出本轮预算或累计停机工时');
   for(const [name,q] of Object.entries(quantities(c.spare_parts))){const stock=s.available(name);const pending=active.filter(x=>!FORMAL.has(x.status)&&(x.inventory_scope||x.dataset_version)===s.scope).reduce((n,x)=>n+(quantities(x.spare_parts)[name]||0),0);if(!stock.source||stock.source==='legacy_unverified'||q+(parts[name]||0)+pending>stock.available_to_allocate)fail(422,'备件库存不足或尚未核对：'+name)}
   const item=place(s,c,limits,[...active,...scheduled],p.start_at);spent+=item.cost;hours+=item.hours;for(const [name,q] of Object.entries(quantities(c.spare_parts)))parts[name]=(parts[name]||0)+q;
   const old=o.status;Object.assign(o,item,{scenario_id:limits.id,dataset_version:s.version,inventory_scope:s.scope,business_revision:s.businessRevision,constraints_snapshot:limits});s.save(o,'schedule','Workers 校验人员、生产、库存、预算及窗口后安排',old);scheduled.push({...item,work_order_id:o.work_order_id});
  }catch(e){if(!(e instanceof Problem))throw e;conflicts.push({equipment_id:o.equipment_id,reason:e.message,suggestion:'核对资源条件后重新排程'})}}
  result={scheduled,conflicts,selection:{task_count:scheduled.length,maintenance_cost:spent,maintenance_hours:hours,method:'workers_earliest_feasible'},human_approval_required:true,optimizer_status:scheduled.length?'feasible':'no_plan',request_id:requestId};
 }else{
  const match=/^\/api\/work-orders\/([^/]+)\/(approval|transition|manage|timeline)$/.exec(path);if(!match)return await resources(s,path,p);
  const id=decodeURIComponent(match[1]),action=match[2],o=s.get(id),old=o.status;
  if(action==='manage'&&p.action==='restore'){if(o.version!==p.version)fail(409,'工单版本已变化')}else s.check(o,p.version);
  if(action==='approval'){
   if(o.status!=='待审批')fail(409,'只有待审批工单可审批');if(!['approve','reject'].includes(p.decision))fail(422,'审批操作无效');
   if(p.decision==='approve'){if(o.dataset_version!==s.version||o.business_revision!==s.businessRevision)fail(409,'数据或资源已变化，请重新排程');if(o.assumptions?.length&&!p.accept_assumptions)fail(422,'请先核对并确认情景假设');s.conflicts(o);s.reserve(o);o.approved_at=now();o.approval_business_revision=s.businessRevision;o.status='已批准'}else{text(p.note);o.status='已退回';s.release(id)}
   o.approver=s.user.display_name;o.approval_note=p.note||'';o.approval_decision_at=now();
  }else if(action==='transition'){
   const map={accept:[['已批准'],'已接单'],start:[['已接单'],'执行中'],pause:[['执行中'],'已暂停'],resume:[['已暂停'],'执行中'],finish:[['执行中'],'待验收'],verify:[['待验收'],'已完成'],rework:[['待验收'],'执行中'],revise:[['已退回','已驳回'],'草稿·待排程'],cancel:[['草稿·待排程','待审批','已批准','已接单','已暂停','已退回','已驳回'],'已取消']};
   if(!map[p.action])fail(422,'未知工单操作');if(s.user.role==='user'&&(!['accept','start','pause','resume','finish'].includes(p.action)||!team(o).includes(String(s.user.staff_id))))fail(403,'只能处理分配给自己的维修任务');
   if(!map[p.action][0].includes(old))fail(409,'当前工单状态不允许该操作');if(['pause','finish','verify','rework','revise','cancel'].includes(p.action))text(p.note);
   if(['accept','start'].includes(p.action)){if(o.dataset_version!==s.version||o.approval_business_revision!==s.businessRevision)fail(409,'审批后资源或数据变化，请撤回重新排程审批');s.conflicts(o);s.reserve(o);o.execution_check={checked_at:now(),action:p.action,dataset_version:s.version,business_revision:s.businessRevision,checks:['数据版本','审批资源版本','正式设备及人员占用','备件库存']}}
   if(p.action==='start')o.actual_start_at=now();
   if(p.action==='finish'){number(p.actual_hours);number(p.actual_cost_cny);Object.assign(o,{actual_hours:p.actual_hours,actual_cost_cny:p.actual_cost_cny,actual_finish_at:now(),repair_result:p.note})}
   if((p.action==='verify'||(p.action==='cancel'&&o.actual_start_at))&&o.spare_parts?.length){if(!Array.isArray(p.actual_parts))fail(422,'请逐项确认备件实际耗用');s.consume(o,p.actual_parts)}
   if(p.action==='cancel')s.release(id);
   o.status=map[p.action][1];if(p.action==='revise'){o.maintenance_action=p.note;for(const k of ['start_at','end_at','staff_id','staff_ids','approved_at','approval_business_revision','execution_check','business_revision','constraints_snapshot'])delete o[k]}
   if(p.action==='verify'){const record={maintenance_id:id,work_order_id:id,equipment_id:o.equipment_id,maintenance_date:o.actual_finish_at,verified_at:now(),actual_start_at:o.actual_start_at,maintenance_type:'工单维修验收',maintenance_result:o.repair_result,actual_hours:o.actual_hours,actual_cost_cny:o.actual_cost_cny,verified_by:s.user.display_name,data_origin:'USER_VERIFIED_MAINTENANCE',source_alert_id:o.source_alert_id};s.write('INSERT INTO maintenance_events VALUES(?,?,?,?,?)',id,o.dataset_version,o.equipment_id,encode(record),now());if(o.dataset_version===s.version)s.write("INSERT INTO records(table_name,row_index,content) SELECT 'maintenance_history',COALESCE(MAX(row_index),-1)+1,? FROM records WHERE table_name='maintenance_history'",encode(record))}
  }else if(action==='manage'){
   text(p.note,2);if(p.action==='archive'){if(!['草稿·待排程','已退回','已驳回','已取消','已完成'].includes(old))fail(409,'请先撤回未开工安排');Object.assign(o,{deleted_at:now(),deleted_by:s.user.display_name,deleted_from_status:old});if(old!=='已完成')o.status='已取消';s.release(id)}
   else if(p.action==='restore'){if(!o.deleted_at)fail(409,'工单不在回收站');const restored=o.deleted_from_status;if(!FINAL.has(restored)&&s.orders.some(x=>x!==o&&!x.deleted_at&&x.equipment_id===o.equipment_id&&x.dataset_version===o.dataset_version&&!FINAL.has(x.status)))fail(409,'设备已有未完成工单');o.status=restored;for(const k of ['deleted_at','deleted_by','deleted_from_status'])delete o[k]}
   else if(p.action==='withdraw'){if(old==='待验收'){o.status='执行中';for(const k of ['actual_finish_at','actual_hours','actual_cost_cny','repair_result'])delete o[k]}else{if(!['待审批','已批准','已接单','已取消','已退回','已驳回'].includes(old)||o.actual_start_at)fail(409,'已开工或验收记录不可撤回');o.status='草稿·待排程';s.release(id);for(const k of ['start_at','end_at','staff_id','staff_ids','staff_name','approved_at','approver','approval_business_revision','execution_check','business_revision','constraints_snapshot'])delete o[k]}}
   else fail(422,'未知管理操作');
  }else if(action==='timeline'){
   if(!['待审批','已批准','已接单'].includes(old)||o.actual_start_at||o.dataset_version!==s.version)fail(409,'仅当前数据的未开工安排可调整');text(p.note,2);if(!Array.isArray(p.staff_ids)||new Set(p.staff_ids).size!==p.staff_ids.length)fail(422,'人员缺失或重复');
   const fingerprint=await s.fingerprint();if(p.apply&&p.state_fingerprint!==fingerprint)fail(409,'预览后资源已变化，请重新校验');const c=candidate(s,o.equipment_id),start=date(p.start_at),end=date(p.end_at),limits=scenario(s,p.scenario_id);if(end-start<c.hours*3600000||start<Date.now()||start<date(c.window_start)||end>date(c.window_end))fail(422,'调整时间超出有效停机窗口或时长不足');
   const others=s.orders.filter(x=>x!==o&&!x.deleted_at&&ACTIVE.has(x.status));const same=others.filter(x=>x.dataset_version===o.dataset_version);if(c.cost+same.reduce((n,x)=>n+(x.cost||0),0)>limits.budget||(end-start)/3600000+same.reduce((n,x)=>n+(x.hours||0),0)>limits.max_downtime_h)fail(422,'调整超出预算或累计停机限制');for(const [name,q] of Object.entries(quantities(c.spare_parts)))if(q>s.available(name,o.inventory_scope||o.dataset_version,id).available_to_allocate)fail(422,'备件库存不足');
   const checked=place(s,{...c,hours:(end-start)/3600000,window_start:p.start_at,window_end:p.end_at},limits,others,p.start_at,p.staff_ids.map(String));if(date(checked.start_at)!==start||date(checked.end_at)!==end)fail(422,'调整时间未通过完整约束校验');result={success:true,preview:!p.apply,scheduled:checked,state_fingerprint:fingerprint,requires_approval:true,message:'校验通过，保存后退回待审批'};if(!p.apply)return result;
   s.release(id);Object.assign(o,checked,{scenario_id:limits.id,constraints_snapshot:limits,business_revision:s.businessRevision,status:'待审批'});for(const k of ['approver','approved_at','approval_decision_at','approval_note','approval_business_revision','execution_check'])delete o[k];
  }
  s.save(o,action==='transition'||action==='manage'?p.action:action,p.note,old);result={...result,success:true,work_order_id:id,status:o.status,version:o.version,request_id:requestId};
 }
 s.recordReceipt(requestId,signature,result);await s.commit();return result;
}

async function resources(s,path,p){
 const m=/^\/api\/resources\/(staff|orders|scenarios|requirements|inventory)\/([^/]+)$/.exec(path);if(!m)return null;
 const kind=m[1],id=decodeURIComponent(m[2]);text(id,1,100);
 if(kind==='inventory'){
  number(p.on_hand);if(!Number.isInteger(p.on_hand))fail(422,'库存数量必须为整数');text(p.note,2,500);const old=s.stock.find(x=>x.scope===s.scope&&x.part_name===id);if(old&&p.version!==old.version)fail(409,'库存已变化，请刷新');s.write('INSERT OR REPLACE INTO inventory_stock VALUES(?,?,?,?,?,?)',s.scope,id,p.on_hand,(old?.version||0)+1,now(),'manual_count');s.write('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?)',crypto.randomUUID(),s.scope,id,null,'count',p.on_hand-(old?.on_hand||0),p.note,now());
 }else{
  const table=kind==='requirements'?'maintenance_rules':kind,key={staff:'staff_id',orders:'order_id',scenarios:'scenario_id',requirements:'equipment_id'}[kind];
  if(['orders','requirements'].includes(kind)&&!(s.data.equipment||[]).some(x=>x.equipment_id===(p.equipment_id||id)))fail(422,'设备不存在');
  if(kind==='staff'){text(p.staff_name,1,100);if(!Array.isArray(p.skills)||!p.skills.length||p.skills.some(x=>typeof x!=='string'||!x.trim()))fail(422,'人员技能无效');number(p.available_hours,Number.MIN_VALUE,24);if(date(p.shift_end)<=date(p.shift_start)||p.available_hours*3600000>date(p.shift_end)-date(p.shift_start))fail(422,'班次或可用工时无效');p.skills=p.skills.join(',')}
  if(kind==='orders'){text(p.order_name,1,200);if(date(p.end_at)<=date(p.start_at)||date(p.due_at)<date(p.end_at))fail(422,'生产订单时间无效');number(p.delay_cost_cny_per_hour??0)}
  if(kind==='scenarios'){text(p.scenario_name,1,100);number(p.maintenance_budget_cny);number(p.available_staff_count,1,1000);if(!Number.isInteger(p.available_staff_count))fail(422,'人数必须为整数');number(p.max_downtime_h,Number.MIN_VALUE,100000);number(p.risk_threshold??.35,0,1)}
  if(kind==='requirements'){number(p.maintenance_hours,Number.MIN_VALUE,10000);number(p.maintenance_cost_cny);number(p.required_staff_count,1,100);if(!Number.isInteger(p.required_staff_count))fail(422,'所需人数无效');text(p.required_skill);if(date(p.window_end)-date(p.window_start)<p.maintenance_hours*3600000)fail(422,'设备停机窗口不足');quantities(p.spare_parts);for(const part of p.spare_parts||[]){if(part.quantity<1)fail(422,'计划备件数量必须大于0');number(part.available_quantity);if(!Number.isInteger(part.available_quantity))fail(422,'库存数量无效');if(!s.stock.some(x=>x.scope===s.scope&&x.part_name===part.part_name))s.write('INSERT INTO inventory_stock VALUES(?,?,?,?,?,?)',s.scope,part.part_name,0,1,now(),'legacy_unverified')}}
  const existing=(s.data[table]||[]).find(x=>x[key]===id),index=existing?existing._index:Math.max(-1,...(s.data[table]||[]).map(x=>x._index))+1;const content={...existing,...p,[key]:id,data_origin:'USER_CONFIRMED_OPERATIONAL_INPUT',configuration_status:'configured'};delete content._index;for(const k of Object.keys(content))if(/(?:_at|_start|_end)$/.test(k)&&typeof content[k]==='string'&&/^\d{4}-/.test(content[k]))content[k]=stamp(date(content[k]));s.write('INSERT OR REPLACE INTO records VALUES(?,?,?)',table,index,encode(content));
 }
 const revision=String(Number(s.businessRevision)+1);s.write("INSERT OR REPLACE INTO settings VALUES('business_revision',?)",revision);s.audit('resource_updated',id,{kind,revision});await s.commit();return {success:true,business_revision:Number(revision),message:'已保存，旧安排需重新核对'};
}

export async function workOrders(request,env,user){
 const url=new URL(request.url);if(!/^\/api\/(?:work-orders(?:\/|$)|alerts\/[^/]+\/action$|maintenance-requests$|schedule\/generate$|maintenance\/(?:timeline|time-readiness)$|resources(?:\/|$)|equipment\/[^/]+\/operations$|operations\/resource-occupancy$)/.test(url.pathname))return null;
 if(request.method==='POST'&&!['developer','admin','user'].includes(user.role))return Response.json({detail:'只读账号不能修改工单或资源'},{status:403});
 try{const s=await new State(env.BUSINESS_DB,user).load(request,url,String(env.BUSINESS_SCHEMA_VERSION)==='2');const body=await route(request,s,url);return body===null?Response.json({detail:'工单接口不存在'},{status:404}):Response.json(body,{headers:{'Cache-Control':'no-store'}})}catch(e){if(e instanceof Problem)return Response.json({detail:e.message},{status:e.status});throw e}
}

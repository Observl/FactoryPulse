import {read,utils} from "xlsx";
type Row=Record<string,unknown>;
type Tables=Record<string,Row[]>;
const names:Record<string,string>={
 equipment:"01_设备档案",readings:"02_运行监测",maintenance_rules:"03_维护参数",
 maintenance_history:"04_维护历史",staff:"05_维修人员",orders:"06_生产订单",
 scenarios:"07_策略情景",demo_risks:"08_风险评分演示"
};
const required:Record<string,string[]>={
 equipment:["equipment_id","equipment_name","equipment_type","status"],
 readings:["reading_id","equipment_id","timestamp","air_temperature_k","process_temperature_k","rotational_speed_rpm","torque_nm","tool_wear_min"],
 maintenance_rules:["equipment_id","inspection_cost_cny","repair_cost_cny","inspection_duration_h","assumed_failure_loss_cny","repair_duration_h","required_staff_count"],
 maintenance_history:["maintenance_id","equipment_id"],
 staff:["staff_id","available_hours"],
 orders:["order_id","equipment_id"],
 scenarios:["scenario_id","maintenance_budget_cny","risk_threshold","available_staff_count","max_downtime_h"],
 demo_risks:["equipment_id","risk_score"]
};
const key="factorypulse_pages_demo_v1";
const n=(v:unknown,defaultValue=0)=>{const x=Number(v);return Number.isFinite(x)?x:defaultValue};
const demo=():Tables=>{
 const ids=Array.from({length:12},(_,i)=>"CNC-"+String(i+1).padStart(3,"0"));
 return {
 equipment:ids.map((equipment_id,i)=>({equipment_id,equipment_name:"模拟数控机床 "+(i+1),equipment_type:"CNC",status:i%5===0?"预警":"运行中",production_line:"L"+(1+i%3)})),
 readings:ids.flatMap((equipment_id,i)=>Array.from({length:12},(_,j)=>({reading_id:"R-"+i+"-"+j,equipment_id,timestamp:"2026-10-"+String(1+j).padStart(2,"0")+" 08:00:00",air_temperature_k:297+i*.2,process_temperature_k:308+i*.3+j*.1,rotational_speed_rpm:1400+20*i,torque_nm:30+i,tool_wear_min:30+j*10}))),
 maintenance_rules:ids.map(equipment_id=>({equipment_id,inspection_cost_cny:150,repair_cost_cny:600,inspection_duration_h:1,assumed_failure_loss_cny:4500,repair_duration_h:2,required_staff_count:1})),
 maintenance_history:ids.flatMap((equipment_id,i)=>Array.from({length:3},(_,j)=>({maintenance_id:"M-"+i+"-"+j,equipment_id,maintenance_type:"模拟保养",cost_cny:300}))),
 staff:Array.from({length:4},(_,i)=>({staff_id:"ST-"+(i+1),available_hours:8})),
 orders:Array.from({length:30},(_,i)=>({order_id:"O-"+(i+1),equipment_id:ids[i%12],order_qty:20+i})),
 scenarios:[{scenario_id:"SC-1",scenario_name:"基准预算",maintenance_budget_cny:3000,risk_threshold:.6,available_staff_count:2,max_downtime_h:12},{scenario_id:"SC-2",scenario_name:"紧缩预算",maintenance_budget_cny:1500,risk_threshold:.7,available_staff_count:1,max_downtime_h:6}],
 demo_risks:ids.map((equipment_id,i)=>({equipment_id,risk_score:Number((.1+((i*17)%85)/100).toFixed(2))}))
 };
};
let tables:Tables=demo();
let uploadedFilename="内置模拟数据（可上传原始测试Excel替换）";
try{const stored=localStorage.getItem(key);if(stored){const state=JSON.parse(stored) as {tables:Tables;filename:string};if(state.tables?.equipment?.length){tables=state.tables;uploadedFilename=state.filename}}}catch{}
function response(body:unknown,status=200,headers?:HeadersInit){return new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json; charset=utf-8",...headers}})}
function error(message:string,status=422){return response({detail:message},status)}
function latestByDevice(){const last=new Map<string,Row>();for(const r of tables.readings||[]){const id=String(r.equipment_id);if(!last.has(id)||String(r.timestamp)>String(last.get(id)?.timestamp))last.set(id,r)}return last}
function devices(){const risk=new Map((tables.demo_risks||[]).map(r=>[String(r.equipment_id),r]));const last=latestByDevice();return (tables.equipment||[]).map(e=>{const id=String(e.equipment_id);const score=n(risk.get(id)?.risk_score);return {...e,risk_score:score,risk_level:score>=.7?"高":score>=.4?"中":"低",risk_origin:"DEMO_ONLY_NOT_MODEL_OUTPUT",latest_reading:last.get(id)||{}}})}
function overview(){const ds=devices();const scores=ds.map(d=>n(d.risk_score));return {devices:ds,counts:Object.fromEntries(Object.keys(names).map(k=>[k,tables[k]?.length||0])),metrics:{total:ds.length,high:scores.filter(x=>x>=.7).length,warning:scores.filter(x=>x>=.4&&x<.7).length,avg_risk:scores.length?Number((scores.reduce((a,b)=>a+b,0)/scores.length).toFixed(3)):0},filename:uploadedFilename,risk_source:"网页端本地演示数据（非训练模型预测）"}}
function validate(next:Tables){
 const ids=new Set((next.equipment||[]).map(r=>String(r.equipment_id)));
 if(!ids.size||ids.size!==next.equipment.length)throw Error("设备档案为空或设备编号重复");
 for(const k of ["readings","maintenance_rules","maintenance_history","orders","demo_risks"]){
  for(const row of next[k])if(!ids.has(String(row.equipment_id)))throw Error(names[k]+" 中存在未知设备编号："+String(row.equipment_id))
 }
 if(new Set(next.demo_risks.map(r=>String(r.equipment_id))).size!==next.demo_risks.length)throw Error("风险评分表设备编号重复");
 for(const r of next.demo_risks)if(!Number.isFinite(Number(r.risk_score))||n(r.risk_score)<0||n(r.risk_score)>1)throw Error("风险评分必须为0至1的数值");
 for(const k of ["readings","maintenance_rules","staff","orders","scenarios"])if(!next[k].length)throw Error(names[k]+" 不可为空");
}
async function parseFile(file:File){
 if(!file.name.toLowerCase().endsWith(".xlsx"))throw Error("请使用 .xlsx 格式");
 if(file.size>8*1024*1024)throw Error("文件不可超过8MB");
 const book=read(await file.arrayBuffer(),{type:"array",cellDates:true});
 const next:Tables={};
 for(const [k,title] of Object.entries(names)){
  const sheet=book.Sheets[title];if(!sheet)throw Error("缺少工作表："+title);
  const grid=utils.sheet_to_json<unknown[]>(sheet,{header:1,defval:null,raw:false});
  const header=(grid[0]||[]).map(v=>String(v??"").trim());
  const missing=required[k].filter(h=>!header.includes(h));if(missing.length)throw Error(title+" 缺少字段："+missing.join("、"));
  next[k]=utils.sheet_to_json<Row>(sheet,{defval:null,raw:false}).filter(x=>Object.values(x).some(v=>v!==null&&v!==""));
 }
 validate(next);tables=next;uploadedFilename=file.name;
 try{localStorage.setItem(key,JSON.stringify({tables,filename:uploadedFilename}))}catch{}
 return {success:true,filename:file.name,counts:Object.fromEntries(Object.entries(next).map(([k,v])=>[k,v.length]))};
}
function simulate(body:Record<string,unknown>){
 if(!tables.equipment?.length)throw Error("请先导入Excel");
 const ss=tables.scenarios||[];const s=ss.find(x=>x.scenario_id===body.scenario_id)||ss[0]||{};
 const budget=body.budget!==undefined?n(body.budget):n(s.maintenance_budget_cny,3000);
 const threshold=body.risk_threshold!==undefined?n(body.risk_threshold):n(s.risk_threshold,.6);
 const people=body.staff_count!==undefined?n(body.staff_count):n(s.available_staff_count,2);
 const maxHours=body.max_downtime_h!==undefined?n(body.max_downtime_h):n(s.max_downtime_h,8);
 const strategy=String(body.strategy||"optimized");
 if(!["optimized","risk_threshold","fixed_interval"].includes(strategy))throw Error("未知策略");
 const rules=new Map((tables.maintenance_rules||[]).map(r=>[String(r.equipment_id),r]));
 const candidates=devices().map(d=>{const rule=rules.get(String(d.equipment_id))||{};const cost=n(rule.inspection_cost_cny,150)+n(rule.repair_cost_cny,600);const hours=n(rule.inspection_duration_h,1)+n(rule.repair_duration_h,2);const staff=n(rule.required_staff_count,1);const loss=n(rule.assumed_failure_loss_cny,4500);const benefit=.6*n(d.risk_score)*loss;return {equipment_id:String(d.equipment_id),equipment_name:String(d.equipment_name),risk:n(d.risk_score),cost,hours,people:staff,expected_loss_avoided:Number(benefit.toFixed(2)),net_value:Number((benefit-cost).toFixed(2))}});
 if(strategy==="optimized")candidates.sort((a,b)=>b.net_value/Math.max(b.cost,1)-a.net_value/Math.max(a.cost,1));
 else if(strategy==="risk_threshold")candidates.sort((a,b)=>b.risk-a.risk);
 else candidates.sort((a,b)=>a.equipment_id.localeCompare(b.equipment_id));
 let spent=0,elapsed=0;
 const output:typeof candidates=[];
 for(const task of candidates){
  if(strategy==="risk_threshold"&&task.risk<threshold)continue;
  if(strategy==="optimized"&&task.net_value<=0)continue;
  if(task.people>people||spent+task.cost>budget||elapsed+task.hours>maxHours)continue;
  spent+=task.cost;elapsed+=task.hours;output.push(task);
 }
 const baseline=devices().reduce((a,d)=>a+n(d.risk_score)*n(rules.get(String(d.equipment_id))?.assumed_failure_loss_cny,4500),0);
 const avoided=output.reduce((a,d)=>a+d.expected_loss_avoided,0);
 return {scenario:String(s.scenario_name||"自定义"),strategy,selected:output,constraints:{budget,risk_threshold:threshold,staff_count:people,max_downtime_h:maxHours},summary:{task_count:output.length,maintenance_cost:Number(spent.toFixed(2)),maintenance_hours:Number(elapsed.toFixed(2)),baseline_expected_loss:Number(baseline.toFixed(2)),expected_loss_after:Number((baseline-avoided).toFixed(2)),illustrative_total_cost:Number((baseline-avoided+spent).toFixed(2))},disclaimer:"网页端浏览器计算，维护降风险60%仅为演示假设；贪心非全局最优，成本非真实工厂收益。"};
}
function exportCsv(scenario:string,strategy:string){
 const r=simulate({scenario_id:scenario,strategy});const fields=["设备ID,设备名称,演示风险,维护成本,工时,人员数,假设避免损失"];for(const v of r.selected)fields.push([v.equipment_id,v.equipment_name,v.risk,v.cost,v.hours,v.people,v.expected_loss_avoided].map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(","));
 return "\ufeff"+fields.join("\r\n");
}
export function installDemoApi(){
 const native=window.fetch.bind(window);
 window.fetch=async (input:RequestInfo|URL,init?:RequestInit)=>{
  const url=typeof input==="string"?input:input instanceof URL?input.href:input.url;
  const path=new URL(url,location.href);
  if(!path.pathname.startsWith("/api/"))return native(input,init);
  try{
   if(path.pathname==="/api/health")return response({status:"ok",mode:"github-pages-local-browser"});
   if(path.pathname==="/api/overview")return response(overview());
   if(path.pathname.startsWith("/api/records/")){const key=path.pathname.split("/").pop()||"";if(!names[key])return error("不存在的数据表",404);const all=tables[key]||[];return response({records:all.slice(0,Math.max(1,Math.min(5000,n(path.searchParams.get("limit"),500)))),total:all.length})}
   if(path.pathname==="/api/import"&&init?.method==="POST"){const file=(init.body as FormData).get("file");if(!(file instanceof File))return error("缺少Excel文件");return response(await parseFile(file))}
   if(path.pathname==="/api/simulate"&&init?.method==="POST")return response(simulate(JSON.parse(String(init.body))));
   if(path.pathname==="/api/strategies/compare")return response({strategies:["fixed_interval","risk_threshold","optimized"].map(strategy=>simulate({scenario_id:path.searchParams.get("scenario_id"),strategy}))});
   if(path.pathname==="/api/export/maintenance.csv")return new Response(exportCsv(path.searchParams.get("scenario_id")||"",path.searchParams.get("strategy")||"optimized"),{headers:{"Content-Type":"text/csv; charset=utf-8","Content-Disposition":'attachment; filename="factorypulse_maintenance_plan.csv"'}});
   if(path.pathname==="/api/developer/settings")return response({provider:"none",base_url:"",model:"",has_api_key:false,mode:"static"},init?.method==="POST"?403:200);
   if(path.pathname==="/api/developer/test-connection")return error("GitHub Pages为静态站点，不提供安全的服务端API代理。请下载桌面版进行AI API配置。",403);
   if(path.pathname==="/api/copilot/chat")return error("网页版不发送第三方AI请求，请下载桌面版或另行部署受保护后端。",403);
   return error("浏览器演示模式不支持该API接口",404);
  }catch(e){return error(e instanceof Error?e.message:"浏览器端操作失败")}
 };
}

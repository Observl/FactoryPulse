import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Reading = { equipment_id?: string; timestamp?: string; process_temperature_k?: number | string; air_temperature_k?: number | string; rotational_speed_rpm?: number | string; torque_nm?: number | string; tool_wear_min?: number | string };
type Device = { equipment_id: string; equipment_name: string; equipment_type?: string; status: string; production_line?: string; risk_score: number; latest_reading?: Reading };
type Overview = { devices: Device[]; counts: Record<string, number>; filename: string; metrics: { total: number; high: number; warning: number; avg_risk: number } };
const palette = ["#f97316","#ffba77","#64748b","#cbd5e1","#94a3b8","#ea580c"];
const toNum = (x: unknown): number | null => { if (x === null || x === undefined || x === "") return null; const n=Number(x); return Number.isFinite(n) ? n : null; };
const avg = (values: (number | null)[]) => { const valid = values.filter((v): v is number => v !== null); return valid.length ? valid.reduce((a,b)=>a+b,0)/valid.length : null; };
function Figure({value,suffix="",digits=0}:{value:number|null|undefined;suffix?:string;digits?:number}) { return <>{value===null||value===undefined?"—":value.toFixed(digits)+suffix}</> }
function Stat({label,value,desc,accent=false}:{label:string;value:React.ReactNode;desc:string;accent?:boolean}) { return <div className="metric"><span>{label}</span><strong className={accent?"orange":""}>{value}</strong><small>{desc}</small></div> }
function Panel({title,note,children}:{title:string;note:string;children:React.ReactNode}) { return <section className="panel"><div className="panel-heading"><h2>{title}</h2><span>{note}</span></div>{children}</section> }
function Placeholder({message}:{message:string}) { return <div className="chart-empty">{message}</div> }

export function EquipmentInsights({data}:{data:Overview}) {
 const {devices,counts}=data;
 const chart=useMemo(()=>{
  const lines=[...new Set(devices.map(d=>d.production_line||"未分配"))].sort();
  const statuses=[...new Set(devices.map(d=>d.status||"未标注"))].sort();
  return {statuses,data:lines.map(name=>{
    const ds=devices.filter(d=>(d.production_line||"未分配")===name);
    return {name,total:ds.length,...Object.fromEntries(statuses.map(status=>[status,ds.filter(d=>(d.status||"未标注")===status).length]))};
  })};
 },[devices]);
 const types=new Set(devices.map(d=>d.equipment_type||"未知"));
 const withReadings=devices.filter(d=>toNum(d.latest_reading?.rotational_speed_rpm)!==null).length;
 const statusColor=(status:string,index:number)=> /预警|告警|高风险|异常|故障|停机/.test(status)?"#f97316":/正常|运行/.test(status)?"#4e9c85":palette[(index+2)%palette.length];
 return <>
  <div className="metrics">
   <Stat label="设备总数" value={devices.length} desc="来自设备档案"/>
   <Stat label="设备类型" value={types.size} desc="不同设备类别"/>
   <Stat label="有监测数据的设备" value={withReadings} desc="具有有效转速记录"/>
   <Stat label="运行监测记录" value={counts.readings||0} desc="Excel历史采样数量"/>
  </div>
  <Panel title="各产线设备状态分布" note="堆叠条形图 · 数量/状态合并">
   {chart.data.length?<div className="insight-chart stacked-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={chart.data} layout="vertical" margin={{top:8,right:25,bottom:8,left:7}}><CartesianGrid stroke="#eff1f4" horizontal={false}/><XAxis type="number" allowDecimals={false}/><YAxis type="category" dataKey="name" width={85} tick={{fontSize:12}}/><Tooltip formatter={(value,name)=>[Number(value).toFixed(0)+" 台",String(name)]}/><Legend/>{chart.statuses.map((status,i)=><Bar key={status} stackId="status" dataKey={status} name={status} fill={statusColor(status,i)} radius={0}/>)}</BarChart></ResponsiveContainer></div>:<Placeholder message="导入Excel后显示产线设备状态分布"/>}
   <p className="insight-note">每条横柱代表一条产线，分块颜色代表Excel中的设备状态，各色块之和为该产线设备总数。</p>
  </Panel>
 </>;
}

export function RiskInsights({devices}:{devices:Device[]}) {
 const [focused,setFocused]=useState("");
 const ranked=[...devices].sort((a,b)=>Number(b.risk_score)-Number(a.risk_score));
 const high=ranked.filter(d=>d.risk_score>=0.7).length,mid=ranked.filter(d=>d.risk_score>=0.4&&d.risk_score<0.7).length,low=ranked.filter(d=>d.risk_score<0.4).length;
 const dist=[{name:"低风险 (<40%)",value:low},{name:"中风险 (40–70%)",value:mid},{name:"高风险 (≥70%)",value:high}];
 const top=ranked.slice(0,8).map(d=>({name:d.equipment_id,risk:Number((d.risk_score*100).toFixed(2))}));
 const selected=ranked.find(d=>d.equipment_id===focused);
 const averageRisk=devices.length?devices.reduce((total,d)=>total+d.risk_score,0)/devices.length*100:null;
 return <>
  <div className="metrics">
    <Stat label="高风险设备" value={high} desc="演示评分 ≥ 70%" accent/>
    <Stat label="中风险设备" value={mid} desc="演示评分 40%–70%"/>
    <Stat label="低风险设备" value={low} desc="演示评分 < 40%"/>
    <Stat label="平均模拟风险" value={<Figure value={averageRisk} suffix="%" digits={1}/>} desc="非训练模型预测"/>
  </div>
  <div className="content-grid">
    <Panel title="演示风险排行 TOP 8" note="按评分从高到低">
     {top.length?<div className="insight-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={top} layout="vertical" margin={{left:10,right:20}}><CartesianGrid stroke="#eff1f4" horizontal={false}/><XAxis type="number" domain={[0,100]} unit="%"/><YAxis type="category" dataKey="name" width={68} tick={{fontSize:11}}/><Tooltip formatter={(v)=>[String(v)+"%","模拟风险"]}/><Bar dataKey="risk" fill="#f97316" radius={[0,5,5,0]} onClick={(entry: any)=>setFocused(String(entry?.name??entry?.payload?.name??""))}/></BarChart></ResponsiveContainer></div>:<Placeholder message="暂无演示风险数据"/>}
    </Panel>
    <Panel title="风险等级结构" note="40% / 70% 分界阈值">
     {devices.length?<div className="insight-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={dist} dataKey="value" nameKey="name" innerRadius={52} outerRadius={91} label>{dist.map((_,i)=><Cell key={i} fill={["#94a3b8","#ffba77","#f97316"][i]}/>)}</Pie><Tooltip/><Legend/></PieChart></ResponsiveContainer></div>:<Placeholder message="暂无风险分布数据"/>}
    </Panel>
  </div>
  <div className="risk-device-select"><span>点击图表柱形或以下设备查看详情：</span>{top.map(d=><button key={d.name} className={focused===d.name?"risk-chip active":"risk-chip"} onClick={()=>setFocused(d.name)}>{d.name}</button>)}</div>
  {selected&&<div className="selected-detail"><div><b>{selected.equipment_name}</b><span>{selected.equipment_id} · {selected.production_line||"未分配产线"}</span></div><div>演示风险 <b>{(selected.risk_score*100).toFixed(1)}%</b></div><div>设备状态 <b>{selected.status}</b></div><button onClick={()=>setFocused("")}>清除选择</button></div>}
  <p className="insight-note">风险值来自测试Excel“08_风险评分演示”，不是AI模型输出。阈值仅为界面演示分组规则。</p>
 </>;
}

export function AnomalyInsights({devices,version}:{devices:Device[];version:string}) {
 const [readings,setReadings]=useState<Reading[]>([]);
 const [selected,setSelected]=useState("");
 const [loading,setLoading]=useState(true);
 useEffect(()=>{
  let active=true;setLoading(true);
  fetch("/api/records/readings?limit=5000").then(r=>{if(!r.ok)throw Error("无法加载");return r.json()}).then((v:{records:Reading[]})=>{if(active)setReadings(v.records||[])}).catch(()=>{if(active)setReadings([])}).finally(()=>{if(active)setLoading(false)});
  return()=>{active=false};
 },[version]);
 useEffect(()=>{if(!devices.find(d=>d.equipment_id===selected))setSelected(devices[0]?.equipment_id||"")},[devices,selected]);
 const d=devices.find(x=>x.equipment_id===selected);
 const history=readings.filter(r=>r.equipment_id===selected).sort((a,b)=>String(a.timestamp||"").localeCompare(String(b.timestamp||""))).slice(-60);
 const trend=history.map((r,i)=>({time:String(r.timestamp||i).slice(5,16),temperature:toNum(r.process_temperature_k),speed:toNum(r.rotational_speed_rpm),wear:toNum(r.tool_wear_min)}));
 const temps=devices.map(x=>toNum(x.latest_reading?.process_temperature_k));
 const speeds=devices.map(x=>toNum(x.latest_reading?.rotational_speed_rpm));
 const visible=devices.filter(x=>toNum(x.latest_reading?.process_temperature_k)!==null).length;
 const tempComparison=devices.map(x=>({name:x.equipment_id,temperature:toNum(x.latest_reading?.process_temperature_k)})).filter(x=>x.temperature!==null);
 return <>
  <div className="metrics">
   <Stat label="设备监测覆盖" value={`${visible}/${devices.length}`} desc="具备工艺温度读数"/>
   <Stat label="平均工艺温度" value={<Figure value={avg(temps)} suffix=" K" digits={1}/>} desc="最新监测值"/>
   <Stat label="平均设备转速" value={<Figure value={avg(speeds)} suffix=" rpm" digits={0}/>} desc="最新监测值"/>
   <Stat label="可查看的历史采样" value={readings.length} desc={loading?"加载中":"已加载记录数"}/>
  </div>
  <div className="content-grid">
   <Panel title="设备工艺温度对比" note="各设备最新监测值">
    {tempComparison.length?<div className="insight-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={tempComparison}><CartesianGrid stroke="#eff1f4" vertical={false}/><XAxis dataKey="name" tick={{fontSize:10}}/><YAxis domain={["auto","auto"]} unit=" K"/><Tooltip formatter={v=>[String(v)+" K","工艺温度"]}/><Bar dataKey="temperature" fill="#f97316" radius={[5,5,0,0]}/></BarChart></ResponsiveContainer></div>:<Placeholder message="暂无温度监测记录"/>}
   </Panel>
   <Panel title="单台设备工况趋势" note="历史监测采样">
    <label className="insight-select-label">选择设备<select value={selected} onChange={e=>setSelected(e.target.value)}>{devices.map(x=><option key={x.equipment_id} value={x.equipment_id}>{x.equipment_id} · {x.equipment_name}</option>)}</select></label>
    {trend.length?<div className="insight-chart compact"><ResponsiveContainer width="100%" height="100%"><LineChart data={trend}><CartesianGrid stroke="#eff1f4" vertical={false}/><XAxis dataKey="time" tick={{fontSize:10}} interval="preserveStartEnd"/><YAxis yAxisId="temp" domain={["auto","auto"]} tick={{fontSize:10}}/><YAxis yAxisId="rpm" orientation="right" domain={["auto","auto"]} tick={{fontSize:10}}/><Tooltip/><Legend/><Line yAxisId="temp" name="工艺温度(K)" dataKey="temperature" stroke="#f97316" strokeWidth={2} dot={false} connectNulls/><Line yAxisId="rpm" name="转速(rpm)" dataKey="speed" stroke="#64748b" strokeWidth={2} dot={false} connectNulls/></LineChart></ResponsiveContainer></div>:<Placeholder message="暂无该设备历史监测数据"/>}
   </Panel>
  </div>
  <p className="insight-note">工况图表提供可核查的数据证据，不表示温度或转速与故障之间具有因果关系；该页面尚未接入模型特征归因或真实AI解释。</p>
 </>;
}

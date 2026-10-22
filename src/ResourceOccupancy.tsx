import {Button} from "./components/Button";
import {LoadingPanel} from "./LoadingPanel";
import {useEffect,useState} from "react";
import {apiRequest,errorMessage} from "./api";
import {FieldHint} from "./ProfessionalTerm";

type Work={work_order_id:string;equipment_id:string;status:string;start_at?:string;end_at?:string;current_dataset:boolean};
type Person={staff_id:string;staff_name?:string;skills?:string;shift_start?:string;shift_end?:string;available_hours?:number;bookings:Work[]};
type Order={order_id:string;equipment_id:string;order_name?:string;start_at?:string;end_at?:string;due_at?:string;related_work_orders:Work[]};
export function ResourceOccupancy({kind,identifier,revision,onOpenWorkOrder}:{kind:"staff"|"orders";identifier:string;revision:number;onOpenWorkOrder?:(id:string)=>void}){
 const [data,setData]=useState<{staff:Person[];orders:Order[]}|null>(null),[error,setError]=useState("");
 useEffect(()=>{let active=true;setData(null);setError("");apiRequest("/operations/resource-occupancy").then(value=>{if(active)setData(value)}).catch(reason=>{if(active)setError(errorMessage(reason))});return()=>{active=false}},[revision]);
 const selected=kind==="staff"?data?.staff.filter(person=>!identifier||person.staff_id===identifier):data?.orders.filter(order=>!identifier||order.order_id===identifier);
 const work=(items:Work[])=>items.length?<ul>{items.map(item=><li key={item.work_order_id}><Button className="text-link" disabled={!onOpenWorkOrder} onClick={()=>onOpenWorkOrder?.(item.work_order_id)}>{item.work_order_id}</Button> · {item.status} · {item.start_at||"时间未提供"} 至 {item.end_at||"未提供"}{!item.current_dataset?" · 其他数据版本":""}</li>)}</ul>:<span>暂无未闭环关联工单</span>;
 return <details className="detail-section"><summary>{kind==="staff"?"人员班次与工单占用":"生产占用与关联维护工单"}</summary><p className="hint">{kind==="staff"?"技能、班次和可用工时用于决定能否分配维修任务。待审批任务只表示计划占用，实际开工仍需记录。":"订单时间用于限制设备可停机窗口。关联维护工单不自动表示与生产时间冲突，审批时还需检查具体时间。"}</p>{error&&<p className="alert error" role="alert">{error}</p>}{!data&&!error&&<LoadingPanel title="资源占用" fields={["人员班次","生产占用","关联工单"]}/>}{data&&<div className="table-scroll"><table><thead><tr><th>{kind==="staff"?"人员与技能":"订单与设备"}</th><th>{kind==="staff"?"班次与可用工时":"生产占用与交期"}</th><th><FieldHint text="关联尚未完成的工单，包含待审批、执行和验收阶段。计划起止时间不是实际完成时间。">关联工单</FieldHint></th></tr></thead><tbody>{selected?.map(item=>"staff_id" in item?<tr key={item.staff_id}><td>{item.staff_name||item.staff_id}<small className="cell-secondary">{item.staff_id} · {item.skills||"技能未提供"}</small></td><td>{item.shift_start||"班次未提供"} 至 {item.shift_end||"未提供"}<small className="cell-secondary">已填写可用工时：{item.available_hours??"未提供"} 小时，未在此自动扣减</small></td><td className="evidence-cell">{work(item.bookings)}</td></tr>:<tr key={item.order_id}><td>{item.order_name||item.order_id}<small className="cell-secondary">{item.order_id} · {item.equipment_id}</small></td><td>{item.start_at||"占用时间未提供"} 至 {item.end_at||"未提供"}<small className="cell-secondary">交期：{item.due_at||"未提供"}</small></td><td className="evidence-cell">{work(item.related_work_orders)}</td></tr>)}</tbody></table></div>}</details>;
}

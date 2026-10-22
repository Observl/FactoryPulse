import {Button} from "./components/Button";
import {LoadingPanel} from "./LoadingPanel";
import {useEffect,useState} from "react";
import {apiRequest,errorMessage} from "./api";
import {AuditTrail} from "./AuditTrail";
import {EquipmentTimeline} from "./EquipmentTimeline";
import type {ManagedOrder} from "./WorkOrderPanel";

type Production={order_id:string;order_name?:string;start_at?:string;end_at?:string;due_at?:string;data_origin?:string};
type Work=ManagedOrder&{current_dataset:boolean};
export function EquipmentOperations({equipmentId,dataVersion,onOpenWorkOrder}:{equipmentId:string;dataVersion:string;onOpenWorkOrder:(id:string)=>void}){
 const [data,setData]=useState<{orders:Production[];work_orders:Work[]}|null>(null),[error,setError]=useState("");
 useEffect(()=>{let active=true;setData(null);setError("");apiRequest(`/equipment/${encodeURIComponent(equipmentId)}/operations`).then(result=>{if(active)setData(result)}).catch(reason=>{if(active)setError(errorMessage(reason))});return()=>{active=false}},[equipmentId,dataVersion]);
 return <><section className="detail-section"><div className="detail-section-title"><h3>生产订单与维护任务</h3><span>订单占用期间不安排设备维修</span></div>{error&&<p role="alert" className="alert error">{error}</p>}{!data&&!error&&<LoadingPanel title="生产订单与维护任务" fields={["生产订单","维护工单"]}/>}{data&&<><EquipmentTimeline key={equipmentId+dataVersion} equipment={[{equipment_id:equipmentId}]} production={data.orders.map(order=>({...order,equipment_id:equipmentId}))} orders={data.work_orders.filter(order=>order.current_dataset)} onOpen={order=>onOpenWorkOrder(order.work_order_id)}/><details className="technical-details"><summary>订单与工单明细</summary><div className="table-scroll"><table><thead><tr><th>生产订单</th><th>设备占用开始</th><th>占用结束</th><th>交期</th><th>来源</th></tr></thead><tbody>{data.orders.map(order=><tr key={order.order_id}><td>{order.order_id}<small className="cell-secondary">{order.order_name||"未命名"}</small></td><td>{order.start_at||"未提供"}</td><td>{order.end_at||"未提供"}</td><td>{order.due_at||"未提供"}</td><td>{order.data_origin==="SIMULATED_BUSINESS_DATA"?"模拟经营条件":"企业填写，需核对"}</td></tr>)}</tbody></table></div>{!data.orders.length&&<p className="detail-caption">未录入该设备的生产订单，不代表设备没有生产占用。</p>}<div className="table-scroll"><table><thead><tr><th>维护工单</th><th>状态</th><th>维修人员</th><th>计划时间</th><th>操作</th></tr></thead><tbody>{data.work_orders.map(order=><tr key={order.work_order_id}><td>{order.work_order_id}{!order.current_dataset&&<small className="cell-secondary">其他数据版本，需核对设备身份</small>}</td><td>{order.status}</td><td>{order.staff_name||"待指定"}</td><td>{order.start_at||"待排程"} — {order.end_at||"待排程"}</td><td><Button className="secondary" onClick={()=>onOpenWorkOrder(order.work_order_id)}>查看处理过程</Button></td></tr>)}</tbody></table></div>{!data.work_orders.length&&<p className="detail-caption">尚无关联工单。</p>}</details></>}</section><AuditTrail key={equipmentId} equipmentId={equipmentId}/></>;
}

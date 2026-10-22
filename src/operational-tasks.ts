export type TaskDevice={review_required?:boolean;equipment_id:string;equipment_name:string;risk_available?:boolean;risk_score:number;prediction_at?:string;recommended_by?:string;prediction_window?:string};
export type TaskOrder={work_order_id:string;equipment_id:string;status:string;dataset_version?:string;staff_id?:string;staff_ids?:string[];staff_name?:string;end_at?:string;latest_finish_at?:string};
export type TaskAlert={alert_id:string;equipment_id:string;status:string;dataset_version?:string;prediction_at?:string;defer_until?:string};
export type OperationalTask={id:string;equipment:string;category:string;status:string;owner:string;due:string;overdue:boolean;condition:string;action:string;deviceId?:string;alertId?:string;workOrderId?:string;oldVersion?:boolean};

export function operationalTasks(devices:TaskDevice[],orders:TaskOrder[],alerts:TaskAlert[],version:string,now:number,technicianId?:string):OperationalTask[]{
 const tasks:OperationalTask[]=[];
 const expired=(value?:string)=>!!value&&Number.isFinite(new Date(value).getTime())&&new Date(value).getTime()<=now;
 if(!technicianId)for(const device of devices){
  const decisions=alerts.filter(alert=>alert.dataset_version===version&&alert.equipment_id===device.equipment_id&&alert.prediction_at===device.prediction_at);
  const deferred=decisions.find(alert=>alert.status==="已延期");
  const deferredDue=!!deferred&&expired(deferred.defer_until);
  if((device.risk_available===false||(device.review_required===false||(device.review_required===undefined&&device.risk_score<.15)))&&!deferredDue)continue;
  if(decisions.some(alert=>["已驳回","已转工单"].includes(alert.status)))continue;
  if(deferred&&!expired(deferred.defer_until))continue;
  const due=deferred?.defer_until||device.recommended_by||"";
  tasks.push({id:`alert:${device.equipment_id}:${device.prediction_at||version}`,equipment:`${device.equipment_id} · ${device.equipment_name}`,category:"预警复核",status:deferred?"延期复核到期":decisions.some(alert=>alert.status==="已确认")?"已确认·待决定维护":"待复核",owner:"设备总管",due,overdue:expired(due),condition:"记录复核结论；需要维修时创建维护需求",action:"查看设备证据",deviceId:device.equipment_id});
 }
 if(!technicianId)for(const alert of alerts){
  if(alert.dataset_version!==version||alert.status!=="已延期"||!expired(alert.defer_until))continue;
  const device=devices.find(item=>item.equipment_id===alert.equipment_id);
  if(!device||device.prediction_at===alert.prediction_at)continue;
  tasks.push({id:`deferred:${alert.alert_id}`,alertId:alert.alert_id,deviceId:alert.equipment_id,equipment:`${alert.equipment_id} · ${device.equipment_name}`,category:"预警复核",status:"历史延期复核到期",owner:"设备总管",due:alert.defer_until||"",overdue:true,condition:"核对原预警记录并填写复核意见；维修需求需依据当前设备证据",action:"处理到期复核"});
 }
 const transitions:Record<string,{category:string;owner:string;condition:string;action:string}>={
  "草稿·待排程":{category:"需求排程",owner:"设备总管",condition:"补齐约束并生成排程草案",action:"核对并排程"},
  "待审批":{category:"待审批",owner:"设备总管",condition:"核对硬约束，批准或退回",action:"核对审批"},
  "已退回":{category:"需求排程",owner:"设备总管",condition:"按退回意见修改需求并重新排程",action:"修改需求"},
  "已驳回":{category:"需求排程",owner:"设备总管",condition:"按退回意见修改需求并重新排程",action:"修改需求"},
  "已批准":{category:"执行任务",owner:"维修人员",condition:"被分配人员确认接单",action:"查看工单"},
  "已接单":{category:"执行任务",owner:"维修人员",condition:"实际开始维修时记录开工",action:"记录开工"},
  "执行中":{category:"执行任务",owner:"维修人员",condition:"记录结果、实际工时和费用并提交完工",action:"继续执行"},
  "已暂停":{category:"执行任务",owner:"维修人员",condition:"确认可继续后恢复维修",action:"处理暂停"},
  "待验收":{category:"待验收",owner:"设备总管",condition:"核对维修结果及实际耗用，验收或返修",action:"核对验收"}
 };
 for(const order of orders){
  const step=transitions[order.status];if(!step)continue;
  if(technicianId&&(!(order.staff_ids||[order.staff_id]).includes(technicianId)||!["已批准","已接单","执行中","已暂停"].includes(order.status)))continue;
  const due=order.latest_finish_at||order.end_at||"";
  tasks.push({id:order.work_order_id,workOrderId:order.work_order_id,equipment:order.equipment_id,category:step.category,status:order.status,owner:step.owner==="维修人员"?order.staff_name||order.staff_ids?.join("、")||order.staff_id||"待指定人员":step.owner,due,overdue:expired(due),condition:step.condition,action:step.action,oldVersion:order.dataset_version!==version});
 }
 return tasks.sort((a,b)=>Number(b.overdue)-Number(a.overdue)||(a.due&&b.due?new Date(a.due).getTime()-new Date(b.due).getTime():a.due?-1:b.due?1:0));
}

/** Shared management queues are explicit; execution belongs to assigned staff only. */
export function personalTasks(devices:TaskDevice[],orders:TaskOrder[],alerts:TaskAlert[],version:string,now:number,user:{role:string;staff_id?:string}):OperationalTask[]{
 if(user.role==="viewer")return [];
 if(user.role==="technician")return operationalTasks(devices,orders,alerts,version,now,user.staff_id||"unassigned-account");
 if(!["admin","manager"].includes(user.role))return [];
 return operationalTasks(devices,orders,alerts,version,now).filter(task=>["预警复核","待审批","待验收","需求排程"].includes(task.category));
}

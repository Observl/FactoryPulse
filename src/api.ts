/** Shared failure handling. Mutations are never retried automatically. */
const labels:Record<string,string>={username:"账号",display_name:"人员姓名",password:"密码",current_password:"当前密码",new_password:"新密码",role:"账号角色",active:"账号状态",on_hand:"实盘库存",actual_parts:"实际备件耗用",prediction_at:"预测时间",defer_until:"下次复核时间",equipment_id:"设备编号",staff_name:"人员姓名",skills:"技能",available_hours:"可用工时",shift_start:"班次开始",shift_end:"班次结束",start_at:"开始时间",end_at:"结束时间",due_at:"订单交期",window_start:"最早停机时间",window_end:"最晚恢复时间",maintenance_hours:"维修工时",maintenance_cost_cny:"维修费用",required_skill:"所需技能",required_staff_count:"参与人数",maintenance_budget_cny:"维修预算",available_staff_count:"可用人数",max_downtime_h:"累计停机工时",risk_threshold:"提醒分数线",actor:"操作人员",approver:"审批人员",note:"处理说明",actual_hours:"实际工时",actual_cost_cny:"实际费用",priority:"优先级",part_name:"备件名称",quantity:"需要数量",available_quantity:"可用库存",scenario_name:"排程条件名称",order_name:"订单名称",request_id:"操作编号",version:"记录版本"};
type ValidationIssue={loc?:Array<string|number>;type?:string;msg?:string;ctx?:Record<string,unknown>};
function issueMessage(issue:ValidationIssue):string{
 const field=issue.loc?.filter(part=>typeof part==="string"&&!['body','query','path'].includes(part)).at(-1);
 const label=typeof field==="string"?(labels[field]||"输入项"):"输入项";
 const ctx=issue.ctx||{};let message=issue.msg?.replace(/^Value error, /,"")||"请检查输入";
 if(issue.type==="missing")message="需要填写";
 else if(issue.type==="string_too_short")message=`至少填写 ${ctx.min_length??1} 个字符`;
 else if(issue.type==="string_too_long")message=`不能超过 ${ctx.max_length} 个字符`;
 else if(issue.type==="greater_than")message=`必须大于 ${ctx.gt}`;
 else if(issue.type==="greater_than_equal")message=`不能小于 ${ctx.ge}`;
 else if(issue.type==="less_than_equal")message=`不能大于 ${ctx.le}`;
 else if(issue.type==="finite_number")message="必须是有效的有限数值";
 else if(issue.type?.startsWith("datetime"))message="请填写有效的日期和时间";
 else if(issue.type?.startsWith("int"))message="请填写整数";
 else if(issue.type?.startsWith("float"))message="请填写有效数值";
 return `${label}：${message}`;
}

export function responseError(body:unknown,status:number):string{
 const detail=body&&typeof body==="object"&&"detail" in body?(body as {detail:unknown}).detail:undefined;
 if(typeof detail==="string")return detail;
 if(Array.isArray(detail))return detail.slice(0,3).map(item=>issueMessage(item as ValidationIssue)).join("；")+(detail.length>3?`；另有 ${detail.length-3} 项需要修改`:"");
 if(status===409)return "记录已被更新，请刷新后核对，再重新操作。";
 if(status===401)return "会话已过期，请重新登录。";
 if(status===403)return "当前账号没有执行此操作的权限。";
 if(status===404)return "这条记录已不存在，请刷新后重新选择。";
 if(status>=500)return "数据服务暂时无法完成操作，请稍后重试；提交操作前先核对记录是否已更新。";
 return "操作未完成，请检查填写内容后重试。";
}

export class ApiError extends Error{
 constructor(message:string,public status:number){super(message);this.name="ApiError"}
}

export async function apiRequest(path:string,options:RequestInit={},timeoutMs?:number){
 const write=!!options.method&&options.method.toUpperCase()!=="GET";
 const controller=new AbortController();let timedOut=false;
 const cancel=()=>controller.abort();
 if(options.signal?.aborted)controller.abort();
 options.signal?.addEventListener("abort",cancel,{once:true});
 const timer=window.setTimeout(()=>{timedOut=true;controller.abort()},timeoutMs??(write?90000:30000));
 try{
  const response=await fetch("/api"+path,{...options,cache:options.cache||"no-store",signal:controller.signal});
  let body:unknown;
  try{body=await response.json()}catch{throw new ApiError(write?"服务没有返回可识别的结果。操作可能已提交，请先刷新记录确认。":"服务没有返回有效数据，请确认后端服务正在运行。",response.status)}
  if(response.status===401&&!path.startsWith("/auth/")&&typeof window.dispatchEvent==="function")window.dispatchEvent(new CustomEvent("factorypulse:auth-expired"));
  if(!response.ok)throw new ApiError(responseError(body,response.status),response.status);
  return body as any;
 }catch(error){
  if(error instanceof ApiError)throw error;
  if(timedOut)throw new ApiError(write?"等待超时，操作可能仍在处理中。请先刷新记录确认，避免重复提交。":"读取超时，请稍后刷新。",0);
  if(controller.signal.aborted)throw error;
  throw new ApiError(write?"连接中断，无法确认操作结果。请先刷新记录再决定是否重试。":"无法连接数据服务，请确认后端服务已启动。",0);
 }finally{window.clearTimeout(timer);options.signal?.removeEventListener("abort",cancel)}
}

export function errorMessage(error:unknown){return error instanceof Error?error.message:String(error)}

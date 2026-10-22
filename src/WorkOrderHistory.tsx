export type OrderEvent={at:string;actor:string;from:string;to:string;note:string};
export function displayTime(value?:string){
 if(!value)return "时间未提供";
 const date=new Date(value);
 return Number.isNaN(date.getTime())?value:date.toLocaleString("zh-CN",{hour12:false});
}
export function WorkOrderHistory({events,createdAt,source}:{events:OrderEvent[];createdAt?:string;source?:string}){
 return <ol className="work-order-events" aria-label="工单处理记录">
  {createdAt&&<li><div className="event-marker" aria-hidden="true"/><div className="event-content"><strong>维护需求已创建</strong><time dateTime={createdAt}>{displayTime(createdAt)}</time><p>{source?`来源预警：${source}`:"人工维护需求"}</p></div></li>}
  {events.map((event,index)=><li key={event.at+index}><div className="event-marker" aria-hidden="true"/><div className="event-content"><div className="event-transition"><span>{event.from}</span><span aria-hidden="true">→</span><strong>{event.to}</strong></div><div className="event-metadata"><time dateTime={event.at}>{displayTime(event.at)}</time><span>{event.actor||"操作人未记录"}</span></div>{event.note&&<p>{event.note}</p>}</div></li>)}
  {!events.length&&!createdAt&&<li><p className="quiet-note">暂无处理记录</p></li>}
 </ol>;
}

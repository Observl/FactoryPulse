export function ChartEventLegend({faults=0,maintenance=0,threshold}:{faults?:number;maintenance?:number;threshold?:string}){
 return <div className="chart-event-legend" aria-label="图表标记说明">
  {faults>0&&<span><i className="chart-fault-dot"/>故障标记 · {faults} 处</span>}
  {maintenance>0&&<span><i className="chart-maintenance-dot"/>维修记录 · {maintenance} 处</span>}
  {threshold&&<span><i className="chart-threshold-line"/>{threshold}</span>}
 </div>;
}
export function faultMarkers(series:{time:number;signal?:number|null;risk?:number|null}[],intervals:{start:number;end:number}[]){
 if(!series.length)return [];
 const low=series[0].time,high=series[series.length-1].time;
 return intervals.filter(event=>event.end>=low&&event.start<=high).map(event=>{
  const time=Math.max(low,Math.min(high,event.start));
  const point=series.reduce((near,next)=>Math.abs(next.time-time)<Math.abs(near.time-time)?next:near);
  return {...event,time:point.time,signal:point.signal,risk:point.risk};
 });
}

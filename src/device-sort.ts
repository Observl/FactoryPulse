import {deviceState} from "./device-state";
export type SortKey='equipment_id'|'equipment_name'|'production_line'|'equipment_type'|'status'|'risk_score'|'timestamp'|'temperature'|'speed';
type Row={equipment_id:string;equipment_name?:string;production_line?:string;equipment_type?:string;status?:string;review_required?:boolean;risk_score?:number;risk_available?:boolean;latest_reading?:{failure?:number;timestamp?:string;process_temperature_k?:number;rotational_speed_rpm?:number}};
export function sortDevices<T extends Row>(rows:T[],key:SortKey,direction:'asc'|'desc'):T[]{
 const value=(row:T):string|number|null=>{
  if(key==='status')return ({unknown:0,offline:1,normal:2,warning:3,fault:4} as Record<string,number>)[deviceState(row).kind];
  const raw=key==='timestamp'?row.latest_reading?.timestamp:key==='temperature'?row.latest_reading?.process_temperature_k:key==='speed'?row.latest_reading?.rotational_speed_rpm:key==='risk_score'&&row.risk_available===false?null:row[key as keyof Row];
  if(raw==null||raw==='')return null;
  if(key==='timestamp'){const time=Date.parse(String(raw));return Number.isFinite(time)?time:null}
  return typeof raw==='number'?Number.isFinite(raw)?raw:null:String(raw);
 };
 return [...rows].sort((a,b)=>{const x=value(a),y=value(b);if(x==null&&y!=null)return 1;if(y==null&&x!=null)return -1;const compared=x==null&&y==null?0:typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y),'zh-CN',{numeric:true});return compared*(direction==='asc'?1:-1)||a.equipment_id.localeCompare(b.equipment_id,'zh-CN',{numeric:true})});
}

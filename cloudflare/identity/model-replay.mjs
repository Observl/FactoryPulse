// Read the same frozen prediction evidence used by the Python implementation.
export function eventTimeline(series,faults,maintenance){
 const result=[],bounds=new Map(),prior=new Map();
 for(const point of [...series].sort((a,b)=>String(a.timestamp).localeCompare(String(b.timestamp)))){
  const id=String(point.equipment_id),stamp=point.timestamp;if(!stamp)continue;
  if(!bounds.has(id))bounds.set(id,[stamp,stamp]);else bounds.get(id)[1]=stamp;
  if(point.alert&&!prior.get(id))result.push({equipment_id:id,timestamp:stamp,kind:'alert',title:'模型达到提醒分数线',detail:point.observed_future_failure===1?'事后核验：故障前提醒':point.observed_future_failure===0?'事后核验：误报窗口':'后续观测不足，无法核验',reading_id:point.reading_id,score:point.score});
  prior.set(id,Boolean(point.alert));
 }
 for(const event of faults)result.push({equipment_id:event.equipment_id,timestamp:event.failure_at,kind:'failure',title:'故障标记开始',detail:event.detected?'事后核验：已提前提醒':'事后核验：漏报',lead_hours:event.lead_hours,first_alert_at:event.first_alert_at});
 for(const row of maintenance){const range=bounds.get(String(row.equipment_id)),stamp=row.maintenance_date||row.verified_at;if(!range||!stamp)continue;const time=Date.parse(stamp);if(!Number.isFinite(time)||time<Date.parse(range[0])||time>Date.parse(range[1]))continue;result.push({equipment_id:String(row.equipment_id),timestamp:String(stamp),kind:'maintenance',title:row.maintenance_type||'历史维修记录',detail:'原始记录，不据此推断维修因果收益',maintenance_id:row.maintenance_id,source:row.data_origin})}
 return result.sort((a,b)=>String(a.timestamp).localeCompare(String(b.timestamp)));
}
export async function modelReplay(db,version,normalized=false){
 const row=await db.prepare('SELECT run_id,dataset_version,model_version,content FROM prediction_runs WHERE dataset_version=? ORDER BY created_at DESC,run_id DESC LIMIT 1').bind(version).first();
 if(!row)return {status:'unavailable',series:[],events:[],timeline:[],evaluation:{},message:'当前数据版本没有可回放的模型证据'};
 const content=JSON.parse(row.content),summary=content.summary||{},series=content.replay||[],evaluation=summary.evaluation||{},events=evaluation.events||[];
 const bounds=new Map();for(const point of series){const value=Date.parse(point.timestamp);if(!Number.isFinite(value))continue;const key=String(point.equipment_id),old=bounds.get(key);bounds.set(key,{equipment_id:key,start_at:Math.min(old?.start_at??value,value),end_at:Math.max(old?.end_at??value,value)})}
 let maintenance=[];
 if(bounds.size){
  const ranges=JSON.stringify([...bounds.values()].map(x=>({...x,start_at:new Date(x.start_at).toISOString(),end_at:new Date(x.end_at).toISOString()})));
  const cte="WITH bounds AS (SELECT json_extract(value,'$.equipment_id') AS equipment_id,json_extract(value,'$.start_at') AS start_at,json_extract(value,'$.end_at') AS end_at FROM json_each(?)) ";
  let sql;
  if(normalized){
   const emitted="COALESCE(strftime('%Y-%m-%d %H:%M:%S',m.maintenance_date,'+8 hours'),json_extract(m.attributes,'$.verified_at'))";
   sql=cte+"SELECT json_patch(m.attributes,json_object('maintenance_id',m.maintenance_id,'equipment_id',m.equipment_id,'maintenance_type',m.maintenance_type,'failure_at',strftime('%Y-%m-%d %H:%M:%S',m.failure_at,'+8 hours'),'failure_end',strftime('%Y-%m-%d %H:%M:%S',m.failure_end,'+8 hours'),'maintenance_date',strftime('%Y-%m-%d %H:%M:%S',m.maintenance_date,'+8 hours'),'data_origin',m.data_origin,'downtime_hours',COALESCE(m.observed_downtime_h,(julianday(m.failure_end)-julianday(m.failure_at))*24.0))) AS content FROM bounds b JOIN maintenance_history m ON m.equipment_id=b.equipment_id WHERE julianday("+emitted+") BETWEEN julianday(b.start_at) AND julianday(b.end_at) ORDER BY m.equipment_id,m.maintenance_date,m.maintenance_id";
  }else sql=cte+"SELECT r.content FROM bounds b JOIN records r ON r.table_name='maintenance_history' AND json_extract(r.content,'$.equipment_id')=b.equipment_id WHERE julianday(COALESCE(json_extract(r.content,'$.maintenance_date'),json_extract(r.content,'$.verified_at'))) BETWEEN julianday(b.start_at) AND julianday(b.end_at) ORDER BY r.row_index";
  maintenance=(await db.prepare(sql).bind(ranges).all()).results.map(x=>JSON.parse(x.content));
 }

 return {status:summary.xgboost,model_version:row.model_version,training_rows:summary.training_rows||0,positive_labels:summary.positive_labels||0,evaluation,message:summary.message||'',run_id:row.run_id,dataset_version:row.dataset_version,series,events,timeline:eventTimeline(series,events,maintenance),replay_basis:'冻结模型的时间外测试回放；非现场实时预警，非滚动重训；故障、维修与核验结论仅供事后复盘'};
}

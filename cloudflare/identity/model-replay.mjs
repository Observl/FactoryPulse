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
export async function modelReplay(db,version){
 const row=await db.prepare('SELECT run_id,dataset_version,model_version,content FROM prediction_runs WHERE dataset_version=? ORDER BY created_at DESC LIMIT 1').bind(version).first();
 if(!row)return {status:'unavailable',series:[],events:[],timeline:[],evaluation:{},message:'当前数据版本没有可回放的模型证据'};
 const content=JSON.parse(row.content),summary=content.summary||{},series=content.replay||[],evaluation=summary.evaluation||{},events=evaluation.events||[];
 const maintenance=(await db.prepare("SELECT content FROM records WHERE table_name='maintenance_history' ORDER BY row_index").all()).results.map(x=>JSON.parse(x.content));
 return {status:summary.xgboost,model_version:row.model_version,training_rows:summary.training_rows||0,positive_labels:summary.positive_labels||0,evaluation,message:summary.message||'',run_id:row.run_id,dataset_version:row.dataset_version,series,events,timeline:eventTimeline(series,events,maintenance),replay_basis:'冻结模型的时间外测试回放；非现场实时预警，非滚动重训；故障、维修与核验结论仅供事后复盘'};
}

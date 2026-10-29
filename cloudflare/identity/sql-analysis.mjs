// Authenticated, parameterized SQL reports. The caller authenticates every request.
import {qualityQuery} from './quality-query.mjs';
import {businessStatistics} from './statistics.mjs';
const json=(value,status=200)=>Response.json(value,{status,headers:{'Cache-Control':'no-store'}});
const rows=async(db,sql,params=[])=>(await db.prepare(sql).bind(...params).all()).results;
const timestamp=value=>{if(!value)return null;const t=Date.parse(/[Zz]|[+-]\d{2}:\d{2}$/.test(value)?value:value.replace(' ','T')+'+08:00');if(!Number.isFinite(t))throw new Error('请输入有效时间');return new Date(t).toISOString()};

export async function sqlRead(request,env,user){
 if(String(env.BUSINESS_SCHEMA_VERSION)!=='2'||request.method!=='GET')return null;
 const db=env.BUSINESS_DB,url=new URL(request.url),path=url.pathname,p=url.searchParams;
 if(!db||!(['/api/data-quality','/api/data/summary','/api/overview','/api/resources/inventory'].includes(path)||path.startsWith('/api/analysis/')))return null;
 try{
  if(path==='/api/data-quality'){
   const packed=await db.prepare(qualityQuery).first(),value=JSON.parse(packed.report);
   const fieldCoverage=[...new Set(JSON.parse(packed.fields).flatMap(x=>x?JSON.parse(x):[]))];
   const quality_status=value.reading_count===0?'没有可用采样，无法完成质量判断':value.missing_rate!==null&&value.missing_rate<0.05&&value.duplicate_readings===0&&value.invalid_timestamps===0&&value.abnormal_values===0&&value.future_timestamps===0?'基础校验通过，需核对现场适用性':'需补充或修复数据';
   return json({...value,quality_status,freshness:value.future_timestamps>0?'future_timestamp':value.data_age_hours>24?'historical':'recent_or_unknown',field_coverage:fieldCoverage,equipment_quality:JSON.parse(packed.equipment_quality),metric_statistics:JSON.parse(packed.metric_statistics),sampling_baselines:JSON.parse(packed.sampling_baselines),sampling_gaps:JSON.parse(packed.gaps),
    missing_rate_scope:'指标值缺失率；主键和时间有效性单独检查',gap_method:'SQL 按设备正采样间隔中位数推断，超过3倍标为待复核间断；不是采集SLA',computed_by:'cloudflare_d1_sql',computed_at:new Date().toISOString()});
  }
  if(path==='/api/data/summary')return json((await businessStatistics(env)).source);
  if(path==='/api/resources/inventory')return json({records:await rows(db,'SELECT *,MAX(0,-balance_after_reservations) AS shortfall FROM v_current_spare_part_availability ORDER BY part_name'),meaning:'SQL：实盘库存扣除有效预留'});
  if(path==='/api/overview'){
   const limit=Number(p.get('limit')||500);if(!Number.isInteger(limit)||limit<1||limit>2000)return json({detail:'limit须在1到2000之间'},400);
   const artifact=await db.prepare("SELECT content FROM fp_v_processed_results WHERE view_key='overview'").first();
   const base=artifact?JSON.parse(artifact.content):{};
   const all=await rows(db,'SELECT content,score,equipment_id FROM v_dashboard_devices ORDER BY equipment_id');
   const devices=all.slice(0,limit);
   const {counts,source}=await businessStatistics(env);
   const scored=all.filter(r=>r.score!==null),average=scored.reduce((sum,r)=>sum+r.score,0)/scored.length;
   const metrics={total:all.length,high:scored.filter(r=>r.score>0.35).length,warning:scored.filter(r=>r.score>=0.15&&r.score<=0.35).length,unknown:all.length-scored.length,avg_risk:scored.length?Math.round(average*1000)/1000:null};
   const top=[...all].sort((a,b)=>(a.score===null)-(b.score===null)||(b.score??0)-(a.score??0)||a.equipment_id.localeCompare(b.equipment_id)).slice(0,100);
   return json({...base,devices:devices.map(r=>JSON.parse(r.content)),all_devices:all.map(r=>JSON.parse(r.content)),computed_at:new Date().toISOString(),top_risk_devices:top.map(r=>JSON.parse(r.content)),counts,metrics,
    analytics:base.analytics||{xgboost:'unavailable',shap:'unavailable',message:'当前输入尚无匹配的模型计算证据；仅展示有依据的规则参考'},
    sync:{...base.sync,...source,database:'cloudflare-d1://'+env.BUSINESS_DATABASE_ID},returned_devices:devices.length,storage_provider:'cloudflare_d1',schema_version:2});
  }
  const limit=Number(p.get('limit')||100);if(!Number.isInteger(limit)||limit<1||limit>500)return json({detail:'limit须在1到500之间'},400);
  const id=p.get('equipment_id'),start=timestamp(p.get('start_at')),end=timestamp(p.get('end_at'));
  if(start&&end&&start>=end)return json({detail:'结束时间必须晚于开始时间'},400);
  if(path==='/api/analysis/equipment'){
   const filters=[],params=[];if(start){filters.push('s.timestamp>=?');params.push(start)}if(end){filters.push('s.timestamp<?');params.push(end)}
   const where=id?'WHERE e.equipment_id=?':'';if(id)params.push(id);params.push(limit);
   const records=await rows(db,`SELECT e.equipment_id,e.equipment_name,e.equipment_type,e.data_origin,COUNT(s.reading_id) AS reading_count,
    MIN(s.timestamp) AS first_sample_at,MAX(s.timestamp) AS latest_sample_at,AVG(s.vibration_mm_s) AS average_vibration_mm_s,
    MAX(s.vibration_mm_s) AS maximum_vibration_mm_s,AVG(s.motor_current_a) AS average_motor_current_a,
    MAX(s.oil_temperature_c) AS maximum_oil_temperature_c
    FROM equipment e LEFT JOIN sensor_readings s ON e.equipment_id=s.equipment_id ${filters.length?'AND '+filters.join(' AND '):''}
    ${where} GROUP BY e.equipment_id ORDER BY e.equipment_id LIMIT ?`,params);
   return json({records,scope:{equipment_id:id,start_at:start,end_at:end},limit,computed_by:'cloudflare_d1_sql',note:'聚合监测事实，不据此确认故障原因；结束时间不包含在范围内'});
  }
  if(path==='/api/analysis/quality'){
   if(start||end)return json({detail:'此质量视图覆盖当前全部采样；不支持时间筛选，不能将全量结果冒充指定时间范围'},400);
   const qualityRequest=new Request(new URL('/api/data-quality',url));
   let quality;
   if(env.BUSINESS_RESULTS){
    const stub=env.BUSINESS_RESULTS.get(env.BUSINESS_RESULTS.idFromName(env.BUSINESS_DATABASE_ID+'|shared|/api/data-quality'));
    const {revisions,dependencies}=await import('./data-sync.mjs');const all=await revisions(env),vector=Object.fromEntries(['__source__',...dependencies('/api/data-quality')].map(key=>[key,all[key]||0]));
    const response=await stub.fetch('https://results.internal/',{method:'POST',body:JSON.stringify({url:qualityRequest.url,user,vector})});if(!response.ok)throw new Error('质量快照暂不可用');quality=await response.json();
   }else{const response=await sqlRead(qualityRequest,env,user);if(!response.ok)throw new Error('质量计算暂不可用');quality=await response.json()}
   return json({records:quality.equipment_quality.filter(row=>!id||row.equipment_id===id).sort((a,b)=>a.equipment_id.localeCompare(b.equipment_id)).slice(0,limit),limit,computed_by:'cloudflare_d1_sql',computed_at:quality.computed_at});
  }
  if(path==='/api/analysis/work-orders'){
   const filters=['w.deleted_at IS NULL'],params=[];
   if(id){filters.push('w.equipment_id=?');params.push(id)}
   if(start){filters.push('julianday(w.planned_end_at)>julianday(?)');params.push(start)}
   if(end){filters.push('julianday(w.planned_start_at)<julianday(?)');params.push(end)}
   if(user.role==='user'){filters.push('EXISTS(SELECT 1 FROM v_work_order_assignments a WHERE a.work_order_id=w.work_order_id AND a.staff_id=?)');params.push(String(user.staff_id))}
   const where='WHERE '+filters.join(' AND ');
   const records=await rows(db,'SELECT w.* FROM v_work_order_schedule w '+where+' ORDER BY w.updated_at DESC LIMIT ?',[...params,limit]);
   const statistics=await rows(db,'SELECT w.status,COUNT(*) AS work_order_count FROM v_work_order_schedule w '+where+' GROUP BY w.status',params);
   return json({records,statistics,scope:{equipment_id:id,start_at:start,end_at:end},limit,computed_by:'cloudflare_d1_sql'});
  }
  if(path==='/api/analysis/conflicts'){
   if(!['developer','admin'].includes(user.role))return json({detail:'跨工单资源冲突需要管理权限'},403);
   return json({work_order_conflicts:await rows(db,'SELECT * FROM v_work_order_conflicts LIMIT ?',[limit]),production_conflicts:await rows(db,'SELECT * FROM v_production_maintenance_conflicts LIMIT ?',[limit]),computed_by:'cloudflare_d1_sql'});
  }
  return json({detail:'未知只读分析接口'},404);
 }catch(error){if(error.message==='请输入有效时间')return json({detail:error.message},400);throw error}
}

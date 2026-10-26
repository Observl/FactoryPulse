// Authenticated, parameterized SQL reports. The caller authenticates every request.
const qualitySQL=`SELECT *,CASE WHEN reading_count=0 THEN '没有可用采样，无法完成质量判断'
WHEN missing_rate<0.05 AND duplicate_readings=0 AND invalid_timestamps=0 AND abnormal_values=0 AND future_timestamps=0
THEN '基础校验通过，需核对现场适用性' ELSE '需补充或修复数据' END AS quality_status,
CASE WHEN future_timestamps>0 THEN 'future_timestamp' WHEN data_age_hours>24 THEN 'historical' ELSE 'recent_or_unknown' END AS freshness FROM v_quality_report`;
const json=(value,status=200)=>Response.json(value,{status,headers:{'Cache-Control':'no-store'}});
const rows=async(db,sql,params=[])=>(await db.prepare(sql).bind(...params).all()).results;
const fields=async db=>[...new Set((await rows(db,"SELECT DISTINCT json_extract(attributes,'$._feature_fields') AS fields FROM sensor_readings")).flatMap(x=>x.fields?JSON.parse(x.fields):[]))];
const timestamp=value=>{if(!value)return null;const t=Date.parse(/[Zz]|[+-]\d{2}:\d{2}$/.test(value)?value:value.replace(' ','T')+'+08:00');if(!Number.isFinite(t))throw new Error('请输入有效时间');return new Date(t).toISOString()};

export async function sqlRead(request,env,user){
 if(String(env.BUSINESS_SCHEMA_VERSION)!=='2'||request.method!=='GET')return null;
 const db=env.BUSINESS_DB,url=new URL(request.url),path=url.pathname,p=url.searchParams;
 if(!db||!(['/api/data-quality','/api/data/summary','/api/overview','/api/resources/inventory'].includes(path)||path.startsWith('/api/analysis/')))return null;
 try{
  if(path==='/api/data-quality'){
   const value=await db.prepare(qualitySQL).first();
   return json({...value,field_coverage:await fields(db),sampling_gaps:await rows(db,'SELECT * FROM v_sampling_interruptions ORDER BY equipment_id,start_at LIMIT 100'),
    missing_rate_scope:'指标值缺失率；主键和时间有效性单独检查',gap_method:'SQL 按设备正采样间隔中位数推断，超过3倍标为待复核间断；不是采集SLA',computed_by:'cloudflare_d1_sql'});
  }
  if(path==='/api/data/summary')return json(await db.prepare('SELECT * FROM fp_v_data_source').first());
  if(path==='/api/resources/inventory')return json({records:await rows(db,'SELECT *,MAX(0,-balance_after_reservations) AS shortfall FROM v_current_spare_part_availability ORDER BY part_name'),meaning:'SQL：实盘库存扣除有效预留'});
  if(path==='/api/overview'){
   const limit=Number(p.get('limit')||500);if(!Number.isInteger(limit)||limit<1||limit>2000)return json({detail:'limit须在1到2000之间'},400);
   const artifact=await db.prepare("SELECT content FROM fp_v_processed_results WHERE view_key='overview'").first();
   const base=artifact?JSON.parse(artifact.content):{};
   const devices=await rows(db,'SELECT content FROM v_dashboard_devices ORDER BY equipment_id LIMIT ?',[limit]);
   const counts=Object.fromEntries((await rows(db,'SELECT table_name,record_count FROM fp_v_record_counts')).map(r=>[r.table_name,r.record_count]));
   const metrics=await db.prepare('SELECT COUNT(*) AS total,SUM(score>0.35) AS high,SUM(score>=0.15 AND score<=0.35) AS warning,SUM(score IS NULL) AS unknown,ROUND(AVG(score),3) AS avg_risk FROM v_dashboard_devices').first();
   const top=await rows(db,'SELECT content FROM v_dashboard_devices ORDER BY score IS NULL,score DESC,equipment_id LIMIT 100');
   const source=await db.prepare('SELECT * FROM fp_v_data_source').first();
   return json({...base,devices:devices.map(r=>JSON.parse(r.content)),top_risk_devices:top.map(r=>JSON.parse(r.content)),counts,metrics,
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
   return json({records:await rows(db,'SELECT * FROM v_equipment_data_quality '+(id?'WHERE equipment_id=? ':'')+'ORDER BY equipment_id LIMIT ?',id?[id,limit]:[limit]),limit,computed_by:'cloudflare_d1_sql'});
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

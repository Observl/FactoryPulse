/** Shared counts are invalidated by resource revisions, not by a clock. */
export async function businessStatistics(env){
 if(env.BUSINESS_RESULTS){const stub=env.BUSINESS_RESULTS.get(env.BUSINESS_RESULTS.idFromName('statistics:'+env.BUSINESS_DATABASE_ID));const response=await stub.fetch('https://results.internal/',{method:'POST',body:JSON.stringify({operation:'statistics'})});if(!response.ok)throw new Error('统计快照暂不可用');const result=await response.json();if(!result.stable)throw new Error('统计期间数据发生变化，请重新更新');return result}
 const db=env.BUSINESS_DB;
 // Compatible deployments without the durable binding still count only once per response.
 const counts=Object.fromEntries((await db.prepare('SELECT table_name,record_count FROM fp_v_record_counts').all()).results.map(x=>[x.table_name,x.record_count]));
 const settings=Object.fromEntries((await db.prepare("SELECT key,value FROM business_settings WHERE key IN ('last_sync_at','source_name','source_date')").all()).results.map(x=>[x.key,x.value]));
 return {counts,source:{dataset_version:settings.last_sync_at,source_name:settings.source_name,source_date:settings.source_date,record_count:counts.readings,device_count:counts.equipment}};
}

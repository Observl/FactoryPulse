import {modelReplay} from './model-replay.mjs';
// Cloudflare-only persistence. Raw SQL and database credentials are never public APIs.
import {workOrders} from './work-orders.mjs';
import {businessStatistics} from './statistics.mjs';
export async function business(request,env,user){
 const db=env.BUSINESS_DB,url=new URL(request.url),path=url.pathname;
 const reply=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'}});
 if(!db)return reply({detail:'业务 D1 尚未绑定'},503);
 const work=await workOrders(request,env,user);if(work)return work;
 const settings=Object.fromEntries((await db.prepare('SELECT key,value FROM '+(String(env.BUSINESS_SCHEMA_VERSION)==='2'?'business_settings':'settings')).all()).results.map(r=>[r.key,r.value]));
 const version=settings.last_sync_at;
 if(!version)return reply({detail:'测试集尚未完成云端校验'},503);
 const view=async key=>{const row=await db.prepare('SELECT content FROM fp_computed_views WHERE dataset_id=? AND view_key=?').bind(version,key).first();return row?JSON.parse(row.content):null};
 const records=async name=>(await db.prepare('SELECT content FROM records WHERE table_name=? ORDER BY row_index').bind(name).all()).results.map(r=>JSON.parse(r.content));
 if(request.method==='GET'){
  if(path==='/api/model/replay')return reply(await modelReplay(db,version,String(env.BUSINESS_SCHEMA_VERSION)==='2'));
  if(path==='/api/overview'){
   const result=await view('overview');if(!result)return reply({detail:'云端模型证据尚未计算完成'},503);
   const states=(await db.prepare('SELECT * FROM alerts WHERE dataset_version=? ORDER BY updated_at').bind(version).all()).results;
   const byId=new Map(states.map(r=>[r.equipment_id,r]));
   result.devices=result.devices.map(d=>({...d,alert_status:byId.get(d.equipment_id)?.status??d.alert_status,alert_note:byId.get(d.equipment_id)?.note??d.alert_note}));
   result.sync.database='cloudflare-d1://'+env.BUSINESS_DATABASE_ID;
   result.storage_provider='cloudflare_d1';return reply(result);
  }
  const table=/^\/api\/records\/([a-z_]+)$/.exec(path);
  if(table){
   if(!['equipment','readings','maintenance_rules','maintenance_history','staff','orders','scenarios','demo_risks'].includes(table[1]))return reply({detail:'Unknown table'},404);
   const limit=Number(url.searchParams.get('limit')||500);if(!Number.isInteger(limit)||limit<1||limit>25000)return reply({detail:'limit须在1到25000之间'},400);
   const rows=await db.prepare('SELECT content FROM records WHERE table_name=? ORDER BY row_index LIMIT ?').bind(table[1],limit).all();
   const total=String(env.BUSINESS_SCHEMA_VERSION)==='2'?(await businessStatistics(env)).counts[table[1]]:(await db.prepare('SELECT COUNT(*) AS n FROM records WHERE table_name=?').bind(table[1]).first()).n;return reply({records:rows.results.map(r=>JSON.parse(r.content)),total});
  }
  if(path==='/api/sync/status'){const overview=await view('overview');return reply({...overview?.sync,database:'cloudflare-d1://'+env.BUSINESS_DATABASE_ID})}
  if(path==='/api/data-quality'){const result=await view('data-quality');return result?reply(result):reply({detail:'数据质量计算尚未完成'},503)}
  const history=/^\/api\/equipment\/([^/]+)\/history$/.exec(path);
  if(history){const id=decodeURIComponent(history[1]),value=await view('history/'+id);if(!value)return reply({detail:'设备不存在'},404);const added=(await db.prepare('SELECT content FROM maintenance_events WHERE equipment_id=? AND dataset_version=?').bind(id,version).all()).results.map(x=>JSON.parse(x.content));const ids=new Set(added.map(x=>x.work_order_id));value.maintenance=[...added,...(value.maintenance||[]).filter(x=>!ids.has(x.work_order_id))];return reply(value)}
  if(path==='/api/work-orders'){
   const rows=(await db.prepare('SELECT * FROM work_orders ORDER BY updated_at DESC').all()).results;
   return reply({records:rows.map(r=>({...JSON.parse(r.content),status:r.status,updated_at:r.updated_at})).filter(r=>!r.deleted_at&&(!url.searchParams.has('dataset_version')||r.dataset_version===url.searchParams.get('dataset_version')))});
  }
  if(path==='/api/alerts'){
   const filters=[],params=[];for(const key of ['dataset_version','equipment_id','status'])if(url.searchParams.has(key)){filters.push(key+'=?');params.push(url.searchParams.get(key))}
   const limit=Number(url.searchParams.get('limit')||500);if(!Number.isInteger(limit)||limit<1||limit>5000)return reply({detail:'limit须在1到5000之间'},400);
   // Keep existing full-list clients compatible; clients opting into limit receive bounded results.
   const sql='SELECT * FROM alerts'+(filters.length?' WHERE '+filters.join(' AND '):'')+' ORDER BY updated_at DESC,alert_id DESC'+(url.searchParams.has('limit')?' LIMIT ?':'');if(url.searchParams.has('limit'))params.push(limit);
   return reply({records:(await db.prepare(sql).bind(...params).all()).results});
  }
  if(path==='/api/audit')return reply({records:(await db.prepare('SELECT * FROM audit_events ORDER BY event_id DESC LIMIT 200').all()).results.map(r=>({...r,content:JSON.parse(r.content)}))});
  if(path==='/api/data/versions')return reply({current_version:version,records:(await db.prepare('SELECT * FROM dataset_versions ORDER BY archived_at DESC LIMIT 100').all()).results.map(r=>({...JSON.parse(r.metadata),version:r.version,archived_at:r.archived_at}))});
  if(path==='/api/model/evaluation'){const data=await view('overview'),s=data?.analytics||{};return reply({status:s.xgboost,model_version:s.model_version,training_rows:s.training_rows||0,positive_labels:s.positive_labels||0,evaluation:s.evaluation||{},message:s.message||''})}
  if(path==='/api/backups/status')return reply({status:'cloudflare_managed',provider:'cloudflare_d1',local_database:false,message:'数据在 Cloudflare D1；请在 Cloudflare 控制台管理 Time Travel 与导出。'});
  const resource=/^\/api\/resources\/(staff|orders|scenarios|requirements)$/.exec(path);
  if(resource)return reply({records:await records(resource[1]==='requirements'?'maintenance_rules':resource[1])});
 }
 // Do not silently substitute an approximate algorithm for the Python solver.
 return reply({detail:'此业务接口尚未迁移到 Workers；本地计算服务可使用同一 D1 完成此操作。'},501);
}

// Account authentication must run before this read-only cache protocol.
const inputs=['records/equipment','records/readings','records/demo_risks','records/maintenance_rules','records/maintenance_history','records/orders','settings/dataset'];
const snapshots=new Map();
const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value))))).map(x=>x.toString(16).padStart(2,'0')).join('');
export function dependencies(path){
 if(path==='/api/model/replay')return [...inputs,'computed','prediction_runs'];
 if(path==='/api/overview')return [...inputs,'computed','alerts'];
 if(['/api/data-quality','/api/data/summary','/api/sync/status','/api/model/evaluation','/api/model/replay'].includes(path))return [...inputs,'computed'];
 if(path==='/api/work-orders')return ['work_orders','settings/dataset'];
 if(/^\/api\/work-orders\/[^/]+\/flow$/.test(path))return ['work_orders','audit_events','maintenance_events','inventory_stock','inventory_reservations','settings/dataset'];
 if(path==='/api/alerts')return ['alerts','settings/dataset'];
 if(path==='/api/data/versions')return ['dataset_versions','settings/dataset'];
 if(path==='/api/audit')return ['audit_events'];
 const table=/^\/api\/records\/([a-z_]+)$/.exec(path);if(table)return ['records/'+table[1]];
 if(/^\/api\/equipment\/[^/]+\/(history|operations)$/.test(path))return [...inputs,'computed','maintenance_events','work_orders'];
 if(path==='/api/resources/inventory')return ['inventory_stock','inventory_reservations','settings/dataset'];
 const resource=/^\/api\/resources\/(staff|orders|scenarios|requirements)$/.exec(path);if(resource)return ['records/'+(resource[1]==='requirements'?'maintenance_rules':resource[1]),'work_orders','settings/business'];
 if(['/api/maintenance/timeline','/api/maintenance/time-readiness','/api/operations/resource-occupancy'].includes(path))return [...inputs,'records/staff','records/scenarios','work_orders','inventory_stock','inventory_reservations','settings/business'];
 return null;
}
export function delta(old,next,path=[]){
 if(JSON.stringify(old)===JSON.stringify(next))return [];
 if(old&&next&&typeof old==='object'&&typeof next==='object'&&Array.isArray(old)===Array.isArray(next)){
  if(Array.isArray(old))return [...next.slice(0,old.length).flatMap((v,i)=>delta(old[i],v,[...path,i])),...Array.from({length:Math.max(0,old.length-next.length)},(_,i)=>({op:'remove',path:[...path,old.length-i-1]})),...next.slice(old.length).map((v,i)=>({op:'set',path:[...path,old.length+i],value:v}))];
  return [...Object.keys(old).filter(k=>!Object.hasOwn(next,k)).map(k=>({op:'remove',path:[...path,k]})),...Object.entries(next).flatMap(([k,v])=>Object.hasOwn(old,k)?delta(old[k],v,[...path,k]):[{op:'set',path:[...path,k],value:v}])];
 }
 return [{op:'set',path,value:next}];
}
async function revisions(env){
 const rows=(await env.BUSINESS_DB.prepare("SELECT resource,revision FROM fp_resource_revisions UNION ALL SELECT '__source__',value FROM settings WHERE key='last_sync_at'").all()).results;
 const result=Object.fromEntries(rows.map(r=>[r.resource,r.revision]));
 result.__source__=parseInt((await hash([env.BUSINESS_DATABASE_ID,result.__source__||''])).slice(0,13),16);
 return result;
}
export async function syncedRead(request,env,user,handler){
 const url=new URL(request.url),metadata=url.pathname==='/api/data/revisions',keys=dependencies(url.pathname);
 if(request.method!=='GET'||(!metadata&&!keys))return handler();
 const all=await revisions(env),identity=`${user.user_id}:${user.version}:${user.role}`;
 const vector=metadata?all:Object.fromEntries(['__source__',...keys].map(k=>[k,all[k]||0]));
 const tag='"'+(await hash([identity,url.pathname+url.search,vector])).slice(0,32)+'"';
 const headers={'ETag':tag,'X-FP-Revisions':JSON.stringify(vector),'Cache-Control':'private, no-cache','Content-Type':'application/json; charset=utf-8'};
 if(request.headers.get('If-None-Match')===tag)return new Response(null,{status:304,headers});
 if(metadata)return new Response(JSON.stringify({schema:1,identity,resources:all}),{headers});
 const response=await handler();if(!response||response.status!==200)return response;
 const content=await response.text(),after=await revisions(env);
 if(Object.keys(vector).some(k=>(after[k]||0)!==vector[k]))return new Response(content,{status:200,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 const value=JSON.parse(content),key=identity+'|'+url.pathname+url.search,previous=snapshots.get(key)||[],base=request.headers.get('X-FP-Delta-Base'),old=previous.find(x=>x.tag===base);
 let body=content;
 if(old){const patch=JSON.stringify({format:'fp-delta-v1',base,patch:delta(old.value,value)});if(patch.length<content.length*.85){body=patch;headers['X-FP-Delta']='1'}}
 if(content.length<1000000){snapshots.delete(key);snapshots.set(key,[...previous.slice(-1),{tag,value}]);while(snapshots.size>24)snapshots.delete(snapshots.keys().next().value)}
 return new Response(body,{headers});
}

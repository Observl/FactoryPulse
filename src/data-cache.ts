/** Processed API results only. No credentials, auth decisions or write requests are cached. */
export type ReadResult={data:any;status:number;etag?:string;revisions?:Record<string,number>;delta?:boolean};
type Entry={path:string;data:any;etag?:string;revisions?:Record<string,number>;saved:number};
type Loader=(path:string,headers?:Record<string,string>)=>Promise<ReadResult>;
type Listener=(path:string,data:any)=>void;
const allowed=/^\/(?:overview|data-quality|data\/summary|data\/versions|sync\/status|model\/(?:evaluation|replay)|work-orders(?:\/[^/]+\/flow)?|alerts|audit|maintenance\/(?:timeline|time-readiness)|operations\/resource-occupancy|records\/[a-z_]+|equipment\/[^/]+\/(?:history|operations)|resources\/(?:staff|orders|scenarios|requirements|inventory))(?:\?|$)/;
const unsafe=new Set(['__proto__','prototype','constructor']);
const identity=(value:any)=>value&&typeof value==='object'?['work_order_id','alert_id','reading_id','event_id','plan_id','maintenance_id','equipment_id','staff_id','order_id','scenario_id','version','id'].find(key=>value[key]!==undefined):undefined;
export function shareData(old:any,next:any):any{
 if(Object.is(old,next))return old;
 if(!old||!next||typeof old!=='object'||typeof next!=='object'||Array.isArray(old)!==Array.isArray(next))return next;
 if(Array.isArray(next)){
  const key=identity(next[0]),byId=key?new Map(old.map((item:any)=>[item?.[key],item])):null;
  const result=next.map((value:any,i:number)=>shareData(byId?.get(value?.[key!])??old[i],value));
  return old.length===result.length&&result.every((v:any,i:number)=>v===old[i])?old:result;
 }
 const result:Record<string,any>={};let same=Object.keys(old).length===Object.keys(next).length;
 for(const key of Object.keys(next)){if(unsafe.has(key))continue;result[key]=shareData(old[key],next[key]);same&&=result[key]===old[key]&&Object.prototype.hasOwnProperty.call(old,key)}
 return same?old:result;
}
export function applyDelta(base:any,operations:{op:string;path:(string|number)[];value?:any}[]){
 if(!Array.isArray(operations)||operations.length>50000)throw new Error('无效的增量响应');
 let result=base;
 for(const operation of operations){
  if(!['set','remove'].includes(operation.op)||!Array.isArray(operation.path)||operation.path.some(k=>unsafe.has(String(k))))throw new Error('无效的增量路径');
  const update=(node:any,depth:number):any=>{
   if(depth===operation.path.length)return operation.value;
   const key=operation.path[depth];if(!node||typeof node!=='object')throw new Error('增量基线不匹配');
   const copy=Array.isArray(node)?node.slice():{...node};
   if(depth===operation.path.length-1&&operation.op==='remove'){
    if(Array.isArray(copy)){if(!Number.isInteger(key)||Number(key)<0||Number(key)>=copy.length)throw new Error('无效数组路径');copy.splice(Number(key),1)}else delete copy[key];
   }else copy[key]=update(node[key],depth+1);
   return copy;
  };result=update(result,0);
 }
 return shareData(base,result);
}

class PersistentResults{
 private db:Promise<IDBDatabase|null>|null=null;
 private open(){return this.db??=new Promise<IDBDatabase|null>(resolve=>{if(typeof indexedDB==='undefined'){resolve(null);return}const request=indexedDB.open('factorypulse-processed-v2',1);request.onupgradeneeded=()=>request.result.createObjectStore('results',{keyPath:'key'});request.onsuccess=()=>resolve(request.result);request.onerror=()=>resolve(null);request.onblocked=()=>resolve(null)})}
 async read(scope:string):Promise<Entry[]>{try{const db=await this.open();if(!db)return [];return await new Promise(resolve=>{const request=db.transaction('results').objectStore('results').getAll();request.onsuccess=()=>resolve(request.result.filter(r=>r.scope===scope&&r.entry.saved>Date.now()-86400000).map(r=>r.entry));request.onerror=()=>resolve([])})}catch{return []}}
 async write(scope:string,entry:Entry){try{if(JSON.stringify(entry).length>2000000)return;const db=await this.open();if(!db)return;await new Promise<void>(resolve=>{const tx=db.transaction('results','readwrite');tx.objectStore('results').put({key:scope+'|'+entry.path,scope,entry});tx.oncomplete=tx.onerror=tx.onabort=()=>resolve()})}catch{/* Memory cache continues if browser storage is full or disabled. */}}
 async clear(){try{const db=await this.open();if(db)await new Promise<void>(resolve=>{const tx=db.transaction('results','readwrite');tx.objectStore('results').clear();tx.oncomplete=tx.onerror=tx.onabort=()=>resolve()})}catch{}}
}

export class ProcessedCache{
 private scope='';private epoch=0;private entries=new Map<string,Entry>();private pending=new Map<string,Promise<any>>();private listeners=new Set<Listener>();
 private statuses=new Set<()=>void>();private persistence=new PersistentResults();private loader:Loader|null=null;private poll:ReturnType<typeof setInterval>|null=null;private checking:Promise<void>|null=null;private revisionsTag='';private resourceVersions:Record<string,number>={};private lastCheck=0;
 private status={enabled:false,checking:false,lastChecked:0,error:'',entries:0};
 subscribe=(listener:Listener)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener)}};
 subscribeStatus=(listener:()=>void)=>{this.statuses.add(listener);return()=>{this.statuses.delete(listener)}};
 getStatus=()=>this.status;
 private report(update:Partial<typeof this.status>){this.status={...this.status,...update};this.statuses.forEach(listener=>listener())}
 peek=(path:string)=>this.entries.get(path)?.data;
 async authorize(scope:string){
  if(this.scope===scope)return;
  const epoch=++this.epoch;this.scope=scope;this.entries.clear();this.pending.clear();this.revisionsTag='';this.lastCheck=0;
  const entries=await this.persistence.read(scope);if(epoch!==this.epoch)return;
  for(const entry of entries.slice(-60))if(allowed.test(entry.path))this.entries.set(entry.path,entry);
  this.report({enabled:true,entries:this.entries.size,error:''});
  if(!this.poll&&typeof window!=='undefined')this.poll=setInterval(()=>{if(typeof document==='undefined'||document.visibilityState!=='hidden')void this.check()},5000);
 }
 async clear(){++this.epoch;this.scope='';this.entries.clear();this.pending.clear();this.revisionsTag='';this.lastCheck=0;if(this.poll)clearInterval(this.poll);this.poll=null;this.report({enabled:false,entries:0,error:'',checking:false});await this.persistence.clear()}
 async request(path:string,options:RequestInit,loader:Loader){
  if(!this.scope||!allowed.test(path)||options.signal||options.cache==='no-store'||options.cache==='reload')return (await loader(path)).data;
  this.loader=loader;const cached=this.entries.get(path);
  if(cached){if(Date.now()-this.lastCheck>1000)void this.check();return cached.data}
  return this.refresh(path,loader);
 }
 private async refresh(path:string,loader:Loader,force=false){
  const key=this.scope+'|'+path;if(this.pending.has(key))return this.pending.get(key)!;
  const epoch=this.epoch,scope=this.scope,old=this.entries.get(path);
  const job=(async()=>{
   let response=await loader(path,!force&&old?.etag?{'If-None-Match':old.etag,'X-FP-Delta-Base':old.etag}:{});
   if(epoch!==this.epoch){if(scope!==this.scope)throw new DOMException('账号已切换','AbortError');return this.entries.get(path)?.data??response.data;}
   if(response.status===304){if(!old)throw new Error('缓存基线已过期');return old.data}
   let data=response.data;
   if(response.delta){try{if(!old||data?.format!=='fp-delta-v1'||data.base!==old.etag)throw new Error('增量版本不匹配');data=applyDelta(old.data,data.patch)}catch{response=await loader(path,{});if(response.delta||response.status===304)throw new Error('无法重建完整数据');data=response.data}}
   if(epoch!==this.epoch){if(scope!==this.scope)throw new DOMException('账号已切换','AbortError');return this.entries.get(path)?.data??data;}
   data=shareData(old?.data,data);
   // A response without an ETag was computed during a write; never persist that generation.
   if(!response.etag){if(old)return old.data;return data}
   const entry={path,data,etag:response.etag,revisions:response.revisions,saved:Date.now()};this.entries.set(path,entry);
   while(this.entries.size>60)this.entries.delete(this.entries.keys().next().value!);
   void this.persistence.write(scope,entry);this.report({entries:this.entries.size});
   if(data!==old?.data)this.listeners.forEach(listener=>listener(path,data));
   return data;
  })().finally(()=>{if(this.pending.get(key)===job)this.pending.delete(key)});this.pending.set(key,job);return job;
 }
 async check(force=false):Promise<void>{
  if(!this.scope||!this.loader)return;if(this.checking)return this.checking;
  const loader=this.loader,epoch=this.epoch;this.report({checking:true});
  const job=(async()=>{
   try{
    const result=await loader('/data/revisions',!force&&this.revisionsTag?{'If-None-Match':this.revisionsTag}:{});
    if(epoch!==this.epoch)return;
    if(result.status!==304){if(result.data?.schema!==1||!result.data.resources)throw new Error('数据版本服务尚未就绪');if(result.data.identity&&result.data.identity!==this.scope){await this.clear();if(typeof window.dispatchEvent==='function')window.dispatchEvent(new CustomEvent('factorypulse:auth-expired'));return}this.resourceVersions=result.data.resources;this.revisionsTag=result.etag||'';}
    {const resources=this.resourceVersions;
     // Only fetch resources whose dependency vector changed; unchanged entries retain identity.
     await Promise.all([...this.entries.values()].filter(entry=>!entry.revisions||Object.keys(entry.revisions).some(key=>(resources[key]||0)!==entry.revisions![key])).map(entry=>this.refresh(entry.path,loader)));
    }
    if(epoch===this.epoch){this.lastCheck=Date.now();this.report({lastChecked:this.lastCheck,error:''})}
   }catch(error){if(epoch===this.epoch)this.report({error:error instanceof Error?error.message:'更新检查失败'})}
   finally{if(epoch===this.epoch)this.report({checking:false})}
  })().finally(()=>{this.checking=null});this.checking=job;return job;
 }
 async afterWrite(){++this.epoch;this.pending.clear();this.revisionsTag='';this.lastCheck=0;if(this.checking)await this.checking;await this.check(true)}
}
export const processedCache=new ProcessedCache();

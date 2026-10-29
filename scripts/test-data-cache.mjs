import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/data-cache.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {ProcessedCache,applyDelta,shareData}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
globalThis.window={};
const before={devices:[{equipment_id:'E1',value:1},{equipment_id:'E2',value:2}],counts:{total:2}};
const after=applyDelta(before,[{op:'set',path:['devices',1,'value'],value:3}]);
assert.equal(after.devices[0],before.devices[0]);assert.equal(after.counts,before.counts);assert.notEqual(after.devices[1],before.devices[1]);assert.equal(before.devices[1].value,2);
assert.deepEqual(applyDelta({records:[1,2,3]},[{op:'remove',path:['records',2]},{op:'remove',path:['records',1]}]),{records:[1]});
assert.throws(()=>applyDelta({},[{op:'set',path:['__proto__','polluted'],value:true}]));
assert.equal(shareData(before,structuredClone(before)),before);
const reordered=shareData(before.devices,[before.devices[1],before.devices[0]]);assert.equal(reordered[0],before.devices[1]);

const cache=new ProcessedCache();let resources={work_orders:0,alerts:0},requests=[],responses={
 '/work-orders':{data:{records:[{work_order_id:'W1',status:'pending'},{work_order_id:'W2',status:'pending'}]},etag:'"w0"',revisions:{work_orders:0}},
 '/alerts':{data:{records:[]},etag:'"a0"',revisions:{alerts:0}}
};
let revisionTag=0,fail=false;
const load=async(path,headers={})=>{
 requests.push(path);if(fail)throw Error('network unavailable');
 if(path==='/data/revisions')return headers['If-None-Match']===String(revisionTag)?{status:304,data:null}:{status:200,data:{schema:1,resources},etag:String(revisionTag)};
 const value=responses[path];if(headers['If-None-Match']===value.etag)return {status:304,data:null};return {status:200,...value};
};
try{
 await cache.authorize('user-A:1:viewer');
 const work=await cache.request('/work-orders',{},load),alerts=await cache.request('/alerts',{},load);
 await cache.check(true);requests=[];
 await cache.afterWrite();assert.deepEqual(requests,[],'writes must not trigger reads');
 await new Promise(resolve=>setTimeout(resolve,20));assert.deepEqual(requests,[],'idle cache must not poll');
 assert.equal(await cache.request('/work-orders',{},load),work);assert.equal(requests.length,0,'unchanged navigation must reuse the exact cached result');
 resources={work_orders:1,alerts:0};revisionTag++;
 responses['/work-orders']={status:200,data:{format:'fp-delta-v1',base:'"w0"',patch:[{op:'set',path:['records',0,'status'],value:'approved'}]},delta:true,etag:'"w1"',revisions:{work_orders:1}};
 await cache.check(true);
 const changed=cache.peek('/work-orders');assert.equal(changed.records[0].status,'approved');assert.equal(changed.records[1],work.records[1]);assert.equal(cache.peek('/alerts'),alerts);
 assert.equal(requests.filter(x=>x==='/alerts').length,0,'unrelated resource must not refetch');
 requests=[];await cache.check();assert.deepEqual(requests,['/data/revisions']);
 fail=true;await cache.check(true);assert.equal(cache.peek('/work-orders'),changed);assert.match(cache.getStatus().error,/network/);
 fail=false;await cache.authorize('user-B:1:viewer');assert.equal(cache.peek('/work-orders'),undefined,'another account cannot see the previous account cache');
 await cache.clear();assert.equal(cache.getStatus().enabled,false);
 console.log('Cache checks passed: navigation reuse, 304, targeted delta, stable unchanged records, deletion, offline retention, account isolation and logout clearing.');
}finally{await cache.clear()}

// Returning users hydrate persisted JSON without a request, even after several days.
const disk=new Map([['persisted-user|/overview',{scope:'persisted-user',entry:{path:'/overview',data:{devices:[{equipment_id:'cached'}]},saved:Date.now()-7*86400000}}]]);
globalThis.indexedDB={open(){const request={result:{transaction(){const tx={objectStore(){return {getAll(){const r={};queueMicrotask(()=>{r.result=[...disk.values()];r.onsuccess?.()});return r},put(value){disk.set(value.key,value);queueMicrotask(()=>tx.oncomplete?.())},clear(){disk.clear();queueMicrotask(()=>tx.oncomplete?.())}}}};return tx}}};queueMicrotask(()=>request.onsuccess?.());return request}};
const persisted=new ProcessedCache();await persisted.authorize('persisted-user');
let persistedReads=0;
assert.equal((await persisted.request('/overview',{},async()=>{persistedReads++;throw Error('must remain offline')})).devices[0].equipment_id,'cached');
assert.equal(persistedReads,0);
let initialReads=0;const cold=new ProcessedCache();await cold.authorize('new-user');
const initialLoader=async()=>{initialReads++;return {status:200,data:{records:[1]}}};
await cold.request('/resources/staff',{},initialLoader);await cold.request('/resources/staff',{},initialLoader);
assert.equal(initialReads,1,'an uncached resource loads once and then stays local, including JSON without an ETag');
// Old releases persisted Dify readiness and optimistic versions. Reloading must
// discard those snapshots and saving must be followed by a fresh server read.
disk.set('dify-user|/copilot/dify/config',{scope:'dify-user',entry:{path:'/copilot/dify/config',data:{ready:false,version:0},saved:1}});
disk.set('dify-user|/copilot/dify/status',{scope:'dify-user',entry:{path:'/copilot/dify/status',data:{ready:false},saved:1}});
const difyCache=new ProcessedCache();await difyCache.authorize('dify-user');
assert.equal(difyCache.peek('/copilot/dify/config'),undefined);
assert.equal(difyCache.peek('/copilot/dify/status'),undefined);
let configVersion=0,difyReads=0;
const difyLoader=async()=>{difyReads++;return {status:200,data:{ready:configVersion>0,version:configVersion}}};
assert.equal((await difyCache.request('/copilot/dify/config',{},difyLoader)).ready,false);
configVersion=1;await difyCache.afterWrite();
assert.deepEqual(await difyCache.request('/copilot/dify/config',{},difyLoader),{ready:true,version:1});
assert.equal((await difyCache.request('/copilot/dify/status',{},difyLoader)).ready,true);
assert.equal(difyReads,3);assert.equal(difyCache.peek('/copilot/dify/config'),undefined);
console.log('Dify cache regression passed: stale persisted settings excluded, saved version and readiness read fresh.');
console.log('Persistent JSON checks passed: week-old offline cache and first-visit-only loading.');

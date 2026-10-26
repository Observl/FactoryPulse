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

// Unit tests with mocked transport only. No browser or network is used.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source=await readFile(new URL('../src/api.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {apiRequest,responseError}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
globalThis.window={setTimeout,clearTimeout};
let calls=0;

assert.equal(responseError({detail:[{loc:['body','available_hours'],type:'greater_than',ctx:{gt:0}}]},422),'可用工时：必须大于 0');
assert.equal(responseError({detail:[{loc:['body','shift_end'],type:'value_error',msg:'Value error, 班次结束必须晚于开始'}]},422),'班次结束：班次结束必须晚于开始');
globalThis.fetch=async()=>{calls++;throw new TypeError('network failed')};
await assert.rejects(apiRequest('/work-orders',{method:'POST'}),/无法确认操作结果/);
assert.equal(calls,1,'a failed mutation must never be retried automatically');

calls=0;
globalThis.fetch=async()=>{calls++;return {ok:false,status:502,json:async()=>{throw new SyntaxError('HTML response')}}};
await assert.rejects(apiRequest('/import/jobs/example/commit',{method:'POST'}),/操作可能已提交/);
assert.equal(calls,1);

globalThis.fetch=async(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true}));
await assert.rejects(apiRequest('/overview',{},1),/读取超时/);
globalThis.fetch=async()=>({ok:false,status:409,json:async()=>({detail:'记录版本已改变，请刷新'})});
await assert.rejects(apiRequest('/work-orders/example/approval',{method:'POST'}),/记录版本已改变/);
console.log('6 API failure-handling checks passed (mocked transport; no browser/network).');

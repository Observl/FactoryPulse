import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../src/WorkOrderPanel.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('panel.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const declarations={};
function visit(node){if(ts.isVariableDeclaration(node)&&ts.isIdentifier(node.name)&&['submit','reloadAfterConflict'].includes(node.name.text))declarations[node.name.text]='const '+node.getText(tree)+';';ts.forEachChild(node,visit)}visit(tree);
assert(declarations.submit&&declarations.reloadAfterConflict);
const code=ts.transpileModule(Object.values(declarations).join('\n')+'\nglobalThis.submitApproval=submit;globalThis.reloadApproval=reloadAfterConflict;',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
for(const refreshFails of [false,true]){
 const calls=[],state={};let first=true,refreshes=0;
 const context={JSON,unsaved:{clear(){}},flow:{record:{version:9}},actionVersion:{current:2},operationId:{current:'approval-stable-request'},busy:false,childBusy:false,mode:'approve',note:'核对通过',accept:true,id:'W1',auth:{user:{display_name:'设备总管'}},errorMessage:error=>error.message,
 apiRequest:async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});if(first){first=false;throw Error('返回结果时断线')}return {status:'已批准',version:3}},
 refresh:async()=>{refreshes++;if(refreshFails)throw Error('刷新失败')}};
 for(const key of ['Busy','Error','Message','Mode','Note'])context['set'+key]=value=>{state[key]=value;if(key==='Busy')context.busy=value};
 vm.createContext(context);vm.runInContext(code,context);
 await context.submitApproval();assert.equal(calls.length,1,'失败时不能自动重复写入');assert.equal(refreshes,0);
 await context.submitApproval();assert.equal(calls.length,2);assert.equal(refreshes,1);
 assert.equal(calls[0].body.version,2,'刷新不能把原审批意图换成新版本');
 assert.deepEqual(calls[0].body,calls[1].body);assert.equal(calls[1].body.request_id,'approval-stable-request');
 assert.equal(state.Mode,'');assert.equal(state.Busy,false);assert.match(state.Message,/已保存/);
 if(refreshFails)assert.match(state.Error,/操作已保存，刷新失败/);
}
for(const confirmed of [false,true]){
 const state={};let loads=0;
 const context={busy:false,childBusy:false,mode:'approve',note:'尚未提交',window:{confirm:()=>confirmed},confirmUnsavedNavigation:()=>true,
  load:async()=>{loads++},actionVersion:{current:2},operationId:{current:'old-operation'},crypto:{randomUUID:()=> 'new-operation'},errorMessage:error=>error.message};
 for(const key of ['Mode','Note','Accept','FormRevision','Error'])context['set'+key]=value=>{state[key]=typeof value==='function'?value(0):value};
 vm.createContext(context);vm.runInContext(code,context);await context.reloadApproval();
 assert.equal(loads,confirmed?1:0);
 assert.equal(context.actionVersion.current,confirmed?null:2);
 assert.equal(context.operationId.current,confirmed?'new-operation':'old-operation');
 if(confirmed){assert.equal(state.Mode,'');assert.equal(state.Note,'');assert.equal(state.FormRevision,1)}
}
console.log('4 approval client checks passed: lost response retry, fixed intent version, post-save refresh failure, and explicit refresh/discard; no browser.');

import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
const source=fs.readFileSync(new URL('../src/EquipmentManager.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('manager.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const names=['refreshAfterWrite','act','schedule','approve'];const declarations=[];
function visit(node){if(ts.isVariableDeclaration(node)&&ts.isIdentifier(node.name)&&names.includes(node.name.text))declarations.push('const '+node.getText(tree)+';');ts.forEachChild(node,visit)}visit(tree);
assert.equal(declarations.length,4);
const compiled=ts.transpileModule(declarations.join('\n')+'\nglobalThis.functions={act,schedule,approve};',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
for(const operation of ['act','schedule','approve'])for(const failure of ['refresh','write']){
 const state={review:'open',approval:'open'},calls=[];
 const context={Promise,JSON,unsaved:{clear(){}},crypto:{randomUUID:()=> 'test-request'},handled:[],dataVersion:'v1',note:'复核',deferUntil:'',scenarioId:'S1',approver:'主管',acknowledged:true,alertRequest:{current:{signature:'',id:''}},errorMessage:error=>error.message,
 request:async path=>{calls.push(path);if(failure==='write')throw Error('写入拒绝');return {status:'已保存',work_order_id:'W1',scheduled:[{}],conflicts:[]}},
 load:async()=>{throw Error('连接中断')},onChanged:async()=>{throw Error('概要不可用')}};
 for(const key of ['Busy','Message','Error','Review','Note','OrderFilter','OrderQuery','Conflicts','Approval','BoardFocus','Area'])context['set'+key]=value=>{state[key[0].toLowerCase()+key.slice(1)]=value};
 vm.createContext(context);vm.runInContext(compiled,context);
 if(operation==='act')await context.functions.act({equipment_id:'E1',prediction_at:'2026-10-20'},'work_order');
 if(operation==='schedule')await context.functions.schedule();
 if(operation==='approve')await context.functions.approve({work_order_id:'W1',version:1},'approve');
 assert.equal(calls.length,1,'不得因刷新失败重试写入');assert.equal(state.busy,false);
 if(failure==='refresh'){assert.match(state.message,/已/);assert.match(state.error,/操作已保存/);assert.doesNotMatch(state.error,/处理失败|生成失败|审批失败/);if(operation==='act'){assert.equal(state.review,null);assert.equal(state.orderQuery,'W1')}if(operation==='approve')assert.equal(state.approval,null)}
 else{assert.match(state.error,/失败/);assert.equal(state.message,'');if(operation==='act')assert.equal(state.review,'open');if(operation==='approve')assert.equal(state.approval,'open')}
}
console.log('6 mutation outcome regressions passed: write rejection and post-save refresh failure; no browser/network.');

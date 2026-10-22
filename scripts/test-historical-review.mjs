import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
const source=fs.readFileSync(new URL('../src/HistoricalAlertReview.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('historical.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let declaration;
function visit(node){if(ts.isVariableDeclaration(node)&&node.name.getText(tree)==='save')declaration=node.getText(tree);ts.forEachChild(node,visit)}visit(tree);
assert.ok(declaration);
const compiled=ts.transpileModule('const '+declaration+';globalThis.save=save;', {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function setup(){
 const state={calls:[],closed:0,refreshes:0,busy:false,error:'',saved:false,cleared:0};
 const context={record:{alert_id:'A1',equipment_id:'E1',prediction_at:'old',dataset_version:'v1',version:2},action:'confirm',note:'已核对',until:'',operation:{current:{signature:'',id:''}},pending:{current:false},savedReceipt:{current:false},crypto:{randomUUID:()=> 'request-'+state.calls.length},JSON,Date,encodeURIComponent,
  apiRequest:async(path,options)=>{state.calls.push(JSON.parse(options.body));if(state.writeFailure)throw Error('响应中断')},onSaved:async()=>{state.refreshes++;if(state.refreshFailure)throw Error('刷新中断')},onClose:()=>state.closed++,unsaved:{clear:()=>state.cleared++},errorMessage:error=>error.message,setBusy:value=>state.busy=value,setError:value=>state.error=value,setSaved:value=>state.saved=value};
 vm.createContext(context);vm.runInContext(compiled,context);return {context,state};
}
{
 const {context,state}=setup();state.refreshFailure=true;await context.save();
 assert.equal(state.saved,true);assert.equal(state.cleared,1);assert.match(state.error,/复核已保存/);assert.equal(state.closed,0);
 state.refreshFailure=false;await context.save();assert.equal(state.calls.length,1);assert.equal(state.closed,1);
}
{
 const {context,state}=setup();state.writeFailure=true;await context.save();await context.save();
 assert.equal(state.saved,false);assert.equal(state.cleared,0);assert.equal(state.calls[0].request_id,state.calls[1].request_id);assert.equal(state.busy,false);
 context.note='修正后的意见';await context.save();assert.notEqual(state.calls[1].request_id,state.calls[2].request_id);
}
{
 const {context,state}=setup();let release;context.apiRequest=async()=>{state.calls.push({});await new Promise(resolve=>release=resolve)};
 const first=context.save();await context.save();assert.equal(state.calls.length,1);release();await first;assert.equal(state.busy,false);
}
console.log('3 historical review regressions passed: refresh retry, stable intent and duplicate submission; no browser/network.');

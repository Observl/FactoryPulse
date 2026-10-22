import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('../src/useExclusiveOperation.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source.replace(/^import .*;\s*$/gm,'').replace('export function','function')+'\nglobalThis.createOperation=useExclusiveOperation;', {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const target=new EventTarget();let next=0,allowed=true;const cleanup=[];
const context={CustomEvent,window:target,confirmUnsavedNavigation:()=>allowed,
 useId:()=>String(++next),useRef:value=>({current:value}),useEffect:fn=>cleanup.push(fn())};
vm.createContext(context);vm.runInContext(compiled,context);
let first=0,second=0;
const openFirst=context.createOperation(()=>first++),openSecond=context.createOperation(()=>second++);
assert.equal(openFirst(),true);assert.equal(first,0);assert.equal(second,1);
assert.equal(openSecond(),true);assert.equal(first,1);assert.equal(second,1);
allowed=false;assert.equal(openFirst(),false);assert.equal(first,1);assert.equal(second,1);
cleanup.forEach(fn=>fn());allowed=true;openFirst();assert.equal(second,1);
console.log('4 operation ownership checks passed: peer dismissal, ownership change, unsaved refusal, listener cleanup.');

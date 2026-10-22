import {writeFile} from 'node:fs/promises';
const proxy='http://localhost:3456';
async function call(path,body){const r=await fetch(proxy+path,body===undefined?{}:{method:'POST',body});return r.json()}
const {targetId:id}=await call('/new','http://127.0.0.1:8024/');
const ev=async code=>{const r=await call('/eval?target='+id,code);if(r.error)throw Error(JSON.stringify(r));return r.value};
const wait=async code=>{for(let i=0;i<60;i++){if(await ev(code))return;await new Promise(r=>setTimeout(r,200))}throw Error('UI timeout: '+code)};
try{
const login=await ev(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'acceptance-admin',password:'temporary-acceptance-password-2026'})}).then(r=>r.status)`);if(login!==200)throw Error('QA login '+login);
await call('/navigate?target='+id,'http://127.0.0.1:8024/?view='+encodeURIComponent('个人中心'));
await wait(`!!document.querySelector('.personal-task-entry')`);
const result=await ev(`({duplicateMenuRemoved:!document.querySelector('.workspace-nav'),duplicateUserRemoved:!document.querySelector('.workspace-user'),personalTableRemoved:!document.querySelector('table[aria-label="我的待办"]'),entryButton:!!document.querySelector('.personal-task-entry button'),sourceButton:document.querySelector('.workspace-source')?.tagName==='BUTTON',overflow:document.documentElement.scrollWidth>innerWidth})`);
await ev(`document.querySelector('.personal-task-entry button').click()`);await wait(`document.querySelector('main h1')?.textContent==='我的待办'`);await wait(`!!document.querySelector('table[aria-label="我的待办"]')`);
result.taskNavigation=await ev(`new URLSearchParams(location.search).get('view')==='我的待办'&&!document.querySelector('.user-profile')`);
await ev(`document.querySelector('.workspace-source').click()`);await wait(`document.querySelector('main h1')?.textContent==='数据中心'`);result.dataNavigation=true;
if(Object.entries(result).some(([k,v])=>k==='overflow'?v:!v))throw Error(JSON.stringify(result));
await writeFile('outputs/navigation-qa/browser-report.json',JSON.stringify(result,null,2));console.log(result);
}finally{await call('/close?target='+id)}

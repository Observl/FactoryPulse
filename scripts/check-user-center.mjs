import {writeFile} from 'node:fs/promises';
const proxy='http://localhost:3456';
async function call(path,body){const r=await fetch(proxy+path,body===undefined?{}:{method:'POST',body});return r.json()}
const {targetId:id}=await call('/new','http://127.0.0.1:8024/');
const ev=async code=>{const r=await call('/eval?target='+id,code);if(r.error)throw Error(JSON.stringify(r));return r.value};
try{
const login=await ev(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'acceptance-admin',password:'temporary-acceptance-password-2026'})}).then(r=>r.status)`);if(login!==200)throw Error('QA login '+login);
await call('/navigate?target='+id,'http://127.0.0.1:8024/?view='+encodeURIComponent('个人中心'));
let state;for(let i=0;i<30;i++){state=await ev(`({title:document.querySelector('main h1')?.textContent,profile:!!document.querySelector('.user-profile'),text:document.body.innerText})`);if(state.profile)break;await new Promise(r=>setTimeout(r,300))}if(!state.profile)throw Error(JSON.stringify(state));
let checks=await ev(`(()=>{const button=[...document.querySelectorAll('.user-center button')].find(b=>b.textContent==='修改密码');button.click();const details=document.querySelector('.user-center .security-panel');details.open=true;return {heading:document.querySelector('main h1').textContent,accountInfo:!!document.querySelector('.profile-fields'),passwordForm:!!document.querySelector('form[aria-label="修改自己的密码"]'),createAccount:document.querySelector('.user-center').textContent.includes('新增账号'),logout:[...document.querySelectorAll('.user-center button')].some(b=>b.textContent.includes('退出登录')),overflow:document.documentElement.scrollWidth>innerWidth}})()`);
checks={...checks,...await ev(`({passwordForm:!!document.querySelector('form[aria-label="修改自己的密码"]')})`)};if(!checks.passwordForm)throw Error('Password form did not open');
await writeFile('outputs/user-center-qa/browser-report.json',JSON.stringify(checks,null,2));console.log(checks);
}finally{await call('/close?target='+id)}

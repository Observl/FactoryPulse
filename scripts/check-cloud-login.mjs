import {writeFile} from 'node:fs/promises';
const base=process.env.CLOUD_QA_URL||'http://127.0.0.1:8025/FactoryPulse',out='outputs/cloud-login-qa';
const target=await fetch('http://127.0.0.1:9226/json/new?'+encodeURIComponent(base),{method:'PUT'}).then(r=>r.json());const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let seq=0;const pending=new Map(),errors=[];
ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)}if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)});
const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq,timer=setTimeout(()=>reject(Error(method+' timeout')),20000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}))});
const ev=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(`Boolean(${expression})`))return;await new Promise(r=>setTimeout(r,200))}throw Error('Not ready '+expression)};
const navigate=async view=>{await send('Page.navigate',{url:base+'/?view='+encodeURIComponent(view)});await wait(`document.querySelector('main h1')?.textContent===${JSON.stringify(view==='设备总览'?'设备台账':view)}`)};
const capture=async name=>{const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(out+'/'+name+'.png',Buffer.from(r.data,'base64'))};

const click=label=>ev(`(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===${JSON.stringify(label)});if(!b)throw Error('Missing button');b.click()})()`);
const fill=async(account,password)=>ev(`(()=>{const inputs=document.querySelectorAll('form input');for(const [i,value] of ${JSON.stringify([account,password])}.entries()){Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(inputs[i],value);inputs[i].dispatchEvent(new Event('input',{bubbles:true}))}})()`);
const submit=()=>ev(`document.querySelector('form').requestSubmit()`);
try{
 await send('Page.enable');await send('Runtime.enable');await send('Emulation.setDeviceMetricsOverride',{width:1100,height:900,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:base+'/'});await wait(`document.querySelector('.cloud-login')`);await ev('sessionStorage.clear()');await send('Page.reload');await wait(`document.querySelector('.cloud-login')`);
 await click('只读用户 · 一键进入');await wait(`document.querySelector('.cloud-session-bar')`);await wait(`document.querySelector('table tbody tr')`);
 const report={viewer:await ev(`document.querySelector('.cloud-session-bar').textContent.includes('只读访客')&&!document.body.textContent.includes('导出验收报告')`)};
 await send('Page.reload');await wait(`document.querySelector('.cloud-session-bar')`);report.refreshPreservesViewer=true;
 await click('退出登录');await wait(`document.querySelector('.cloud-login')`);
 await fill('test','wrong-password');await submit();await wait(`document.querySelector('[role=alert]')`);report.wrongPasswordRefused=await ev(`!document.querySelector('.cloud-session-bar')`);
 await fill('test','testprojects');await submit();await wait(`document.querySelector('.cloud-session-bar')`);await wait(`document.querySelector('table tbody tr')`);
 report.admin=await ev(`document.querySelector('.cloud-session-bar').textContent.includes('线上测试员')&&[...document.querySelectorAll('button')].some(b=>b.textContent==='导出验收报告'&&!b.disabled)`);
 report.noPasswordStored=await ev(`!JSON.stringify(sessionStorage).includes('testprojects')`);await capture('admin');
 await click('退出登录');await wait(`document.querySelector('.cloud-login')`);await fill('线上测试员','testprojects');await submit();await wait(`document.querySelector('.cloud-session-bar')`);report.displayNameLogin=true;await click('退出登录');await wait(`document.querySelector('.cloud-login')`);
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});report.mobileNoOverflow=await ev(`document.documentElement.scrollWidth<=innerWidth`);await capture('mobile-login');
 await send('Page.navigate',{url:'http://127.0.0.1:5173/'});await wait(`document.querySelector('.auth-frame')`);report.localHasNoGuest=await ev(`!document.querySelector('.cloud-login')&&!document.body.textContent.includes('一键进入')`);
 report.errors=errors;await writeFile(out+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));if(Object.values(report).some(v=>v===false)||errors.length)throw Error('Login QA failed');
}finally{await send('Browser.close').catch(()=>{});ws.close()}

// Real Chromium rendering through the project's Electron runtime; no business writes.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const output=path.resolve(__dirname,'../outputs/ui-workflow-20261021');
fs.mkdirSync(output,{recursive:true});
let window;
const checks=[];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const evaluate=async code=>{try{return await window.webContents.executeJavaScript(code,true)}catch(error){throw Error(error.message+'\nExpression: '+code.slice(0,500))}};
async function waitFor(code){for(let i=0;i<100;i++){if(await evaluate(code))return;await sleep(150)}throw Error('UI wait failed: '+code)}
async function visit(view){await window.loadURL('http://127.0.0.1:5173/?view='+encodeURIComponent(view));await waitFor('!!document.querySelector("main.main")')}
async function clickText(text,scope='document'){
 const result=await evaluate(`(()=>{const root=${scope};const button=[...root.querySelectorAll('button')].find(b=>b.textContent.trim()===${JSON.stringify(text)});if(!button||button.disabled)return false;button.click();return true})()`);
 assert(result,`Missing enabled button: ${text}`);await sleep(150);
}
async function screenshot(name){await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');await sleep(350);fs.writeFileSync(path.join(output,name+'.png'),(await window.webContents.capturePage()).toPNG())}
async function run(){
 window=new BrowserWindow({show:false,width:565,height:825,useContentSize:true,webPreferences:{contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
 const errors=[];window.webContents.on('console-message',(_event,level,message)=>{if(level===3)errors.push(message)});
 await visit('执行审批');
 await waitFor('!!document.querySelector(".maintenance-queues")');
 await evaluate(`(()=>{const b=[...document.querySelectorAll('.maintenance-queues button')].find(b=>b.textContent.includes('工单处理'));b.click()})()`);
 await waitFor('!!document.querySelector(".board-controls select") && !document.querySelector(".board-controls select").disabled');
 await waitFor('document.querySelectorAll(".board-controls select option").length>1');
 const current=await evaluate('document.querySelector(".board-controls select").value');
 await evaluate(`(()=>{const select=document.querySelector('.board-controls select');select.value=[...select.options].find(o=>o.value!==select.value).value;select.dispatchEvent(new Event('change',{bubbles:true}))})()`);
 await waitFor('!!document.querySelector(".board-controls label:nth-child(2) select:disabled")');
 await waitFor('!!document.querySelector(".maintenance-board>.quiet-note")');
 assert.equal(await evaluate('document.querySelectorAll(".board-controls select").length'),2);
 await evaluate('document.querySelector(".board-controls").scrollIntoView({block:"center"})');
 checks.push('历史版本仍显示数据版本与只读排程条件');await screenshot('historical-schedule-mobile');
 await evaluate(`(()=>{const select=document.querySelector('.board-controls select');select.value=${JSON.stringify(current)};select.dispatchEvent(new Event('change',{bubbles:true}))})()`);
 await waitFor('!!document.querySelector(".board-controls label:nth-child(2) select:not(:disabled)")');

 // Controlled read fixtures exercise both action families, without creating a real work order.
 await evaluate(`(()=>{const original=window.fetch;window.fetch=async(input,options)=>{
  const url=String(input);if(url.includes('/api/work-orders/UI-AUDIT/flow'))return new Response(JSON.stringify({record:{work_order_id:'UI-AUDIT',equipment_id:'CNC-003',status:'待审批',version:1,dataset_version:${JSON.stringify(current)},created_at:'2026-10-21T08:00:00',start_at:'2026-10-21T10:00:00',end_at:'2026-10-21T15:00:00',hours:5,cost:2200,execution_history:[{at:'2026-10-21T09:45:00',actor:'设备总管',from:'草稿·待排程',to:'待审批',note:'自动约束排程生成'}]},owner:'设备总管',next_step:'核对人员和时间后审批',events:[]}),{headers:{'Content-Type':'application/json'}});
  return original(input,options)};
 const button=document.querySelector('.actionable-order-row button');if(!button)throw Error('No existing row to open');
 const realFetch=window.fetch;window.fetch=async(input,options)=>String(input).includes('/api/work-orders/')&&String(input).endsWith('/flow')?realFetch('/api/work-orders/UI-AUDIT/flow',options):realFetch(input,options);button.click()})()`);
 await waitFor('!!document.querySelector("dialog[open] .order-management")');
 await clickText('取消待审批工单','document.querySelector("dialog[open]")');
 assert.equal(await evaluate('document.querySelectorAll("dialog[open] .operation-form").length'),1);
 await clickText('撤回到待排程','document.querySelector("dialog[open]")');
 assert.equal(await evaluate('document.querySelectorAll("dialog[open] .operation-form").length'),1);
 assert.match(await evaluate('document.querySelector("dialog[open] .operation-form").textContent'),/撤回操作/);
 await evaluate('document.querySelector("dialog[open]").scrollTop=document.querySelector("dialog[open] .operation-form").offsetTop-100');
 await screenshot('single-operation-mobile');
 await clickText('取消待审批工单','document.querySelector("dialog[open]")');
 assert.equal(await evaluate('document.querySelectorAll("dialog[open] .operation-form").length'),1);
 await clickText('取消','document.querySelector("dialog[open] .operation-form")');
 assert.equal(await evaluate('document.querySelectorAll("dialog[open] .operation-form").length'),0);
 assert.equal(await evaluate('document.querySelectorAll("dialog[open] .work-order-events").length'),1);
 checks.push('取消与撤回表单互斥、取消关闭、处理记录唯一');
 await evaluate('document.querySelector(".order-event-log").scrollIntoView({block:"center"})');await screenshot('work-order-history-mobile');
 await clickText('关闭','document.querySelector("dialog[open]")');
 await clickText('资源配置');
 await waitFor('!!document.querySelector(".resource-list button")');
 await evaluate('document.querySelector(".resource-list button").click()');
 await clickText('创建人工维护需求');
 assert.equal(await evaluate('document.querySelectorAll(".resource-layout form").length'),0);
 assert.equal(await evaluate('document.querySelectorAll(".resource-editor .operation-form").length'),1);
 await clickText('取消','document.querySelector(".resource-editor .operation-form")');
 assert.equal(await evaluate('document.querySelectorAll(".resource-layout form").length'),1);
 checks.push('资源条件编辑与人工维护需求互斥');
 await visit('数据中心');
 assert.equal(await evaluate('document.querySelectorAll(".data-versions .data-versions").length'),0);
 assert.equal(await evaluate('document.querySelector(".data-versions").parentElement.tagName'), 'MAIN');
 checks.push('历史版本没有重复折叠容器');
 await visit('帮助');await clickText('指标词典');
 assert.equal(await evaluate('[...document.querySelectorAll(".metric-meaning summary")].some(s=>s.textContent.includes("如何理解"))'),false);
 await screenshot('metric-dictionary-mobile');checks.push('词典使用简洁指标名称');
 await visit('风险预测');
 await window.loadURL('http://127.0.0.1:5173/?view='+encodeURIComponent('风险预测')+'&equipment=CNC-003');
 await waitFor('!!document.querySelector(".risk-flow")');
 const formula=await evaluate(`(()=>{const root=document.querySelector('.risk-flow'),cards=[...root.querySelectorAll(':scope>div')],operators=[...root.querySelectorAll(':scope>i')];return {aligned:operators.every(op=>{const r=op.getBoundingClientRect(),c=cards[0].getBoundingClientRect();return Math.abs((r.left+r.width/2)-(c.left+c.width/2))<2&&getComputedStyle(op).transform==='none'}),fonts:[...root.querySelectorAll('.professional-term')].every(term=>getComputedStyle(term).fontSize===getComputedStyle(term.parentElement).fontSize)}})()`);
 assert(formula.aligned);assert(formula.fonts);checks.push('窄屏公式符号居中，术语字号继承所在行');
 await evaluate('document.querySelector(".risk-formula").scrollIntoView({block:"start"})');await screenshot('risk-formula-mobile');
 window.setContentSize(390,825);await sleep(250);
 assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
 checks.push('390px窄屏设备详情无整体横向溢出');
 await visit('帮助');await clickText('指标词典');
 await window.setContentSize(1440,1000);await screenshot('metric-dictionary-desktop');
 assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
 checks.push('桌面页面无整体横向溢出');
 const report={checks,errors,fixture:'工单流转为只读测试响应，其余读取当前本地数据；没有提交业务变更',screenshots:fs.readdirSync(output).filter(f=>f.endsWith('.png'))};
 fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
 fs.rmSync(path.join(output,'failure.txt'),{force:true});
 console.log(JSON.stringify(report));
}
app.whenReady().then(run).then(()=>app.exit(0)).catch(error=>{console.error(error);fs.writeFileSync(path.join(output,'failure.txt'),String(error.stack));app.exit(1)});

/** Private, strongly consistent Cloudflare session state, independent of D1 writes. */
export class IdentityRuntime {
 constructor(ctx){this.ctx=ctx}
 async fetch(request){
  const op=new URL(request.url).pathname,p=await request.json(),now=Date.now();
  const json=(value,status=200)=>Response.json(value,{status});
  if(op==='/dify-config-get')return json(await this.ctx.storage.get('dify-config:'+p.user_id)||null);
  if(op==='/dify-config-set')return this.ctx.storage.transaction(async tx=>{const old=await tx.get('dify-config:'+p.user_id);if(p.version!==(old?.version||0))return json({detail:'配置已更新，请重新加载。'},409);const value={api_key:p.api_key||old?.api_key||'',input_field:p.input_field,output_field:p.output_field,version:(old?.version||0)+1};await tx.put('dify-config:'+p.user_id,value);return json({success:true,version:value.version})});
  if(op==='/lookup'){
   if(await this.ctx.storage.get('revoked:'+p.digest))return json({revoked:true});
   const session=await this.ctx.storage.get('session:'+p.digest);
   return json({session:session&&Date.parse(session.expires_at)>now?session:null});
  }
  if(op==='/attempt'){
   if(await this.ctx.storage.getAlarm()===null)await this.ctx.storage.setAlarm(now+6*3600000);
   return this.ctx.storage.transaction(async tx=>{
    const stored=await tx.get('attempt:'+p.key),legacy=p.previous;
    const candidates=[stored,legacy].filter(x=>x&&Date.parse(x.window_start)>now-600000);
    const old=candidates.sort((a,b)=>b.attempts-a.attempts)[0];
    if(old?.attempts>=5)return json({detail:'尝试次数过多，请10分钟后重试'},429);
    await tx.put('attempt:'+p.key,{attempts:(old?.attempts||0)+1,window_start:old?.window_start||new Date(now).toISOString(),expires_at:new Date(now+600000).toISOString()});
    return json({success:true});
   });
  }
  if(op==='/sign-in'){
   await this.ctx.storage.transaction(async tx=>{
    await tx.put('session:'+p.digest,p.session);
    if(p.attempt_key)await tx.delete('attempt:'+p.attempt_key);
   });
  }else if(op==='/logout'){
   await this.ctx.storage.transaction(async tx=>{
    await tx.delete('session:'+p.digest);
    await tx.put('revoked:'+p.digest,{expires_at:new Date(now+8*3600000).toISOString()});
   });
  }else if(op==='/progress'){
   return json(await this.ctx.storage.get('progress:'+p.user_id)||p.previous||{step:0,completed_at:null});
  }else if(op==='/onboarding'){
   return this.ctx.storage.transaction(async tx=>{
    const old=await tx.get('progress:'+p.user_id)||p.previous||{step:0,completed_at:null};
    if(!Number.isInteger(p.step)||p.step<0||p.step>5)return json({detail:'教程步骤无效'},422);
    if(p.step>old.step+1)return json({detail:'请按顺序完成新手教程'},409);
    const value={step:Math.max(old.step,p.step),completed_at:old.completed_at||(p.step===5?new Date(now).toISOString():null)};
    await tx.put('progress:'+p.user_id,value);return json(value);
   });
  }else{return json({detail:'Not found'},404)}
  if(await this.ctx.storage.getAlarm()===null)await this.ctx.storage.setAlarm(now+6*3600000);
  return json({success:true});
 }
 async alarm(){
  const now=Date.now(),rows=await this.ctx.storage.list(),expired=[];
  for(const [key,value] of rows)if(value.expires_at&&Date.parse(value.expires_at)<=now)expired.push(key);
  for(let start=0;start<expired.length;start+=100)await this.ctx.storage.delete(expired.slice(start,start+100));
  if([...rows.keys()].some(key=>!key.startsWith('progress:')&&!expired.includes(key)))await this.ctx.storage.setAlarm(now+6*3600000);
 }
}

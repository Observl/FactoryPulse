/** Private, strongly consistent Cloudflare session state, independent of D1 writes. */
export class IdentityRuntime {
 constructor(ctx){this.ctx=ctx}
 async fetch(request){
  const op=new URL(request.url).pathname,p=await request.json(),now=Date.now();
  const json=(value,status=200)=>Response.json(value,{status});
  if(op==='/dify-config-get')return json(await this.ctx.storage.get('dify-config:'+p.user_id)||null);
  if(op==='/dify-config-set')return this.ctx.storage.transaction(async tx=>{const old=await tx.get('dify-config:'+p.user_id);if(p.version!==(old?.version||0))return json({detail:'配置已更新，请重新加载。'},409);const value={api_key:p.api_key||old?.api_key||'',input_field:p.input_field,output_field:p.output_field,version:(old?.version||0)+1};await tx.put('dify-config:'+p.user_id,value);return json({success:true,version:value.version})});
  // The browser stores only an authenticated AES-GCM envelope in an HttpOnly cookie.
  if(op==='/session-seal'||op==='/session-open'){
   const raw=await this.ctx.storage.transaction(async tx=>{let value=await tx.get('session-encryption-key');if(!value){value=Array.from(crypto.getRandomValues(new Uint8Array(32)));await tx.put('session-encryption-key',value)}return value});
   const key=await crypto.subtle.importKey('raw',new Uint8Array(raw),'AES-GCM',false,['encrypt','decrypt']);
   const encode=bytes=>btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
   const decode=value=>Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
   if(op==='/session-seal'){
    if(p.attempt_key)await this.ctx.storage.delete('attempt:'+p.attempt_key);
    const iv=crypto.getRandomValues(new Uint8Array(12)),generation=await this.ctx.storage.get('user-generation:'+p.user.user_id)||0;
    const claims={user:p.user,expires_at:now+8*3600000,generation,nonce:crypto.randomUUID()};
    const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv},key,new TextEncoder().encode(JSON.stringify(claims)));
    return json({token:'v2.'+encode(iv)+'.'+encode(encrypted)});
   }
   try{
    const [version,iv,data]=p.token.split('.');if(version!=='v2')return json(null);
    if(await this.ctx.storage.get('revoked-token:'+p.token))return json(null);
    const claims=JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(iv)},key,decode(data))));
    const generation=await this.ctx.storage.get('user-generation:'+claims.user.user_id)||0;
    return json(claims.expires_at>now&&claims.generation===generation?claims.user:null);
   }catch{return json(null)}
  }
  if(op==='/invalidate-user'){
   await this.ctx.storage.transaction(async tx=>{const key='user-generation:'+p.user_id;await tx.put(key,(await tx.get(key)||0)+1)});
   return json({success:true});
  }
  if(op==='/revoke-token'){
   await this.ctx.storage.put('revoked-token:'+p.token,{expires_at:new Date(now+8*3600000).toISOString()});
   return json({success:true});
  }
  if(op==='/lookup'){
   if(await this.ctx.storage.get('revoked:'+p.digest))return json({revoked:true});
   const session=await this.ctx.storage.get('session:'+p.digest);
   return json({session:session&&Date.parse(session.expires_at)>now?session:null});
  }
  if(op==='/attempt'){
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
  return json({success:true});
 }
 async alarm(){/* Older deployments may leave an alarm; do not reschedule or scan storage. */}
}

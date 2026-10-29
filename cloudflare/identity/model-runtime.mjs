/** Portable inference only: no training records, Python runtime, or D1 reads. */
export function infer(model,features){
 if(!Array.isArray(features)||features.length!==model.feature_count||features.some(x=>x!==null&&(typeof x!=='number'||!Number.isFinite(x)))||!features.some(x=>x!==null))throw new Error('输入必须是指定长度的数值数组，缺失使用 null，不能全部缺失');
 const x=features.map((v,i)=>v===null?(model.imputation?Math.fround(model.imputation[i]):null):Math.fround(v));
 let probabilities;
 if(model.kind==='xgboost_binary'){
  let margin=Math.fround(model.base_margin);
  for(const tree of model.trees){let node=0;while(tree.left[node]>=0){const value=x[tree.feature[node]];node=value===null?(tree.missing_left[node]?tree.left[node]:tree.right[node]):value<Math.fround(tree.value[node])?tree.left[node]:tree.right[node]}margin=Math.fround(margin+Math.fround(tree.value[node]))}
  const score=1/(1+Math.exp(-margin));probabilities=[1-score,score];
 }else if(model.kind==='extra_trees'){
  probabilities=Array(model.classes.length).fill(0);
  for(const tree of model.trees){let node=0;while(tree.left[node]>=0)node=x[tree.feature[node]]<=tree.threshold[node]?tree.left[node]:tree.right[node];tree.probabilities[node].forEach((v,i)=>probabilities[i]+=v)}
  probabilities=probabilities.map(v=>v/model.trees.length);
 }else throw new Error('不支持的模型格式');
 const index=probabilities.length===2?(probabilities[1]>=model.threshold?1:0):probabilities.indexOf(Math.max(...probabilities));
 return {label:model.classes[index],class_scores:probabilities.map((score,i)=>({label:model.classes[i],score})),decision_threshold:model.classes.length===2?model.threshold:null};
}
let catalogPromise;const models=new Map();
async function asset(env,path){if(!env.ASSETS)throw new Error('模型资源未绑定');const response=await env.ASSETS.fetch(new Request('https://assets.internal'+path));if(!response.ok)throw new Error('模型资源暂不可用');return response.json()}
export async function diagnostics(request,env){
 const path=new URL(request.url).pathname;if(!path.startsWith('/api/model/diagnostics'))return null;
 const json=(body,status=200)=>Response.json(body,{status,headers:{'Cache-Control':'no-store'}});
 try{
  if(!catalogPromise)catalogPromise=asset(env,'/models/manifest.json').catch(error=>{catalogPromise=null;throw error});const catalog=await catalogPromise;
  if(path==='/api/model/diagnostics'&&request.method==='GET')return json(catalog);
  if(request.method!=='POST')return json({detail:'不支持此诊断操作'},405);
  const id=decodeURIComponent(path.slice('/api/model/diagnostics/'.length)),entry=catalog.models.find(m=>m.id===id);if(!entry)return json({detail:'诊断模型不存在'},404);
  const text=await request.text();if(text.length>64000)return json({detail:'诊断输入过长'},413);
  let input;try{input=JSON.parse(text)}catch{return json({detail:'请提供有效 JSON'},422)}
  if(input?.input_contract!==entry.input_contract)return json({detail:'特征格式版本不匹配，请重新载入模型要求'},409);
  if(!models.has(id))models.set(id,asset(env,entry.artifact).catch(error=>{models.delete(id);throw error}));
  const model=await models.get(id);while(models.size>2)models.delete(models.keys().next().value);
  let result;try{result=infer(model,input.features)}catch(error){return json({detail:error.message},422)}
  return json({...result,model_id:id,model_version:catalog.version,artifact_sha256:entry.artifact_sha256,scope:entry.scope,semantics:'匹配训练格式的当前状态诊断分数；不表示未来七天故障概率，也不自动生成维修任务',computed_at:new Date().toISOString()});
 }catch{return json({detail:'诊断模型暂时不可用，请稍后重试'},503)}
}

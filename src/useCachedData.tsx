import {Button} from './components/Button';
import {useEffect,useRef,useSyncExternalStore} from 'react';
import {processedCache} from './data-cache';
export function useApiUpdate(paths:(string|RegExp)[],onUpdate:(path:string,data:any)=>void){
 const callback=useRef(onUpdate),matchers=useRef(paths);callback.current=onUpdate;matchers.current=paths;
 useEffect(()=>processedCache.subscribe((path,data)=>{if(matchers.current.some(value=>typeof value==='string'?value===path:value.test(path)))callback.current(path,data)}),[]);
}
export function DataCacheStatus(){
 const status=useSyncExternalStore(processedCache.subscribeStatus,processedCache.getStatus);
 if(!status.enabled)return null;
 return <><Button className="secondary" disabled={status.checking} onClick={()=>void processedCache.check()}>{status.checking?"正在更新…":"更新数据"}</Button><span className="data-cache-status" role="status" title={status.error||`已缓存 ${status.entries} 项结果；仅点击更新数据时检查线上版本，未变更时保留本地 JSON。`}>{status.error?'缓存可用 · 更新检查失败':status.checking?'检查更新中':status.lastChecked?'缓存已同步':'本地缓存就绪'}</span></>;
}

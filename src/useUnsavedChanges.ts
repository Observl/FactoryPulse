import {useCallback,useEffect,useRef,useState} from "react";

const navigationEvent="factorypulse:before-navigation";
export function confirmUnsavedNavigation(){
 const event=new Event(navigationEvent,{cancelable:true});
 return window.dispatchEvent(event)||window.confirm("有尚未保存的内容。离开后这些修改会丢失，确定继续？");
}

export function useUnsavedChanges(){
 const [dirty,setDirty]=useState(false);
 const current=useRef(false);
 const mark=useCallback(()=>{current.current=true;setDirty(true)},[]);
 const clear=useCallback(()=>{current.current=false;setDirty(false)},[]);
 const discard=useCallback(()=>{if(current.current&&!window.confirm("当前修改尚未保存。放弃修改并继续？"))return false;clear();return true},[clear]);
 useEffect(()=>{
  const guard=(event:Event)=>{if(current.current)event.preventDefault()};
  const unload=(event:BeforeUnloadEvent)=>{if(current.current){event.preventDefault();event.returnValue=""}};
  window.addEventListener(navigationEvent,guard);window.addEventListener("beforeunload",unload);
  return()=>{window.removeEventListener(navigationEvent,guard);window.removeEventListener("beforeunload",unload)};
 },[]);
 return {dirty,mark,clear,discard};
}

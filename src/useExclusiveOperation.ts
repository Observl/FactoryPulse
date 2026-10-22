import {useEffect,useId,useRef} from "react";
import {confirmUnsavedNavigation} from "./useUnsavedChanges";

const eventName="factorypulse:operation-selected";
/** One editable operation at a time, including forms owned by different components. */
export function useExclusiveOperation(onDismiss:()=>void){
 const id=useId(),dismiss=useRef(onDismiss);dismiss.current=onDismiss;
 useEffect(()=>{
  const listener=(event:Event)=>{if((event as CustomEvent<string>).detail!==id)dismiss.current()};
  window.addEventListener(eventName,listener);
  return()=>window.removeEventListener(eventName,listener);
 },[id]);
 return ()=>{
  if(!confirmUnsavedNavigation())return false;
  window.dispatchEvent(new CustomEvent(eventName,{detail:id}));
  return true;
 };
}

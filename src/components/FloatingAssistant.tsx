import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Bot,Minus,X} from 'lucide-react';
import {Button} from './Button';
import './floating-assistant.css';

/** Non-modal: the workspace remains usable while a conversation stays mounted. */
export function FloatingAssistant({context,children}:{context:string;children:ReactNode}){
 const [open,setOpen]=useState(false),[visited,setVisited]=useState(false);
 const trigger=useRef<HTMLButtonElement>(null),close=useRef<HTMLButtonElement>(null),panel=useRef<HTMLElement>(null);
 const minimize=()=>{setOpen(false);trigger.current?.focus()};
 useEffect(()=>{if(open)close.current?.focus()},[open]);
 return <aside className="floating-assistant" aria-label="悬浮 AI 助手">
  {visited&&<section ref={panel} id="floating-assistant-panel" className="floating-assistant-panel" hidden={!open} aria-label="AI 助手对话" onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();minimize()}}}>
   <header className="floating-assistant-header"><div><Bot size={20} aria-hidden="true"/><strong>AI 助手</strong><small>边看页面，边问问题</small></div><Button ref={close} variant="icon" aria-label="收起 AI 助手" onClick={minimize}><Minus size={19}/></Button></header>
   <p className="floating-assistant-context">{context}</p>
   <div className="floating-assistant-content">{children}</div>
  </section>}
  <Button ref={trigger} className="floating-assistant-trigger" variant="secondary" aria-label={open?'收起 AI 助手':'打开 AI 助手'} aria-expanded={open} aria-controls="floating-assistant-panel" onClick={()=>{setVisited(true);setOpen(value=>!value)}}>{open?<X size={20} aria-hidden="true"/>:<Bot size={22} aria-hidden="true"/>}<span>AI 助手</span></Button>
 </aside>;
}

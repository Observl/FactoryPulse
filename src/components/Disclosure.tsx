import {useState,type ReactNode} from 'react';
import {ChevronDown} from 'lucide-react';

/** Secondary content is loaded on first expansion and retained across toggles. */
export function Disclosure({title,meta,children,defaultOpen=false,className=''}:{title:string;meta?:ReactNode;children:ReactNode;defaultOpen?:boolean;className?:string}){
 const [visited,setVisited]=useState(defaultOpen);
 return <details className={`disclosure ${className}`} open={defaultOpen||undefined} onToggle={event=>{if(event.currentTarget.open)setVisited(true)}}>
  <summary><span className="disclosure-title">{title}</span>{meta!=null&&<span className="disclosure-meta">{meta}</span>}<ChevronDown className="disclosure-chevron" size={16} aria-hidden="true"/></summary>
  {visited&&<div className="disclosure-body">{children}</div>}
 </details>;
}

import {useEffect,useId,useRef,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {Button} from './Button';
export function ActionDialog({title,children,onClose,busy=false}:{title:string;children:ReactNode;onClose:()=>void;busy?:boolean}){
 const ref=useRef<HTMLDialogElement>(null),titleId=useId();
 useEffect(()=>{const dialog=ref.current;dialog?.showModal();return()=>dialog?.close()},[]);
 return createPortal(<dialog ref={ref} className="ui-action-dialog" aria-labelledby={titleId} onClick={event=>event.stopPropagation()} onKeyDown={event=>event.stopPropagation()} onSubmit={event=>event.stopPropagation()} onCancel={event=>{event.preventDefault();if(!busy)onClose()}}><header className="ui-action-dialog-header"><h2 id={titleId}>{title}</h2><Button disabled={busy} onClick={onClose} aria-label={'关闭'+title}>关闭</Button></header><div className="ui-action-dialog-content">{children}</div></dialog>,document.body);
}

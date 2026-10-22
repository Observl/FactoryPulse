import {ActionDialog} from "./components/ActionDialog";
import {Button} from "./components/Button";
import {useState} from 'react';
import {useAuth} from './Auth';
import {apiRequest,errorMessage} from './api';
import {useUnsavedChanges} from './useUnsavedChanges';
import {useExclusiveOperation} from './useExclusiveOperation';
export function ProfileSettings(){
 const auth=useAuth(),unsaved=useUnsavedChanges();
 const [open,setOpen]=useState(false),[username,setUsername]=useState(''),[display,setDisplay]=useState(''),[version,setVersion]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 const close=()=>{setOpen(false);setUsername('');setDisplay('');setError('');unsaved.clear()};
 const exclusive=useExclusiveOperation(close);
 if(!auth.user||!['developer','admin'].includes(auth.user.role))return null;
 const submit=async()=>{setBusy(true);setError('');try{await apiRequest('/auth/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,display_name:display,version})});close();await auth.refresh();setMessage('显示名称已更新，登录编号不变。')}catch(reason){setError(errorMessage(reason))}finally{setBusy(false)}};
 return <div className="profile-settings"><Button className="secondary" disabled={busy} onClick={()=>{if(open){if(unsaved.discard())close()}else if(exclusive()){setUsername(auth.user!.username);setDisplay(auth.user!.display_name);setVersion(auth.user!.version);setOpen(true);setMessage('')}}}>修改账号名称</Button>{message&&<p role="status">{message}</p>}{open&&<ActionDialog title="修改账号名称" busy={busy} onClose={()=>{if(unsaved.discard())close()}}><form className="operation-form" aria-label="修改自己的账号名称" onChangeCapture={unsaved.mark} onSubmit={e=>{e.preventDefault();void submit()}}><label>用户编号<input readOnly autoComplete="username" maxLength={60} value={username} onChange={e=>setUsername(e.target.value)}/></label><label>显示名称<input required maxLength={100} value={display} onChange={e=>setDisplay(e.target.value)}/></label><div className="ui-form-feedback" aria-live="polite">{error&&<p className="alert error" role="alert">{error}</p>}</div><div className="actions"><Button className="primary" disabled={busy||!username.trim()||!display.trim()} type="submit" busy={busy} busyLabel="正在保存…">{'保存名称'}</Button><Button className="secondary" disabled={busy} type="button" onClick={()=>{if(unsaved.discard())close()}}>取消</Button></div></form></ActionDialog>}</div>;
}

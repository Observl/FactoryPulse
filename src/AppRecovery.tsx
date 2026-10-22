import {Button} from "./components/Button";
import {Component,type ErrorInfo,type ReactNode} from "react";

type State={failed:boolean;reference:string};
export class AppRecovery extends Component<{children:ReactNode},State>{
 state:State={failed:false,reference:""};
 static getDerivedStateFromError():State{return {failed:true,reference:`UI-${Date.now().toString(36).toUpperCase()}`}}
 componentDidCatch(_error:Error,_info:ErrorInfo){
  // Do not serialize component state, imported rows, passwords or API keys.
  console.error("FactoryPulse 页面显示异常",this.state.reference);
 }
 render(){
  if(!this.state.failed)return this.props.children;
  return <main className="auth-frame"><section className="panel" role="alert"><h1>页面暂时无法显示</h1><p>当前输入尚未保存的内容可能丢失。已提交操作是否成功，请恢复后核对工单与处理记录。</p><p className="hint">参考编号：{this.state.reference}</p><Button className="primary" onClick={()=>window.location.reload()}>重新载入并核对记录</Button><p className="hint">如再次出现，请向管理员提供参考编号、操作时间和所处步骤。不要提供密码或密钥。</p></section></main>;
 }
}

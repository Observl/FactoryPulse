import React from "react";
import { createRoot } from "react-dom/client";

import {AuthGate} from "./Auth";
import {AppRecovery} from "./AppRecovery";
import "./styles.css";
import "./workflow-extensions.css";
import "./ui-consistency.css";
import "./workflow-polish.css";
import "./pearl-glass.css";

async function start() {
  if (import.meta.env.VITE_STATIC_DEMO === "true") {
    const {default:StaticReview}=await import("./StaticReview");
    createRoot(document.getElementById("root")!).render(<AppRecovery><AuthGate><StaticReview/></AuthGate></AppRecovery>);
    return;
  }
  const {default:App}=await import("./App");
  createRoot(document.getElementById("root")!).render(<React.StrictMode><AppRecovery><AuthGate><App /></AuthGate></AppRecovery></React.StrictMode>);
}
void start().catch(()=>{
 const root=document.getElementById("root");
 if(!root)return;
 createRoot(root).render(<main className="auth-frame"><section className="panel" role="alert"><h1>工具启动未完成</h1><p>请确认应用文件完整，再重新载入。重复出现时联系管理员处理。</p><button className="primary" onClick={()=>window.location.reload()}>重新载入</button></section></main>);
});

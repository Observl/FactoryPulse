import { useEffect, useState } from "react";
import { Activity, Bot, CalendarClock, ChartNoAxesCombined, ClipboardList, Database, Factory, Gauge, Settings2, ShieldAlert } from "lucide-react";
import { BarChart, Bar, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Device = { equipment_id: string; equipment_name: string; equipment_type: string; status: string; risk_score: number; temperature_k: number; rotational_speed_rpm: number };
const fallback: Device[] = [
  { equipment_id: "CNC-001", equipment_name: "立式加工中心 A", equipment_type: "CNC", status: "正常", risk_score: 0.12, temperature_k: 307.4, rotational_speed_rpm: 1450 },
  { equipment_id: "CNC-002", equipment_name: "精密铣削中心 B", equipment_type: "CNC", status: "预警", risk_score: 0.76, temperature_k: 313.2, rotational_speed_rpm: 1710 },
  { equipment_id: "CNC-003", equipment_name: "五轴加工中心 C", equipment_type: "CNC", status: "高风险", risk_score: 0.89, temperature_k: 317.1, rotational_speed_rpm: 1820 },
  { equipment_id: "CNC-004", equipment_name: "数控车床 D", equipment_type: "CNC", status: "正常", risk_score: 0.19, temperature_k: 305.7, rotational_speed_rpm: 1310 },
  { equipment_id: "CNC-005", equipment_name: "加工中心 E", equipment_type: "CNC", status: "正常", risk_score: 0.31, temperature_k: 309.1, rotational_speed_rpm: 1540 },
  { equipment_id: "CNC-006", equipment_name: "加工中心 F", equipment_type: "CNC", status: "预警", risk_score: 0.68, temperature_k: 312.4, rotational_speed_rpm: 1690 }
];
const nav = [
  { name: "设备总览", icon: Gauge }, { name: "设备管理", icon: Database }, { name: "风险预测", icon: Activity },
  { name: "异常解释", icon: ShieldAlert }, { name: "维护策略", icon: ChartNoAxesCombined },
  { name: "维护计划", icon: CalendarClock }, { name: "Factory Copilot", icon: Bot }
];
export default function App() {
  const [page, setPage] = useState("设备总览");
  const [devices, setDevices] = useState<Device[]>(fallback);
  const [source, setSource] = useState("内置模拟数据");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/equipment", { signal: controller.signal }).then(r => { if (!r.ok) throw Error("API unavailable"); return r.json(); })
      .then((data: { devices: Device[]; data_source: string }) => { setDevices(data.devices); setSource(data.data_source); })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  const warning = devices.filter(d => d.risk_score >= 0.6).length;
  const avg = devices.length ? devices.reduce((s, d) => s + d.risk_score, 0) / devices.length : 0;
  return <div className="layout">
    <aside className="sidebar"><div className="brand"><span className="brand-icon"><Factory size={20}/></span><div>FactoryPulse<small>工业智能维护平台</small></div></div>
      <div className="nav-title">工作空间</div><nav>{nav.map(({ name, icon: Icon }) => <button key={name} className={page === name ? "nav active" : "nav"} onClick={() => setPage(name)}><Icon size={18}/>{name}</button>)}</nav>
      <div className="sidebar-footer"><Settings2 size={16}/> 本地演示版本 v0.1.0</div>
    </aside>
    <main className="main"><header><div><div className="eyebrow">FACTORY OPERATIONS / OVERVIEW</div><h1>{page}</h1><p>制造设备健康监测与维护辅助决策</p></div><span className="demo-tag">模拟数据 · 不代表真实预测</span></header>
      {page === "设备总览" || page === "设备管理" ? <>
        <div className="metrics"><div className="metric"><span>设备总数</span><strong>{devices.length}</strong><small>当前样本设备</small></div><div className="metric"><span>高风险与预警</span><strong className="orange">{warning}</strong><small>风险评分 ≥ 0.60</small></div><div className="metric"><span>平均风险评分</span><strong>{(avg * 100).toFixed(1)}%</strong><small>演示风险评分</small></div><div className="metric"><span>数据来源</span><strong className="source">{source === "内置模拟数据" ? "本地" : "API"}</strong><small>{source}</small></div></div>
        <div className="content-grid"><section className="panel chart-panel"><div className="panel-heading"><h2>设备风险分布</h2><span>模拟评分（0–100%）</span></div><ResponsiveContainer width="100%" height={250}><BarChart data={devices.map(d => ({ name: d.equipment_id, risk: Math.round(d.risk_score * 100) }))}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf0f2"/><XAxis dataKey="name" tick={{ fontSize: 11 }}/><YAxis domain={[0, 100]} tick={{ fontSize: 11 }}/><Tooltip formatter={(v) => [v + "%", "风险评分"]}/><Bar dataKey="risk" fill="#f97316" radius={[5, 5, 0, 0]}/></BarChart></ResponsiveContainer></section>
        <section className="panel info-panel"><div className="panel-heading"><h2>系统状态</h2><span>DEMO</span></div><div className="info-row"><span>设备数据</span><b>已加载</b></div><div className="info-row"><span>故障预测模型</span><b>待接入</b></div><div className="info-row"><span>维护优化引擎</span><b>待接入</b></div><div className="info-row"><span>AI API</span><b>待配置</b></div><p className="hint">此页面用于验证桌面框架、接口联动与基础交互。当前风险评分为模拟值，不是机器学习模型输出。</p></section></div>
        <section className="panel table-panel"><div className="panel-heading"><h2>设备运行概览</h2><span>{devices.length} 台设备</span></div><div className="table-scroll"><table><thead><tr><th>设备编号</th><th>设备名称</th><th>类型</th><th>状态</th><th>风险评分</th><th>工艺温度（K）</th><th>转速（rpm）</th></tr></thead><tbody>{devices.map(d => <tr key={d.equipment_id}><td className="mono">{d.equipment_id}</td><td>{d.equipment_name}</td><td>{d.equipment_type}</td><td><span className={d.risk_score >= 0.6 ? "status warn" : "status"}>{d.status}</span></td><td className={d.risk_score >= 0.6 ? "orange" : ""}>{(d.risk_score * 100).toFixed(0)}%</td><td>{d.temperature_k.toFixed(1)}</td><td>{d.rotational_speed_rpm}</td></tr>)}</tbody></table></div></section>
      </> : <section className="panel placeholder"><ClipboardList size={32} color="#f97316"/><h2>{page} · 开发中</h2><p>该模块已加入项目开发计划，当前版本尚未实现真实业务功能。</p><a href="https://github.com/Observl/FactoryPulse/issues">查看开发 Issues →</a></section>}
    </main></div>;
}

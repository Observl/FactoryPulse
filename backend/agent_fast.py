"""Exact, read-only shortcuts. Ambiguous or compound requests stay with the agent."""
import re
from .agent_policy import plain_answer

def quick_tool(question: str):
    text=re.sub(r"[\s？?。！!]", "",question)
    if text in {"模型评估结果可靠吗","模型评估可靠吗","模型准确吗","查看模型评估","模型预测准确吗"}: return "evaluation"
    if text in {"本周哪些设备需要优先复核","哪些设备需要优先复核","查看高风险设备","哪些设备风险最高"}: return "equipment"
    if text in {"比较当前维护排程方案","比较当前维护方案","比较维护方案"}: return "compare_plans"
    return None

def evidence_answer(tool: str, evidence: dict) -> dict:
    source=evidence.get("source",tool);stamp=evidence.get("data_time") or "未提供"
    if tool=="evaluation":
        metrics=evidence.get("evaluation") or {}
        def pct(key):
            value=metrics.get(key)
            return "未提供" if value is None else f"{float(value)*100:.1f}%"
        if not metrics:
            answer="当前没有可用的模型评估，无法判断预测准确性。请先核对数据与真实故障标注。"
        else:
            events=metrics.get('independent_test_events')
            limit="独立故障证据有限，尚不能证明现场准确性。" if events is None or events<10 else "仍需通过更多设备与现场试用验证。"
            answer=f"{limit}当前风险分数不是故障概率。\n\n历史测试预警命中率{pct('precision')}，故障前窗口发现率{pct('recall')}，正常窗口误报率{pct('false_alarm_rate')}；独立故障{events if events is not None else '未提供'}次。请在风险中心查看完整评估。"
    elif tool=="compare_plans":
        strategies=evidence.get("strategies") or []
        labels={"fixed_interval":"固定顺序对照","risk_threshold":"风险阈值优先","optimized":"约束优化选择"}
        def value(summary,key,unit=""):
            number=summary.get(key)
            return "未提供" if number is None else f"{number:,.1f}{unit}"
        lines=[]
        for item in strategies:
            summary=item.get("summary") or {}
            lines.append(f"{labels.get(item.get('strategy'),'其他方案')}：{summary.get('task_count','未提供')}项，维护费用{value(summary,'maintenance_cost','元')}，累计工时{value(summary,'maintenance_hours','小时')}")
        scenario=next((item.get("scenario") for item in strategies if item.get("scenario")),"未提供")
        answer=(f"按情景“{scenario}”计算："+"；".join(lines)+"。") if lines else "当前没有可比较的维护方案，请先核对维护资源与情景条件。"
        answer+="\n\n这是任务取舍对照，尚未创建或批准工单，也不能证明无人员、班次或订单冲突。请在维护中心选择所需情景，核对正式排程。费用来自录入参数；收益仅可作情景测算。"
    else:
        devices=evidence.get('devices') or []
        available=[item for item in devices if item.get('risk_score') is not None and item.get('risk_available',True)]
        available.sort(key=lambda item:-item['risk_score'])
        elevated=[item for item in available if item.get('review_required',item['risk_score']>=.15)]
        if elevated:
            descriptions=[f"{item['equipment_id']}：{item['risk_score']*100:.1f}分" for item in elevated[:5]]
            answer="在本次返回的设备中，优先复核"+"；".join(descriptions)+"。请打开设备证据，核对工况和维修履历后决定是否创建维护需求。"
        else: answer="本次查询未发现达到当前复核提醒线的设备。证据不足不表示设备安全，仍需核对数据完整性。"
        answer+="\n\n这些是现有记录的风险排序，不是未来七天故障概率，也不代表现场实时状态。"
    answer+=f"\n\n数据时间：{stamp}；来源：{source}。"
    return {"answer":plain_answer(answer),"mode":"evidence_direct","trace":[{"tool":tool,"source":source,"data_time":evidence.get('data_time'),"data_version":evidence.get('data_version'),"model_version":evidence.get('model_version'),"status":"success","result_summary":"基于后端原始证据直接回答，未调用语言模型"}],"proposals":[],"evidence":evidence if tool=='equipment' else None}

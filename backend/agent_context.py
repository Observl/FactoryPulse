"""Small model-facing evidence views; original tool results stay in the run cache."""


def model_evidence(tool, result):
    view = dict(result)
    if tool == "equipment" and isinstance(view.get("devices"),list):
        view["devices"] = [{k:v for k,v in device.items() if k != "scoring_details"} for device in view["devices"]]
        view["context_note"] = "保留设备风险、工况、SHAP和来源；逐项评分公式可在设备证据页面查看。"
    if tool == "evaluation" and isinstance(view.get("evaluation"),dict):
        view["evaluation"] = {k:v for k,v in view["evaluation"].items() if k not in {"events","adaptive_training","feature_names","equipment_profile"}}
        view["context_note"] = "保留评估指标、样本数量、时间范围与适用限制；逐事件表和训练配置未展开。"
    if tool == "history" and isinstance(view.get("series"),list) and len(view["series"])>8:
        series=view["series"]
        indices={0,len(series)-1}
        for key in ("risk","signal"):
            valid=[i for i,row in enumerate(series) if isinstance(row.get(key),(int,float))]
            if valid:
                indices.add(min(valid,key=lambda i:series[i][key]))
                indices.add(max(valid,key=lambda i:series[i][key]))
        view["series"]=[series[i] for i in sorted(indices)]
        view["series_context_summary"]={"input_points":len(series),"shown_points":len(indices),"selection":"首尾与风险/信号极值原始采样点；不是完整时序，不用于推断每个中间时刻"}
    return view

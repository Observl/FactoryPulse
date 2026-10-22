"""Join historical evidence for display; never feed retrospective labels to scoring."""
from datetime import datetime


def event_timeline(series, faults, maintenance):
    timeline=[]
    bounds={}
    prior={}
    for point in sorted(series,key=lambda row:str(row.get("timestamp",""))):
        equipment=str(point.get("equipment_id",""));stamp=point.get("timestamp")
        if not stamp: continue
        bounds.setdefault(equipment,[stamp,stamp])[1]=stamp
        alert=bool(point.get("alert"))
        if alert and not prior.get(equipment,False):
            observed=point.get("observed_future_failure")
            outcome="事后核验：故障前提醒" if observed==1 else "事后核验：误报窗口" if observed==0 else "后续观测不足，无法核验"
            timeline.append({"equipment_id":equipment,"timestamp":stamp,"kind":"alert","title":"模型达到提醒分数线","detail":outcome,"reading_id":point.get("reading_id"),"score":point.get("score")})
        prior[equipment]=alert
    for event in faults:
        timeline.append({"equipment_id":event["equipment_id"],"timestamp":event["failure_at"],"kind":"failure","title":"真实故障开始","detail":"事后核验：已提前提醒" if event.get("detected") else "事后核验：漏报","lead_hours":event.get("lead_hours"),"first_alert_at":event.get("first_alert_at")})
    for record in maintenance:
        equipment=str(record.get("equipment_id",""));stamp=record.get("maintenance_date") or record.get("verified_at")
        if equipment not in bounds or not stamp: continue
        try:
            moment=datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
            low=datetime.fromisoformat(bounds[equipment][0].replace("Z","+00:00"));high=datetime.fromisoformat(bounds[equipment][1].replace("Z","+00:00"))
            if not low<=moment<=high: continue
        except (ValueError,TypeError): continue
        timeline.append({"equipment_id":equipment,"timestamp":str(stamp),"kind":"maintenance","title":record.get("maintenance_type") or "历史维修记录","detail":"原始记录，不据此推断维修因果收益","maintenance_id":record.get("maintenance_id"),"source":record.get("data_origin")})
    return sorted(timeline,key=lambda row:str(row["timestamp"]))

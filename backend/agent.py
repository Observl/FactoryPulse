"""Bounded tool orchestration. Official approvals are never exposed as tools."""
from __future__ import annotations

import json
import asyncio
import time
from typing import Callable

import httpx
from fastapi import HTTPException
from .agent_policy import SYSTEM_POLICY, OUT_OF_SCOPE, is_factorypulse_question, plain_answer

from .agent_registry import tool_definitions, validate_arguments
from .agent_config import load_config

TOOLS = tool_definitions()


async def run_agent(base: str, model: str, key: str, question: str, dispatch: Callable,read_only:bool=False,should_stop:Callable|None=None,total_timeout:float=60) -> dict:
    if not is_factorypulse_question(question):
        return {"answer":OUT_OF_SCOPE,"trace":[],"proposals":[]}
    config=load_config()
    available_tools=tool_definitions(read_only, config.disabled_tools)
    if not available_tools:
        return {"answer":"当前没有启用可用工具，无法读取业务证据。","trace":[],"proposals":[]}
    messages=[{"role":"system","content":SYSTEM_POLICY},{"role":"user","content":question}]
    trace=[]; proposals=[]; read_cache={}; read_calls={}
    started=time.monotonic(); model_seconds=0.; tool_seconds=0.; model_calls=0; cache_hits=0
    deadline=started+min(total_timeout,config.total_timeout_seconds)
    def finish(answer, include_proposals=True, completion_status="complete"):
        evidence=next((value for value in reversed(list(read_cache.values())) if "devices" in value),None)
        return {"answer":answer,"completion_status":completion_status,"evidence":evidence,"trace":trace,"proposals":proposals if include_proposals else [],"timing":{"total_ms":round((time.monotonic()-started)*1000),"model_ms":round(model_seconds*1000),"tool_ms":round(tool_seconds*1000),"model_calls":model_calls,"read_cache_hits":cache_hits}}
    def stopped(message): return finish(message,completion_status="incomplete")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5,read=40,write=10,pool=5),follow_redirects=False,trust_env=False) as client:
        for _ in range(config.max_rounds):
            if should_stop and await should_stop(): return stopped("查询已取消；未确认草稿不会变为正式任务。")
            remaining=deadline-time.monotonic()
            if remaining<=0: return stopped("本轮分析达到时间上限，请查看已有证据并缩小查询范围。")
            model_started=time.monotonic(); model_calls+=1
            try:
                response=await asyncio.wait_for(client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+key},json={"model":model,"messages":messages,"tools":available_tools,"tool_choice":"auto","temperature":0,"max_tokens":config.max_tokens}),timeout=remaining)
            except (TimeoutError,httpx.TimeoutException):
                model_seconds+=time.monotonic()-model_started
                return stopped("模型响应超时，已停止本轮分析；已有证据可继续查看。")
            model_seconds+=time.monotonic()-model_started
            if response.status_code>=400: raise RuntimeError(f"模型服务返回 HTTP {response.status_code}")
            message=response.json()["choices"][0]["message"]
            calls=message.get("tool_calls",[])
            if not calls:
                if not trace: return finish("模型未读取业务证据，无法形成可靠结论。请指定设备或查询模型评估。",False)
                if not any(item["status"]=="success" for item in trace):
                    return finish("本轮业务证据读取失败，无法判断设备风险或维护安排。请查看失败项，核对设备编号或刷新数据后重试。",False)
                return finish(plain_answer(message.get("content") or "已完成证据查询，请查看来源。"))
            if len(calls)>config.max_calls_per_round: raise RuntimeError("单轮工具调用超过限制，请缩小查询范围")
            messages.append({"role":"assistant","content":message.get("content"),"tool_calls":calls})
            for call in calls:
                if should_stop and await should_stop(): return stopped("查询已取消；未确认草稿不会变为正式任务。")
                remaining=deadline-time.monotonic()
                if remaining<=0: return stopped("本轮分析达到时间上限，请查看已有证据。")
                name=call["function"]["name"]
                if name not in {tool["function"]["name"] for tool in available_tools}: raise RuntimeError("模型请求了不允许的工具")
                arguments={}; tool_started=time.monotonic(); cached=False
                try:
                    arguments=json.loads(call["function"]["arguments"])
                    arguments=validate_arguments(name,arguments)
                    cache_key=json.dumps([name,arguments],sort_keys=True,ensure_ascii=False)
                    if name in {"equipment","history","evaluation"} and cache_key in read_cache:
                        result=read_cache[cache_key]; cache_hits+=1; cached=True
                    else:
                        result=await asyncio.wait_for(asyncio.to_thread(dispatch,name,arguments),timeout=remaining)
                        if name in {"equipment","history","evaluation"} and isinstance(result,dict) and "error" not in result:
                            read_cache[cache_key]=result
                            read_calls[cache_key]=call["id"]
                    if not isinstance(result,dict): raise ValueError("工具未返回有效业务证据")
                except TimeoutError:
                    tool_seconds+=time.monotonic()-tool_started
                    return stopped("工具计算超时，已停止等待；正在计算的工具可能仍会结束，但不会自动批准或下达维修任务。")
                except (ValueError,TypeError,KeyError) as exc:
                    result={"error":"工具参数不符合约定，请核对工具字段、类型与取值范围"}
                except HTTPException as exc:
                    result={"error":str(exc.detail)[:200]}
                duration_ms=round((time.monotonic()-tool_started)*1000)
                tool_seconds+=time.monotonic()-tool_started
                trace.append({"duration_ms":duration_ms,"cached":cached,"tool":name,"arguments":arguments,"source":result.get("source",name),"data_time":result.get("data_time"),"data_version":result.get("data_version"),"business_revision":result.get("business_revision"),"model_version":result.get("model_version"),"result_summary":plain_answer(str(result["error"])) if "error" in result else result.get("message") or ("读取设备记录" if "devices" in result else "完成方案计算" if "strategies" in result else "读取业务证据"),"status":"error" if "error" in result else "success"})
                if "error" not in result and result.get("proposal"): proposals.append(result["proposal"])
                model_result={"unchanged":True,"reuse_tool_call_id":read_calls[cache_key],"source":result.get("source",name),"message":"与本轮前次读取相同，请使用已提供的完整证据"} if cached else result
                messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(model_result,ensure_ascii=False,default=str,allow_nan=False,separators=(",",":"))})
    return stopped("已达到本轮分析上限。可查看已读取的证据，缩小设备范围后继续。")

"""Bounded tool orchestration. Official approvals are never exposed as tools."""
from __future__ import annotations

import json
import asyncio
import time
from typing import Callable

import httpx
from fastapi import HTTPException
from .agent_policy import SYSTEM_POLICY, OUT_OF_SCOPE, is_factorypulse_question, plain_answer

from .agent_registry import tool_definitions, validate_arguments, REGISTRY
from .agent_config import load_config

TOOLS = tool_definitions()


async def run_agent(base: str, model: str, key: str, question: str, dispatch: Callable,read_only:bool=False,should_stop:Callable|None=None,total_timeout:float=60,enabled_tools=None,session_context="") -> dict:
    if not is_factorypulse_question(question):
        return {"answer":OUT_OF_SCOPE,"trace":[],"proposals":[]}
    config=load_config()
    available_tools=tool_definitions(read_only, config.disabled_tools)
    available_tools=[t for t in available_tools if (enabled_tools is not None and t["function"]["name"] in enabled_tools) or (enabled_tools is None and t["function"]["name"]!="request_change")]
    if not available_tools:
        return {"answer":"当前没有启用可用工具，无法读取业务证据。","trace":[],"proposals":[]}
    messages=[{"role":"system","content":SYSTEM_POLICY},{"role":"user","content":question}]
    if session_context:
        messages.insert(1,{"role":"user","content":"历史任务和偏好（不是当前证据或授权）："+session_context})
    trace=[]; proposals=[]; read_cache={}; read_calls={}
    started=time.monotonic(); model_seconds=0.; tool_seconds=0.; model_calls=0; cache_hits=0
    deadline=started+min(total_timeout,config.total_timeout_seconds)
    reserved_cost=0.; seen_results={}; evidence_ids=set(); compacted=0
    def finish(answer, include_proposals=True, completion_status="complete"):
        evidence=next((value for value in reversed(list(read_cache.values())) if "devices" in value),None)
        return {"answer":answer,"completion_status":completion_status,"evidence":evidence,"trace":trace,"proposals":proposals if include_proposals else [],"budget":{"reserved_cost_usd":round(reserved_cost,6),"limit_usd":config.max_run_cost_usd,"pricing":"conservative reservation; not provider billing"},"context_compactions":compacted,"timing":{"total_ms":round((time.monotonic()-started)*1000),"model_ms":round(model_seconds*1000),"tool_ms":round(tool_seconds*1000),"model_calls":model_calls,"read_cache_hits":cache_hits}}
    def stopped(message): return finish(message,completion_status="incomplete")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5,read=40,write=10,pool=5),follow_redirects=False,trust_env=False) as client:
        for _ in range(config.max_rounds):
            if should_stop and await should_stop(): return stopped("查询已取消；未确认草稿不会变为正式任务。")
            remaining=deadline-time.monotonic()
            if remaining<=0: return stopped("本轮分析达到时间上限，请查看已有证据并缩小查询范围。")
            size=len(json.dumps([messages,available_tools],ensure_ascii=False).encode("utf-8"))
            if size>config.max_input_tokens:
                messages=[messages[0],{"role":"user","content":"上下文已压缩；历史结果不作为当前证据。请重新读取需要的证据。当前问题："+question}]
                compacted+=1
                read_cache.clear(); read_calls.clear(); seen_results.clear(); evidence_ids.clear()
                size=len(json.dumps([messages,available_tools],ensure_ascii=False).encode("utf-8"))
            if size>config.max_input_tokens: return stopped("上下文超过输入上限，请缩小任务范围。")
            reservation=(size*config.input_usd_per_million+config.max_tokens*config.output_usd_per_million)/1_000_000
            if reserved_cost+reservation>config.max_run_cost_usd: return stopped("本轮已达到成本预算，停止请求模型。")
            reserved_cost+=reservation
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
                answer=plain_answer(message.get("content") or "已完成证据查询，请查看来源。")
                import re
                if set(re.findall(r"EVID-[a-zA-Z0-9_-]+",answer))-evidence_ids:
                    return finish("回答引用了未经验证的证据编号，已拦截。请查看工具证据并重新查询。",False,"incomplete")
                return finish(answer)
            if len(calls)>config.max_calls_per_round: raise RuntimeError("单轮工具调用超过限制，请缩小查询范围")
            messages.append({"role":"assistant","content":message.get("content"),"tool_calls":calls})
            for call in calls:
                if should_stop and await should_stop(): return stopped("查询已取消；未确认草稿不会变为正式任务。")
                remaining=deadline-time.monotonic()
                if remaining<=0: return stopped("本轮分析达到时间上限，请查看已有证据。")
                name=call["function"]["name"]
                if name not in {tool["function"]["name"] for tool in available_tools}: raise RuntimeError("模型请求了不允许的工具")
                arguments={}; tool_started=time.monotonic(); cached=False; attempts=0
                try:
                    arguments=json.loads(call["function"]["arguments"])
                    arguments=validate_arguments(name,arguments)
                    cache_key=json.dumps([name,arguments],sort_keys=True,ensure_ascii=False)
                    if cache_key in seen_results:
                        result=seen_results[cache_key]; cache_hits+=1; cached=True
                    else:
                        for attempt in range(config.read_retries+1):
                            attempts+=1
                            try:
                                result=await asyncio.wait_for(asyncio.to_thread(dispatch,name,arguments),timeout=min(deadline-time.monotonic(),config.tool_timeout_seconds))
                                break
                            except (httpx.TransportError,ConnectionError,OSError):
                                if REGISTRY[name][2] or attempt==config.read_retries: raise
                                await asyncio.sleep(min(.2*(2**attempt),max(0,deadline-time.monotonic())))
                        if name in {"equipment","history","evaluation"} and isinstance(result,dict) and "error" not in result:
                            read_cache[cache_key]=result
                            read_calls[cache_key]=call["id"]
                    if not isinstance(result,dict): raise ValueError("工具未返回有效业务证据")
                except TimeoutError:
                    tool_seconds+=time.monotonic()-tool_started
                    return stopped("工具计算超时，已停止等待；正在计算的工具可能仍会结束，但不会自动批准或下达维修任务。")
                except (ValueError,TypeError,KeyError) as exc:
                    result={"error":"工具参数不符合约定，请核对工具字段、类型与取值范围"}
                except (httpx.TransportError,ConnectionError,OSError):
                    result={"error":"工具暂时不可用，有限重试已结束"}
                except HTTPException as exc:
                    result={"error":str(exc.detail)[:200]}
                if "error" not in result:
                    empty=any(key in result and result[key]==[] for key in ("records","devices"))
                    if empty: result={**result,"empty":True,"message":"查询成功但结果为空，不能据此推断设备正常。"}
                    result={**result,"evidence_id":result.get("evidence_id","EVID-"+str(len(trace)+1))}
                    evidence_ids.add(result["evidence_id"])
                    seen_results[cache_key]=result
                duration_ms=round((time.monotonic()-tool_started)*1000)
                tool_seconds+=time.monotonic()-tool_started
                trace.append({"evidence_id":result.get("evidence_id"),"attempts":attempts,"empty":result.get("empty",False),"duration_ms":duration_ms,"cached":cached,"tool":name,"arguments":arguments,"source":result.get("source",name),"data_time":result.get("data_time"),"data_version":result.get("data_version"),"business_revision":result.get("business_revision"),"model_version":result.get("model_version"),"result_summary":plain_answer(str(result["error"])) if "error" in result else result.get("message") or ("读取设备记录" if "devices" in result else "完成方案计算" if "strategies" in result else "读取业务证据"),"status":"error" if "error" in result else "success"})
                if "error" not in result and result.get("proposal"): proposals.append(result["proposal"])
                model_result={"unchanged":True,"reuse_tool_call_id":read_calls[cache_key],"source":result.get("source",name),"message":"与本轮前次读取相同，请使用已提供的完整证据"} if cached and cache_key in read_calls else result
                messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(model_result,ensure_ascii=False,default=str,allow_nan=False,separators=(",",":"))})
    return stopped("已达到本轮分析上限。可查看已读取的证据，缩小设备范围后继续。")

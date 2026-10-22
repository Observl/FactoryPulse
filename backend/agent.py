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
from .agent_budget import PhaseBudget
from .agent_context import model_evidence

TOOLS = tool_definitions()


async def run_agent(base: str, model: str, key: str, question: str, dispatch: Callable,read_only:bool=False,should_stop:Callable|None=None,total_timeout:float|None=None,enabled_tools=None,session_context="",on_progress=None) -> dict:
    if not is_factorypulse_question(question) and not (session_context and is_factorypulse_question("设备运维会话后续问题："+question)):
        return {"answer":OUT_OF_SCOPE,"trace":[],"proposals":[]}
    config=load_config()
    available_tools=tool_definitions(read_only, config.disabled_tools)
    available_tools=[t for t in available_tools if (enabled_tools is not None and t["function"]["name"] in enabled_tools) or (enabled_tools is None and t["function"]["name"]!="request_change")]
    if not available_tools:
        return {"answer":"当前没有启用可用工具，无法读取业务证据。","trace":[],"proposals":[]}
    messages=[{"role":"system","content":SYSTEM_POLICY},{"role":"user","content":question}]
    if session_context:
        messages.insert(1,{"role":"user","content":"历史任务和偏好（不是当前证据或授权）："+session_context})
    prefix_count=len(messages)
    trace=[]; proposals=[]; read_cache={}; read_calls={}
    started=time.monotonic(); model_seconds=0.; tool_seconds=0.; model_calls=0; cache_hits=0
    phase=PhaseBudget(config.initial_timeout_seconds,config.progress_extension_seconds,hard_timeout=total_timeout)
    seen_results={}; evidence_ids=set(); compacted=0; force_final=False
    def finish(answer, include_proposals=True, completion_status="complete"):
        evidence=next((value for value in reversed(list(read_cache.values())) if "devices" in value),None)
        return {"answer":answer,"completion_status":completion_status,"evidence":evidence,"trace":trace,"proposals":proposals if include_proposals else [],"budget":phase.snapshot(),"context_compactions":compacted,"timing":{"total_ms":round((time.monotonic()-started)*1000),"model_ms":round(model_seconds*1000),"tool_ms":round(tool_seconds*1000),"model_calls":model_calls,"read_cache_hits":cache_hits}}
    def stopped(message): return finish(message,completion_status="incomplete")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5,read=None,write=10,pool=5),follow_redirects=False,trust_env=False) as client:
        for round_index in range(config.max_rounds):
            if should_stop and await should_stop(): return stopped("查询已取消；未确认草稿不会变为正式任务。")
            remaining=phase.remaining()
            if remaining<=0: return stopped("本轮分析达到时间上限，请查看已有证据并缩小查询范围。")
            size=len(json.dumps([messages,available_tools],ensure_ascii=False).encode("utf-8"))
            if size>config.max_input_tokens:
                # Drop whole oldest tool exchanges, preserving task/criteria and the newest evidence.
                while size>config.max_input_tokens:
                    groups=[i for i in range(prefix_count,len(messages)) if messages[i]["role"]=="assistant"]
                    if len(groups)<2: break
                    del messages[groups[0]:groups[1]]
                    compacted+=1
                    size=len(json.dumps([messages,available_tools],ensure_ascii=False).encode("utf-8"))
            if size>config.max_input_tokens: return stopped("上下文超过输入上限，请缩小任务范围。")
            model_started=time.monotonic(); model_calls+=1
            try:
                response=await asyncio.wait_for(client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+key},json={"model":model,"messages":messages,"tools":available_tools,"tool_choice":"none" if force_final or (trace and round_index==config.max_rounds-1) else "auto","temperature":0,"max_tokens":config.max_tokens}),timeout=remaining)
            except (TimeoutError,httpx.TimeoutException):
                model_seconds+=time.monotonic()-model_started
                return stopped("模型响应超时，已停止本轮分析；已有证据可继续查看。")
            model_seconds+=time.monotonic()-model_started
            if response.status_code>=400:
                reason = {400:"模型服务拒绝了请求，请检查当前模型是否支持工具调用及输出长度配置",401:"模型服务拒绝了密钥，请重新保存与所选服务商匹配的 API Key",403:"当前密钥没有所选模型的访问权限",404:"模型或服务地址不存在，请检查模型设置",429:"模型服务限流或账户额度不足，请检查服务商账户"}.get(response.status_code,"模型服务暂时不可用，请稍后重试")
                return stopped(f"{reason}（HTTP {response.status_code}）。")
            choice=response.json()["choices"][0]
            message=choice["message"]
            calls=message.get("tool_calls",[])
            if not calls:
                if not (message.get("content") or "").strip():
                    return stopped("模型未生成最终回答，可能已耗尽输出额度；已读取的证据仍可查看。请重试或调整模型输出上限。")
                if not trace:
                    import re
                    if re.search(r"怎么使用|如何使用|如何配置|怎么配置|操作流程|功能介绍|怎么导入|如何导入",question):
                        return finish("流程说明（未查询当前业务状态）：\n\n"+plain_answer(message.get("content"),max_chars=6000,max_paragraphs=16))
                    if round_index<config.max_rounds-1:
                        messages.extend([{"role":"assistant","content":message.get("content") or ""},{"role":"user","content":"请先调用受控工具读取当前证据，再分析此问题；不要用历史摘要代替当前业务数据。"}])
                        continue
                    return finish("模型未读取业务证据，无法形成可靠结论。请指定设备或查询模型评估。",False,"incomplete")
                if not any(item["status"]=="success" for item in trace):
                    return finish("本轮业务证据读取失败，无法判断设备风险或维护安排。请查看失败项，核对设备编号或刷新数据后重试。",False)
                answer=plain_answer(message.get("content") or "已完成证据查询，请查看来源。",max_chars=6000,max_paragraphs=16)
                import re
                if set(re.findall(r"EVID-[a-zA-Z0-9_-]+",answer))-evidence_ids:
                    return finish("回答引用了未经验证的证据编号，已拦截。请查看工具证据并重新查询。",False,"incomplete")
                return finish(answer)
            deferred=[]
            if len(calls)>config.max_calls_per_round:
                deferred=[call.get("function",{}).get("name", "unknown") for call in calls[config.max_calls_per_round:]]
                calls=calls[:config.max_calls_per_round]
            assistant_message={"role":"assistant","content":message.get("content"),"tool_calls":calls}
            # Some reasoning providers require their returned field on subsequent tool turns.
            # It remains internal; never include it in answers, traces or session memory.
            if isinstance(message.get("reasoning_content"),str):
                assistant_message["reasoning_content"]=message["reasoning_content"]
            messages.append(assistant_message)
            round_cached=0
            for call in calls:
                if should_stop and await should_stop(): return stopped("查询已取消；未确认草稿不会变为正式任务。")
                remaining=phase.remaining()
                if remaining<=0: return stopped("本轮分析达到时间上限，请查看已有证据。")
                name=call["function"]["name"]
                if name not in {tool["function"]["name"] for tool in available_tools}: raise RuntimeError("模型请求了不允许的工具")
                arguments={}; tool_started=time.monotonic(); cached=False; attempts=0
                try:
                    arguments=json.loads(call["function"]["arguments"])
                    arguments=validate_arguments(name,arguments)
                    cache_key=json.dumps([name,arguments],sort_keys=True,ensure_ascii=False)
                    if cache_key in seen_results:
                        result=seen_results[cache_key]; cache_hits+=1; cached=True; round_cached+=1
                    else:
                        for attempt in range(config.read_retries+1):
                            attempts+=1
                            try:
                                result=await asyncio.wait_for(asyncio.to_thread(dispatch,name,arguments),timeout=min(phase.remaining(),config.tool_timeout_seconds))
                                break
                            except (httpx.TransportError,ConnectionError,OSError):
                                if REGISTRY[name][2] or attempt==config.read_retries: raise
                                await asyncio.sleep(min(.2*(2**attempt),max(0,phase.remaining())))
                        if name in {"equipment","history","evaluation"} and isinstance(result,dict) and "error" not in result:
                            read_cache[cache_key]=result
                            read_calls[cache_key]=call["id"]
                    if not isinstance(result,dict): raise ValueError("工具未返回有效业务证据")
                except TimeoutError:
                    tool_seconds+=time.monotonic()-tool_started
                    trace.append({"tool":name,"arguments":arguments,"source":name,"status":"timeout","attempts":attempts,"duration_ms":round((time.monotonic()-tool_started)*1000),"result_summary":"工具超时，未重试仍可能运行的线程"})
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
                useful_progress=phase.credit(name,result,cached=cached,draft=REGISTRY[name][2])
                duration_ms=round((time.monotonic()-tool_started)*1000)
                tool_seconds+=time.monotonic()-tool_started
                trace.append({"useful_progress":useful_progress,"time_extension_seconds":config.progress_extension_seconds if useful_progress else 0,"evidence_id":result.get("evidence_id"),"attempts":attempts,"empty":result.get("empty",False),"duration_ms":duration_ms,"cached":cached,"tool":name,"arguments":arguments,"source":result.get("source",name),"data_time":result.get("data_time"),"data_version":result.get("data_version"),"business_revision":result.get("business_revision"),"model_version":result.get("model_version"),"result_summary":plain_answer(str(result["error"])) if "error" in result else result.get("message") or ("读取设备记录" if "devices" in result else "完成方案计算" if "strategies" in result else "读取业务证据"),"status":"error" if "error" in result else "success"})
                if on_progress and useful_progress:
                    on_progress(phase.snapshot(active=True),list(trace))
                if "error" not in result and result.get("proposal") and not cached: proposals.append(result["proposal"])
                model_result=model_evidence(name,result)
                messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(model_result,ensure_ascii=False,default=str,allow_nan=False,separators=(",",":"))})
            if deferred:
                messages.append({"role":"user","content":"本轮达到工具数量上限，以下工具尚未执行，需要时下一轮再请求："+json.dumps(deferred,ensure_ascii=False)})
            if round_cached==len(calls) and not deferred:
                force_final=True
                messages.append({"role":"user","content":"已重复读取相同证据，没有新数据进展。请基于现有证据给出最终分析，明确证据不足与未验证条件，不再重复调用工具。"})
    return stopped("已达到本轮分析上限。可查看已读取的证据，缩小设备范围后继续。")

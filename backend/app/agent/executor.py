"""Agent 执行器：基于 Function Calling 的多步推理循环。

与纯 RAG 的区别：
- RAG 是「一次检索 + 一次生成」的固定管道；
- Agent 让模型自主决定「调用哪个工具、调用几次」，可组合知识库检索、农事日历、
  气象查询、施肥与农药计算，形成多步推理链。

安全约束：
- 单次提问最多 MAX_STEPS 轮工具调用，防止无限循环；
- 单个工具异常不中断流程，错误会回传给模型自行处理；
- 所有工具结果都会写入对话记录，便于复盘。
"""
from __future__ import annotations

import json
import logging
import time

from app.agent.tools import registry
from app.config import settings
from app.core import guard, history, llm, prompts
from app.core.memory import history_for, memory

logger = logging.getLogger(__name__)

MAX_STEPS = 5

AGENT_SYSTEM_PROMPT = """你是「农技通」农业技术顾问，可以调用工具来解决用户问题。

工作方式：
1. 【强制】只要问题涉及任何农技事实（作物品种、播种、施肥、灌溉、病虫害、农药、养殖管理），
   必须先调用 search_knowledge 检索本地知识库，不得凭记忆直接作答。
   只有当检索结果为空时，才可以说明「知识库暂无相关内容」，再给出通用建议。
2. 涉及「什么时候做什么」调用 crop_calendar；涉及天气、能不能打药、是否冻害调用 get_weather。
3. 涉及施肥用量调用 calc_fertilizer；涉及农药兑水量调用 calc_dilution。
4. 用户描述症状（叶黄、卷曲、烂根、虫害）时调用 diagnose_symptom 做初判。
5. 一个工具不够就调用多个，可以从不同角度多次检索。
6. 综合所有工具结果后给出最终回答，不要罗列工具原始输出。

回答要求：
- 用简体中文，分点作答，400 字以内，不使用 Markdown 标题符号。
- 给出可执行建议：什么时候做、怎么做、用多少量、注意什么。
- 涉及农药必须提示按标签剂量、注意安全间隔期与轮换用药。
- 工具结果不足时直接说明缺什么信息，不要编造。
- 只回答农业相关问题。"""


def _tool_log_entry(name: str, args: dict, result: dict, elapsed_ms: int) -> dict:
    """构造一条工具调用轨迹记录。"""
    label = registry.get(name).label if registry.get(name) else name
    summary = result.get("summary") or result.get("error") or ""
    return {
        "name": name,
        "label": label,
        "args": args,
        "ok": bool(result.get("ok", True)),
        "summary": str(summary)[:200],
        "elapsed_ms": elapsed_ms,
    }


def _execute_tool(name: str, raw_args: str) -> tuple[dict, dict]:
    """执行单个工具，返回 (原始结果, 轨迹记录)。"""
    t0 = time.perf_counter()
    tool = registry.get(name)
    if tool is None:
        result = {"ok": False, "error": f"未知工具：{name}"}
        args: dict = {}
    else:
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}
            result = {"ok": False, "error": "参数不是合法 JSON"}
        else:
            result = tool.run(args)

    elapsed = int((time.perf_counter() - t0) * 1000)
    return result, _tool_log_entry(name, args, result, elapsed)


def _fallback_mock(question: str) -> dict:
    """无真实模型时的降级：直接调知识库检索，返回 mock 结果。"""
    from app.core import rag

    hits = rag.retrieve(question, top_k=settings.top_k)
    context = "\n".join(f"[{i+1}] {h['title']}：{h['content'][:200]}" for i, h in enumerate(hits))
    answer = (
        "【Agent 演示模式】当前未配置真实大模型密钥，Agent 无法进行自主推理。\n\n"
        f"已自动调用「农业知识库检索」工具，命中 {len(hits)} 条片段：\n\n"
        f"{context or '（知识库无命中）'}\n\n"
        "配置 .env 中的 DASHSCOPE_API_KEY 并重启后，Agent 将自主决定调用哪些工具、"
        "调用几次，并给出综合结论。"
    )
    return {
        "answer": answer,
        "sources": hits,
        "tool_calls": [
            {
                "name": "search_knowledge",
                "label": "农业知识库检索",
                "args": {"query": question},
                "ok": True,
                "summary": f"命中 {len(hits)} 条",
                "elapsed_ms": 0,
            }
        ],
        "blocked": False,
        "latency_ms": 0,
    }


def run_agent(question: str, session_id: str = "", save_record: bool = True) -> dict:
    """非流式 Agent 执行。"""
    t0 = time.perf_counter()
    q = (question or "").strip()

    if not q:
        return {"answer": "请输入你的问题后再提交。", "sources": [], "tool_calls": [],
                "blocked": True, "latency_ms": 0}

    # 领域拦截
    verdict = guard.check_question(q)
    if not verdict.allowed:
        latency = int((time.perf_counter() - t0) * 1000)
        if save_record:
            history.add(
                session_id=session_id or "anonymous", question=q,
                answer=prompts.REJECT_MESSAGE, latency_ms=latency, mode="agent", blocked=True,
            )
        return {"answer": prompts.REJECT_MESSAGE, "sources": [], "tool_calls": [],
                "blocked": True, "latency_ms": latency}

    # 无真实模型时降级为 Mock（不做自主推理，只调一次检索）
    try:
        client = llm.get_chat_client()
    except Exception:  # noqa: BLE001
        result = _fallback_mock(q)
        latency = int((time.perf_counter() - t0) * 1000)
        result["latency_ms"] = latency
        if session_id:
            memory.append(session_id, q, result["answer"])
        if save_record:
            history.add(
                session_id=session_id or "anonymous", question=q,
                answer=result["answer"], latency_ms=latency, mode="agent",
                sources=result["sources"], tool_calls=result["tool_calls"],
            )
        return result

    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(history_for(session_id))
    messages.append({"role": "user", "content": q})

    tool_logs: list[dict] = []
    collected_sources: list[dict] = []
    answer = ""

    for step in range(MAX_STEPS):
        try:
            resp = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=registry.schemas(),
                tool_choice="auto",
                temperature=0.3,
                max_tokens=1500,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Agent 模型调用失败：%s", exc)
            answer = f"模型调用失败：{exc}"
            break

        msg = resp.choices[0].message

        # 没有工具调用 -> 得到最终答案
        if not msg.tool_calls:
            answer = msg.content or ""
            break

        # 把助手的工具调用意图写回上下文
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        for tc in msg.tool_calls:
            result, log = _execute_tool(tc.function.name, tc.function.arguments)
            tool_logs.append(log)

            # 知识库检索结果同时作为「参考来源」返回给前端
            if tc.function.name == "search_knowledge" and result.get("results"):
                for r in result["results"]:
                    collected_sources.append(
                        {
                            "title": r.get("title", ""),
                            "category": r.get("category", "通用农技"),
                            "category_key": "general",
                            "source": r.get("title", ""),
                            "content": r.get("content", ""),
                            "score": round(1 - float(r.get("similarity", 0)), 4),
                        }
                    )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False)[:4000],
                }
            )

    # 达到步数上限仍未收敛，强制让模型总结
    if not answer and tool_logs:
        try:
            messages.append(
                {"role": "user", "content": "请基于以上工具结果，直接给出最终回答，不要再调用工具。"}
            )
            resp = client.chat.completions.create(
                model=settings.llm_model, messages=messages, temperature=0.3, max_tokens=1200
            )
            answer = resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            answer = f"生成总结失败：{exc}"

    if not answer:
        answer = "抱歉，本次未能生成有效回答，请换个问法或补充更多信息。"

    latency = int((time.perf_counter() - t0) * 1000)

    if session_id:
        memory.append(session_id, q, answer)
    if save_record:
        history.add(
            session_id=session_id or "anonymous", question=q, answer=answer,
            latency_ms=latency, mode="agent", sources=collected_sources, tool_calls=tool_logs,
        )

    return {
        "answer": answer,
        "sources": collected_sources,
        "tool_calls": tool_logs,
        "blocked": False,
        "latency_ms": latency,
    }


def run_agent_stream(question: str, session_id: str = ""):
    """流式 Agent 执行。

    事件序列：
        {"type": "tool_start", "data": {name,label,args}}
        {"type": "tool_end", "data": {name,ok,summary,elapsed_ms}}
        {"type": "sources", "data": [...]}
        {"type": "delta", "data": "..."}
        {"type": "done", "data": {latency_ms, tool_calls}}
    """
    t0 = time.perf_counter()
    q = (question or "").strip()

    if not q:
        yield {"type": "error", "data": "请输入你的问题后再提交。"}
        return

    verdict = guard.check_question(q)
    if not verdict.allowed:
        yield {"type": "sources", "data": []}
        yield {"type": "delta", "data": prompts.REJECT_MESSAGE}
        latency = int((time.perf_counter() - t0) * 1000)
        history.add(
            session_id=session_id or "anonymous", question=q,
            answer=prompts.REJECT_MESSAGE, latency_ms=latency, mode="agent", blocked=True,
        )
        yield {"type": "done", "data": {"latency_ms": latency, "blocked": True, "tool_calls": []}}
        return

    # 降级：无真实模型
    try:
        client = llm.get_chat_client()
    except Exception:  # noqa: BLE001
        result = _fallback_mock(q)
        yield {"type": "sources", "data": result["sources"]}
        for log in result["tool_calls"]:
            yield {"type": "tool_start", "data": {"name": log["name"], "label": log["label"], "args": log["args"]}}
            yield {"type": "tool_end", "data": {"name": log["name"], "ok": True, "summary": log["summary"], "elapsed_ms": 0}}
        text = result["answer"]
        for i in range(0, len(text), 24):
            yield {"type": "delta", "data": text[i : i + 24]}
        yield {"type": "done", "data": {"latency_ms": 0, "blocked": False, "tool_calls": result["tool_calls"]}}
        return

    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(history_for(session_id))
    messages.append({"role": "user", "content": q})

    tool_logs: list[dict] = []
    collected_sources: list[dict] = []
    answer = ""

    for _ in range(MAX_STEPS):
        try:
            resp = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=registry.schemas(),
                tool_choice="auto",
                temperature=0.3,
                max_tokens=1500,
            )
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "data": f"模型调用失败：{exc}"}
            return

        msg = resp.choices[0].message

        if not msg.tool_calls:
            answer = msg.content or ""
            break

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        for tc in msg.tool_calls:
            tool = registry.get(tc.function.name)
            try:
                preview_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                preview_args = {}

            yield {
                "type": "tool_start",
                "data": {
                    "name": tc.function.name,
                    "label": tool.label if tool else tc.function.name,
                    "args": preview_args,
                },
            }

            result, log = _execute_tool(tc.function.name, tc.function.arguments)
            tool_logs.append(log)

            yield {
                "type": "tool_end",
                "data": {
                    "name": tc.function.name,
                    "ok": log["ok"],
                    "summary": log["summary"],
                    "elapsed_ms": log["elapsed_ms"],
                },
            }

            if tc.function.name == "search_knowledge" and result.get("results"):
                for r in result["results"]:
                    collected_sources.append(
                        {
                            "title": r.get("title", ""),
                            "category": r.get("category", "通用农技"),
                            "category_key": "general",
                            "source": r.get("title", ""),
                            "content": r.get("content", ""),
                            "score": round(1 - float(r.get("similarity", 0)), 4),
                        }
                    )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False)[:4000],
                }
            )

    if collected_sources:
        yield {"type": "sources", "data": collected_sources}

    acc: list[str] = []

    if answer:
        # 循环内模型已给出最终答案，直接分块推送，不再多调一次模型
        for i in range(0, len(answer), 24):
            yield {"type": "delta", "data": answer[i : i + 24]}
        acc.append(answer)
    else:
        # 达到步数上限仍未收敛，让模型基于工具结果做最终总结
        if tool_logs:
            messages.append(
                {"role": "user", "content": "请基于以上工具结果，直接给出最终回答，不要再调用工具。"}
            )
        try:
            stream = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=1200,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    acc.append(delta.content)
                    yield {"type": "delta", "data": delta.content}
        except Exception as exc:  # noqa: BLE001
            err = f"\n\n[生成中断] {exc}"
            acc.append(err)
            yield {"type": "delta", "data": err}

    answer = "".join(acc) or "抱歉，本次未能生成有效回答。"
    latency = int((time.perf_counter() - t0) * 1000)

    if session_id:
        memory.append(session_id, q, answer)
    history.add(
        session_id=session_id or "anonymous", question=q, answer=answer,
        latency_ms=latency, mode="agent", sources=collected_sources, tool_calls=tool_logs,
    )

    yield {
        "type": "done",
        "data": {"latency_ms": latency, "blocked": False, "tool_calls": tool_logs},
    }

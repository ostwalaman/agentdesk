from __future__ import annotations

import time
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from agentops.evaluator import evaluate_response
from agentops.mcp_registry import call_tool
from agentops.observability import append_trace, estimate_cost, utc_iso
from config import get_openai_api_key, get_openai_model


class AgentOpsState(TypedDict, total=False):
    query: str
    thread_id: str
    expected_tool: str | None
    route: str
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: dict[str, Any]
    answer: str
    evaluation: dict[str, Any]
    trace: dict[str, Any]


def route_query(query: str) -> tuple[str, str, dict[str, Any]]:
    q = query.lower()
    if "create" in q and "task" in q:
        return "task_creation", "get_stale_opportunities", {"inactivity_days": 14, "limit": 5}
    if ("high revenue" in q or "high value" in q or "large account" in q or "big account" in q) and (
        "low activity" in q or "recent activity" in q or "stale" in q or "follow" in q or "contacted" in q
    ):
        return "account_activity", "high_revenue_low_activity", {"min_revenue": 1_000_000, "inactivity_days": 14, "limit": 5}
    if "no follow" in q and ("deal" in q or "opportunit" in q or "account" in q):
        return "stale_opportunities", "get_stale_opportunities", {"inactivity_days": 14, "limit": 5}
    if "stale" in q:
        if "email" in q or "draft" in q or "write" in q or "generate" in q:
            return "follow_up", "draft_follow_up", {"context": query}
        return "stale_opportunities", "get_stale_opportunities", {"inactivity_days": 14, "limit": 5}
    if "at risk" in q or "risky" in q or "risk" in q or "urgent" in q or "low probability" in q or "closing soon" in q:
        return "risk_analysis", "find_at_risk_deals", {"inactivity_days": 14, "limit": 5}
    if "no recent activity" in q and ("deal" in q or "opportunit" in q):
        return "stale_opportunities", "get_stale_opportunities", {"inactivity_days": 14, "limit": 5}
    if "forecast" in q or "expected revenue" in q or "weighted" in q:
        return "forecast", "forecast_revenue", {}
    if "pipeline" in q or "stage" in q:
        return "pipeline_health", "get_pipeline_health", {}
    if "draft" in q or "email" in q or "follow-up" in q or "follow up" in q:
        return "follow_up", "draft_follow_up", {"context": query}
    if ("account" in q and ("summarize" in q or "summary" in q or "health" in q)) or "summary of" in q:
        if " for " in q:
            account_name = query.split("for")[-1].strip()
        elif " of " in q:
            account_name = query.split("of")[-1].strip()
        else:
            account_name = query.replace("summarize", "").replace("summary", "").replace("account", "").replace("health", "").strip()
        return "account_summary", "summarize_account", {"account_name": account_name}
    return "metrics", "get_pipeline_health", {}


def router_node(state: AgentOpsState) -> AgentOpsState:
    route, tool_name, tool_args = route_query(state["query"])
    return {**state, "route": route, "tool_name": tool_name, "tool_args": tool_args}


def tool_node(state: AgentOpsState) -> AgentOpsState:
    start = time.perf_counter()
    result = call_tool(state["tool_name"], state.get("tool_args", {}))
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    success = "error" not in result
    tool_trace = {
        "name": state["tool_name"],
        "arguments": state.get("tool_args", {}),
        "latency_ms": latency_ms,
        "success": success,
        "result_preview": str(result)[:1200],
    }
    trace = state.get("trace", {})
    trace["tools"] = [tool_trace]
    return {**state, "tool_result": result, "trace": trace}


def _fallback_answer(state: AgentOpsState) -> str:
    tool_name = state["tool_name"]
    result = state["tool_result"]
    if tool_name == "find_at_risk_deals":
        deals = result.get("deals", [])
        if not deals:
            return "No at-risk open deals matched the current criteria."
        lines = [
            f"- {deal['name']} ({deal['account']}): ${deal['amount']:,.0f}, {deal['stage']}, {deal['probability']}% probability, risk score {deal['risk_score']}"
            for deal in deals[:5]
        ]
        return "Most at-risk deals:\n" + "\n".join(lines)
    if tool_name == "get_pipeline_health":
        stages = result.get("pipeline", {}).get("stages", [])
        lines = [f"- {stage['stage']}: {stage['count']} deals, ${stage['total_value']:,.0f}" for stage in stages[:8]]
        return "Pipeline health by stage:\n" + "\n".join(lines)
    if tool_name == "high_revenue_low_activity":
        rows = result.get("accounts", [])
        lines = [f"- {row['name']}: ${row['annual_revenue']:,.0f}, owner {row['owner']}, last activity {row['last_activity_at']}" for row in rows[:5]]
        return "High-revenue accounts with low recent activity:\n" + ("\n".join(lines) if lines else "None found.")
    if tool_name == "forecast_revenue":
        return f"Forecasted revenue is ${result.get('forecasted_revenue', 0):,.0f}; open opportunity value is ${result.get('open_opportunity_value', 0):,.0f}."
    return str(result)


def answer_node(state: AgentOpsState) -> AgentOpsState:
    api_key = get_openai_api_key()
    prompt_tokens = max(1, len(state["query"].split()) + len(str(state["tool_result"]).split()))
    completion_tokens = 0
    if not api_key:
        answer = _fallback_answer(state)
    else:
        llm = ChatOpenAI(
            model=get_openai_model(),
            temperature=0.1,
            max_tokens=500,
            timeout=20,
            max_retries=0,
            api_key=api_key,
        )
        messages = [
            SystemMessage(
                content=(
                    "You are AgentDesk Enterprise AgentOps. Answer only from the structured CRM tool result. "
                    "Use concise bullets and summarize at most five records. Include evidence such as amounts, "
                    "stages, owners, dates, and record names. Do not invent data. Finish with one short next-step."
                )
            ),
            HumanMessage(content=f"User query: {state['query']}\nTool called: {state['tool_name']}\nTool result: {state['tool_result']}"),
        ]
        try:
            response = llm.invoke(messages)
            answer = response.content if isinstance(response.content, str) else str(response.content)
            usage = getattr(response, "usage_metadata", None) or {}
            prompt_tokens = usage.get("input_tokens", prompt_tokens)
            completion_tokens = usage.get("output_tokens", max(1, len(answer.split())))
        except Exception:
            answer = _fallback_answer(state)
            completion_tokens = max(1, len(answer.split()))
    tokens = {"prompt": prompt_tokens, "completion": completion_tokens, "total": prompt_tokens + completion_tokens}
    trace = state.get("trace", {})
    trace["tokens"] = tokens
    trace["model"] = get_openai_model()
    trace["cost_usd"] = estimate_cost(get_openai_model(), prompt_tokens, completion_tokens)
    return {**state, "answer": answer, "trace": trace}


def evaluator_node(state: AgentOpsState) -> AgentOpsState:
    evaluation = evaluate_response(state["answer"], state["tool_result"], state.get("expected_tool"), state["tool_name"])
    trace = state.get("trace", {})
    trace["evaluation"] = evaluation
    return {**state, "evaluation": evaluation, "trace": trace}


def build_graph():
    graph = StateGraph(AgentOpsState)
    graph.add_node("router", router_node)
    graph.add_node("tool_selection_and_execution", tool_node)
    graph.add_node("answer_generation", answer_node)
    graph.add_node("evaluation_guardrail", evaluator_node)
    graph.set_entry_point("router")
    graph.add_edge("router", "tool_selection_and_execution")
    graph.add_edge("tool_selection_and_execution", "answer_generation")
    graph.add_edge("answer_generation", "evaluation_guardrail")
    graph.add_edge("evaluation_guardrail", END)
    return graph.compile()


GRAPH = build_graph()


async def run_agentops_query(query: str, thread_id: str, expected_tool: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    initial_trace = {"id": f"{int(time.time() * 1000)}-{thread_id}", "timestamp": utc_iso(), "query": query, "thread_id": thread_id}
    result = await GRAPH.ainvoke({"query": query, "thread_id": thread_id, "expected_tool": expected_tool, "trace": initial_trace})
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    trace = result.get("trace", {})
    trace.update(
        {
            "route": result.get("route"),
            "latency_ms": latency_ms,
            "response": result.get("answer"),
            "cost_usd": trace.get("cost_usd", 0),
            "tokens": trace.get("tokens", {"prompt": 0, "completion": 0, "total": 0}),
        }
    )
    append_trace(trace)
    return {
        "response": result.get("answer", ""),
        "tools_used": [result.get("tool_name")],
        "trace": trace,
        "evaluation": result.get("evaluation"),
    }

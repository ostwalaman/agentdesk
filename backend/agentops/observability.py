from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parents[1] / "agentops_logs"
TRACE_PATH = LOG_DIR / "traces.jsonl"
EVAL_PATH = LOG_DIR / "eval_results.json"

MODEL_PRICING_PER_1K = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
}


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING_PER_1K.get(model, MODEL_PRICING_PER_1K["gpt-4o-mini"])
    return round((prompt_tokens / 1000 * pricing["input"]) + (completion_tokens / 1000 * pricing["output"]), 6)


def append_trace(trace: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with TRACE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, default=str) + "\n")


def load_traces(limit: int | None = None) -> list[dict[str, Any]]:
    if not TRACE_PATH.exists():
        return []
    lines = TRACE_PATH.read_text(encoding="utf-8").splitlines()
    if limit:
        lines = lines[-limit:]
    traces = []
    for line in lines:
        try:
            traces.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return traces


def aggregate_metrics() -> dict[str, Any]:
    traces = load_traces(limit=50)
    latencies = [float(trace.get("latency_ms", 0)) for trace in traces]
    tool_calls = [tool for trace in traces for tool in trace.get("tools", [])]
    eval_scores = [float(trace.get("evaluation", {}).get("groundedness_score", 0)) for trace in traces]
    eval_passes = [bool(trace.get("evaluation", {}).get("passed", False)) for trace in traces]
    costs = [float(trace.get("cost_usd", 0)) for trace in traces]
    token_counts = [int(trace.get("tokens", {}).get("total", 0)) for trace in traces]
    failed_tool_calls = [tool for tool in tool_calls if not tool.get("success")]
    p95 = statistics.quantiles(latencies, n=20)[-1] if len(latencies) >= 2 else (latencies[0] if latencies else 0)
    return {
        "request_count": len(traces),
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0,
        "p95_latency_ms": round(p95, 2),
        "avg_tokens_per_request": round(statistics.mean(token_counts), 2) if token_counts else 0,
        "avg_cost_per_request_usd": round(statistics.mean(costs), 6) if costs else 0,
        "total_cost_usd": round(sum(costs), 6),
        "tool_call_count": len(tool_calls),
        "tool_success_rate": round((len(tool_calls) - len(failed_tool_calls)) / len(tool_calls), 3) if tool_calls else 1,
        "failed_tool_calls": len(failed_tool_calls),
        "evaluation_pass_rate": round(sum(eval_passes) / len(eval_passes), 3) if eval_passes else 0,
        "avg_groundedness_score": round(statistics.mean(eval_scores), 3) if eval_scores else 0,
        "recent_traces": load_traces(limit=10),
    }


def save_eval_results(results: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_PATH.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


def load_eval_results() -> dict[str, Any]:
    if not EVAL_PATH.exists():
        return {"runs": [], "summary": {"cases": 0, "pass_rate": 0}}
    return json.loads(EVAL_PATH.read_text(encoding="utf-8"))

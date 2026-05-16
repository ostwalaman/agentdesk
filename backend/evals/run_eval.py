from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from agentops.graph import run_agentops_query
from agentops.observability import save_eval_results

CASES_PATH = Path(__file__).resolve().parent / "eval_cases.jsonl"


async def run_eval() -> dict:
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    started = time.perf_counter()
    for idx, case in enumerate(cases, start=1):
        print(f"[{idx}/{len(cases)}] {case['query']}", flush=True)
        try:
            result = await asyncio.wait_for(
                run_agentops_query(case["query"], thread_id=f"eval-{idx}", expected_tool=case.get("expected_tool")),
                timeout=35,
            )
        except Exception as exc:
            result = {
                "tools_used": [None],
                "evaluation": {"passed": False, "correct_tool": False, "groundedness_score": 0},
                "trace": {"latency_ms": 35000, "cost_usd": 0, "error": str(exc)},
            }
        evaluation = result.get("evaluation") or {}
        trace = result.get("trace") or {}
        results.append(
            {
                "query": case["query"],
                "expected_tool": case.get("expected_tool"),
                "actual_tool": result.get("tools_used", [None])[0],
                "passed": evaluation.get("passed", False),
                "correct_tool": evaluation.get("correct_tool", False),
                "groundedness_score": evaluation.get("groundedness_score", 0),
                "latency_ms": trace.get("latency_ms", 0),
                "cost_usd": trace.get("cost_usd", 0),
            }
        )
    summary = {
        "cases": len(results),
        "pass_rate": round(sum(1 for row in results if row["passed"]) / len(results), 3) if results else 0,
        "tool_accuracy": round(sum(1 for row in results if row["correct_tool"]) / len(results), 3) if results else 0,
        "avg_groundedness": round(sum(row["groundedness_score"] for row in results) / len(results), 3) if results else 0,
        "avg_latency_ms": round(sum(row["latency_ms"] for row in results) / len(results), 2) if results else 0,
        "total_cost_usd": round(sum(row["cost_usd"] for row in results), 6),
        "runtime_seconds": round(time.perf_counter() - started, 2),
    }
    payload = {"summary": summary, "runs": results}
    save_eval_results(payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_eval()), indent=2))

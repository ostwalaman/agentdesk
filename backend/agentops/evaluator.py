from __future__ import annotations

from typing import Any


def evaluate_response(answer: str, tool_result: dict[str, Any] | list[Any], expected_tool: str | None, actual_tool: str) -> dict[str, Any]:
    serialized = str(tool_result).lower()
    answer_lower = answer.lower()
    has_numbers = any(char.isdigit() for char in answer)
    grounded_terms = 0
    for token in answer_lower.replace("$", " ").replace(",", " ").split():
        if len(token) >= 4 and token in serialized:
            grounded_terms += 1
    groundedness_score = min(1.0, 0.45 + grounded_terms / 20 + (0.15 if has_numbers else 0))
    correct_tool = expected_tool is None or expected_tool == actual_tool
    passed = correct_tool and groundedness_score >= 0.6
    return {
        "passed": passed,
        "correct_tool": correct_tool,
        "expected_tool": expected_tool,
        "actual_tool": actual_tool,
        "groundedness_score": round(groundedness_score, 3),
        "notes": "Deterministic overlap check against structured CRM tool output.",
    }

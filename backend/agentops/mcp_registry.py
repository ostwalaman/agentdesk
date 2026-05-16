from __future__ import annotations

from typing import Any

from agentops.crm_tools import TOOL_REGISTRY

MCP_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_pipeline_health",
        "description": "Summarize pipeline health by stage with totals, average probability, and forecast.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "find_at_risk_deals",
        "description": "Find open opportunities at risk due to low probability, inactivity, or close-date urgency.",
        "input_schema": {
            "type": "object",
            "properties": {"stage": {"type": "string"}, "inactivity_days": {"type": "integer"}, "limit": {"type": "integer"}},
            "required": [],
        },
    },
    {
        "name": "summarize_account",
        "description": "Summarize an account by fuzzy account name.",
        "input_schema": {"type": "object", "properties": {"account_name": {"type": "string"}}, "required": ["account_name"]},
    },
    {
        "name": "draft_follow_up",
        "description": "Draft a follow-up email for an opportunity.",
        "input_schema": {"type": "object", "properties": {"opportunity_id": {"type": "integer"}, "context": {"type": "string"}}, "required": []},
    },
    {
        "name": "create_task",
        "description": "Create a task for the primary contact on an account.",
        "input_schema": {
            "type": "object",
            "properties": {"account_id": {"type": "integer"}, "task_text": {"type": "string"}, "due_days": {"type": "integer"}},
            "required": ["account_id", "task_text"],
        },
    },
    {
        "name": "forecast_revenue",
        "description": "Calculate forecasted revenue and pipeline totals.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_stale_opportunities",
        "description": "Find open opportunities with no recent activity.",
        "input_schema": {"type": "object", "properties": {"inactivity_days": {"type": "integer"}, "limit": {"type": "integer"}}, "required": []},
    },
    {
        "name": "high_revenue_low_activity",
        "description": "Find high-revenue accounts with low recent activity.",
        "input_schema": {
            "type": "object",
            "properties": {"min_revenue": {"type": "number"}, "inactivity_days": {"type": "integer"}, "limit": {"type": "integer"}},
            "required": [],
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {name}"}
    return TOOL_REGISTRY[name](**(arguments or {}))

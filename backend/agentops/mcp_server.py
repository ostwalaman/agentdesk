from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from agentops.crm_tools import (
    create_task_for_account,
    draft_follow_up as draft_follow_up_tool,
    find_at_risk_deals as find_at_risk_deals_tool,
    forecast_revenue as forecast_revenue_tool,
    get_pipeline_health as get_pipeline_health_tool,
    summarize_account as summarize_account_tool,
)


def _csv_env(name: str, defaults: list[str]) -> list[str]:
    configured = [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]
    return configured or defaults


allowed_hosts = _csv_env("MCP_ALLOWED_HOSTS", ["127.0.0.1:*", "localhost:*"])
allowed_origins = _csv_env("MCP_ALLOWED_ORIGINS", ["http://127.0.0.1:*", "http://localhost:*"])


mcp = FastMCP(
    "AgentDesk CRM MCP Server",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    ),
)


@mcp.tool()
def get_pipeline_health() -> dict[str, Any]:
    """Summarize CRM pipeline health by stage with counts, value, probability, and forecast."""
    return get_pipeline_health_tool()


@mcp.tool()
def find_at_risk_deals(stage: str | None = None, inactivity_days: int = 14, limit: int = 5) -> dict[str, Any]:
    """Find open CRM opportunities at risk because of low probability, close-date urgency, or inactivity."""
    return find_at_risk_deals_tool(stage=stage, inactivity_days=inactivity_days, limit=limit)


@mcp.tool()
def summarize_account(account_name: str) -> dict[str, Any]:
    """Fuzzy-search and summarize a CRM account, including health, owner, activity, and open opportunities."""
    return summarize_account_tool(account_name=account_name)


@mcp.tool()
def draft_follow_up(opportunity_id: int | None = None, context: str = "") -> dict[str, Any]:
    """Draft a professional follow-up email for an open CRM opportunity using CRM context."""
    return draft_follow_up_tool(opportunity_id=opportunity_id, context=context)


@mcp.tool()
def create_task(account_id: int, task_text: str, due_days: int = 3) -> dict[str, Any]:
    """Create an open follow-up task for the primary contact on a CRM account."""
    return create_task_for_account(account_id=account_id, task_text=task_text, due_days=due_days)


@mcp.tool()
def forecast_revenue() -> dict[str, Any]:
    """Calculate total opportunity value, open opportunity value, weighted forecast, and average probability."""
    return forecast_revenue_tool()

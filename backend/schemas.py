from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    thread_id: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    response: str
    tools_used: list[str]


class AccountOut(BaseModel):
    id: int
    name: str
    industry: str
    annual_revenue: float
    account_health: str
    owner: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineStageSummary(BaseModel):
    stage: str
    count: int
    total_value: float
    average_probability: float
    forecasted_revenue: float


class PipelineSummary(BaseModel):
    stages: list[PipelineStageSummary]
    total_pipeline: float
    total_forecasted_revenue: float


class ToolResult(BaseModel):
    result: dict[str, Any] | list[dict[str, Any]] | str

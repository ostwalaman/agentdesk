from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from agentops.graph import run_agentops_query
from agentops.mcp_registry import MCP_TOOL_DEFINITIONS, call_tool
from agentops.mcp_server import mcp
from agentops.observability import aggregate_metrics, append_trace, load_eval_results, load_traces, utc_iso
from config import get_openai_key_debug
from csv_import import import_multiple_crm_csv
from database import get_db, init_db
from models import Account
from salesforce_sync import sync_salesforce_to_sqlite
from schemas import AccountOut, ChatRequest, ChatResponse
from tools import get_at_risk_deals, get_basic_crm_metrics, get_pipeline_summary


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(seed=True)
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AgentDesk API", version="1.0.0", lifespan=lifespan)
api_router = APIRouter()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api_router.get("/debug/openai-key")
def debug_openai_key():
    return get_openai_key_debug()


@api_router.get("/metrics")
def metrics():
    return {"crm": get_basic_crm_metrics.invoke({}), "agentops": aggregate_metrics()}


@api_router.get("/traces/recent")
def recent_traces(limit: int = 10):
    return {"traces": load_traces(limit=limit)}


@api_router.get("/eval/results")
def eval_results():
    return load_eval_results()


@api_router.post("/eval/run")
async def run_eval_endpoint():
    from evals.run_eval import run_eval

    return await run_eval()


@api_router.get("/tools")
def tool_definitions():
    return {"tools": MCP_TOOL_DEFINITIONS}


@api_router.post("/tools/{tool_name}")
def call_registered_tool(tool_name: str, arguments: dict[str, Any] | None = None):
    return call_tool(tool_name, arguments or {})


def _money(value: float) -> str:
    return f"${value:,.0f}"


def answer_basic_metric_question(message: str) -> ChatResponse | None:
    metrics = get_basic_crm_metrics.invoke({})
    if "error" in metrics:
        return None

    if any(phrase in message for phrase in ("how many", "number of", "count of")):
        wants_accounts = "account" in message
        wants_opportunities = any(word in message for word in ("opportunit", "deal"))
        wants_contacts = "contact" in message
        wants_tasks = "task" in message
        if sum([wants_accounts, wants_opportunities, wants_contacts, wants_tasks]) > 1:
            lines = []
            if wants_accounts:
                lines.append(f"- Accounts: **{metrics['accounts']}**")
            if wants_opportunities:
                lines.append(
                    f"- Opportunities: **{metrics['opportunities']}** total, **{metrics['open_opportunities']}** open"
                )
            if wants_contacts:
                lines.append(f"- Contacts: **{metrics['contacts']}**")
            if wants_tasks:
                lines.append(f"- Tasks: **{metrics['tasks']}**")
            return ChatResponse(response="CRM record counts:\n" + "\n".join(lines), tools_used=["get_basic_crm_metrics"])
        if "account" in message:
            return ChatResponse(response=f"You have **{metrics['accounts']} accounts** in total.", tools_used=["get_basic_crm_metrics"])
        if "contact" in message:
            return ChatResponse(response=f"You have **{metrics['contacts']} contacts** in total.", tools_used=["get_basic_crm_metrics"])
        if any(word in message for word in ("opportunit", "deal")):
            return ChatResponse(
                response=f"You have **{metrics['opportunities']} opportunities** in total, including **{metrics['open_opportunities']} open opportunities**.",
                tools_used=["get_basic_crm_metrics"],
            )
        if "task" in message:
            return ChatResponse(response=f"You have **{metrics['tasks']} tasks** in total.", tools_used=["get_basic_crm_metrics"])

    if any(word in message for word in ("total", "sum")):
        if "account" in message and any(word in message for word in ("amount", "revenue", "value")):
            return ChatResponse(
                response=f"Total annual revenue across all accounts is **{_money(metrics['total_account_annual_revenue'])}**.",
                tools_used=["get_basic_crm_metrics"],
            )
        if any(word in message for word in ("pipeline", "opportunit", "deal")):
            return ChatResponse(
                response=(
                    f"Total opportunity value is **{_money(metrics['total_opportunity_value'])}**. "
                    f"Open opportunity value is **{_money(metrics['open_opportunity_value'])}**. "
                    f"Forecasted revenue is **{_money(metrics['total_forecasted_revenue'])}**."
                ),
                tools_used=["get_basic_crm_metrics"],
            )

    if "average" in message or "avg" in message:
        if "account" in message and "revenue" in message:
            return ChatResponse(
                response=f"Average annual revenue per account is **{_money(metrics['average_account_annual_revenue'])}**.",
                tools_used=["get_basic_crm_metrics"],
            )
        if any(word in message for word in ("deal", "opportunit")):
            return ChatResponse(
                response=(
                    f"Average opportunity amount is **{_money(metrics['average_opportunity_amount'])}**. "
                    f"Average probability is **{metrics['average_probability']}%**."
                ),
                tools_used=["get_basic_crm_metrics"],
            )

    if any(word in message for word in ("largest", "biggest", "top", "highest", "max", "maximum")):
        if "account" in message:
            top = metrics["top_account_by_revenue"]
            if top:
                return ChatResponse(
                    response=f"Top account by annual revenue is **{top['name']}** at **{_money(top['annual_revenue'])}**.",
                    tools_used=["get_basic_crm_metrics"],
                )
        if any(word in message for word in ("deal", "opportunit")):
            top = metrics["largest_opportunity"]
            if top:
                return ChatResponse(
                    response=f"Largest opportunity is **{top['name']}** for **{top['account']}**, worth **{_money(top['amount'])}** in stage **{top['stage']}**.",
                    tools_used=["get_basic_crm_metrics"],
                )

    if "health" in message:
        lines = [f"- {item['name']}: {item['count']}" for item in metrics["accounts_by_health"]]
        return ChatResponse(response="Account health breakdown:\n" + "\n".join(lines), tools_used=["get_basic_crm_metrics"])

    if "industry" in message or "sector" in message:
        lines = [f"- {item['name']}: {item['count']} accounts" for item in metrics["accounts_by_industry"][:10]]
        return ChatResponse(response="Top industries by account count:\n" + "\n".join(lines), tools_used=["get_basic_crm_metrics"])

    if "owner" in message or "sales rep" in message or "rep" in message:
        lines = [f"- {item['name']}: {item['count']} accounts" for item in metrics["accounts_by_owner"][:10]]
        return ChatResponse(response="Accounts by owner:\n" + "\n".join(lines), tools_used=["get_basic_crm_metrics"])

    if "stage" in message:
        lines = [
            f"- {item['name']}: {item['count']} opportunities, {_money(item['total_value'])}"
            for item in metrics["opportunities_by_stage"]
        ]
        return ChatResponse(response="Opportunities by stage:\n" + "\n".join(lines), tools_used=["get_basic_crm_metrics"])

    if "won" in message or "lost" in message:
        return ChatResponse(
            response=(
                f"Closed won: **{metrics['closed_won_opportunities']} opportunities**, "
                f"**{_money(metrics['closed_won_value'])}**. "
                f"Closed lost: **{metrics['closed_lost_opportunities']} opportunities**, "
                f"**{_money(metrics['closed_lost_value'])}**."
            ),
            tools_used=["get_basic_crm_metrics"],
        )

    return None


@api_router.post("/sync/salesforce")
def sync_salesforce():
    try:
        return sync_salesforce_to_sqlite()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Salesforce sync failed: {exc}") from exc


@api_router.post("/import/csv")
async def import_csv(files: list[UploadFile] = File(...)):
    csv_files: dict[str, str] = {}
    for file in files:
        contents = await file.read()
        csv_files[file.filename or "upload.csv"] = contents.decode("utf-8-sig")
    result = import_multiple_crm_csv(csv_files)
    return {"filenames": list(csv_files), **result}


@api_router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    message = request.message.lower()
    basic_answer = answer_basic_metric_question(message)
    if basic_answer:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        prompt_tokens = max(1, len(request.message.split()))
        completion_tokens = max(1, len(basic_answer.response.split()))
        evaluation = {
            "passed": True,
            "correct_tool": True,
            "expected_tool": "get_basic_crm_metrics",
            "actual_tool": "get_basic_crm_metrics",
            "groundedness_score": 1.0,
            "notes": "Deterministic CRM metric answer generated from structured metrics.",
        }
        trace = {
            "id": f"{int(time.time() * 1000)}-{request.thread_id}",
            "timestamp": utc_iso(),
            "query": request.message,
            "thread_id": request.thread_id,
            "route": "basic_metrics",
            "latency_ms": latency_ms,
            "response": basic_answer.response,
            "tools": [
                {
                    "name": "get_basic_crm_metrics",
                    "arguments": {},
                    "latency_ms": latency_ms,
                    "success": True,
                    "result_preview": basic_answer.response[:1200],
                }
            ],
            "tokens": {"prompt": prompt_tokens, "completion": completion_tokens, "total": prompt_tokens + completion_tokens},
            "model": "deterministic",
            "cost_usd": 0,
            "evaluation": evaluation,
        }
        append_trace(trace)
        return ChatResponse(
            response=basic_answer.response,
            tools_used=basic_answer.tools_used,
            trace=trace,
            evaluation=evaluation,
        )
    result = await run_agentops_query(request.message, request.thread_id)
    return ChatResponse(
        response=result["response"],
        tools_used=result["tools_used"],
        trace=result.get("trace"),
        evaluation=result.get("evaluation"),
    )


@api_router.get("/pipeline")
def pipeline():
    return get_pipeline_summary.invoke({})


@api_router.get("/accounts", response_model=list[AccountOut])
def accounts(db: Session = Depends(get_db)) -> list[Account]:
    return db.query(Account).order_by(Account.name.asc()).all()


@api_router.get("/crm/accounts", response_model=list[AccountOut])
def crm_accounts(db: Session = Depends(get_db)) -> list[Account]:
    return db.query(Account).order_by(Account.name.asc()).all()


@api_router.get("/crm/opportunities")
def crm_opportunities(db: Session = Depends(get_db)):
    from models import Opportunity

    rows = db.query(Opportunity).order_by(Opportunity.close_date.asc()).limit(500).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "stage": row.stage,
            "amount": row.amount,
            "close_date": row.close_date.date().isoformat(),
            "probability": row.probability,
            "account_id": row.account_id,
        }
        for row in rows
    ]


@api_router.get("/deals/at-risk")
def at_risk_deals():
    return get_at_risk_deals.invoke({})


app.include_router(api_router)
app.include_router(api_router, prefix="/api")


@app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp_redirect():
    return RedirectResponse(url="/mcp/", status_code=307)


app.mount("/mcp", mcp.streamable_http_app())


BACKEND_DIR = Path(__file__).resolve().parent
STATIC_DIR = BACKEND_DIR / "static"
LOCAL_FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
FRONTEND_DIST = STATIC_DIR if STATIC_DIR.exists() else LOCAL_FRONTEND_DIST

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if full_path.startswith(("api/", "mcp/")):
        raise HTTPException(status_code=404, detail="Not found")
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend build not found. Run `npm run build` in frontend.")

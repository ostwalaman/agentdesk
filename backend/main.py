from __future__ import annotations

from fastapi import Depends, FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from agent import run_agent
from config import get_openai_key_debug
from csv_import import import_multiple_crm_csv
from database import get_db, init_db
from models import Account
from salesforce_sync import sync_salesforce_to_sqlite
from schemas import AccountOut, ChatRequest, ChatResponse
from tools import get_at_risk_deals, get_basic_crm_metrics, get_crm_counts, get_crm_totals, get_pipeline_summary

app = FastAPI(title="AgentDesk API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db(seed=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/openai-key")
def debug_openai_key():
    return get_openai_key_debug()


@app.get("/metrics")
def metrics():
    return get_basic_crm_metrics.invoke({})


def _money(value: float) -> str:
    return f"${value:,.0f}"


def answer_basic_metric_question(message: str) -> ChatResponse | None:
    metrics = get_basic_crm_metrics.invoke({})
    if "error" in metrics:
        return None

    if any(phrase in message for phrase in ("how many", "number of", "count of")):
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


@app.post("/sync/salesforce")
def sync_salesforce():
    return sync_salesforce_to_sqlite()


@app.post("/import/csv")
async def import_csv(files: list[UploadFile] = File(...)):
    csv_files: dict[str, str] = {}
    for file in files:
        contents = await file.read()
        csv_files[file.filename or "upload.csv"] = contents.decode("utf-8-sig")
    result = import_multiple_crm_csv(csv_files)
    return {"filenames": list(csv_files), **result}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = request.message.lower()
    basic_answer = answer_basic_metric_question(message)
    if basic_answer:
        return basic_answer
    result = await run_agent(request.message, request.thread_id)
    return ChatResponse(response=result["response"], tools_used=result["tools_used"])


@app.get("/pipeline")
def pipeline():
    return get_pipeline_summary.invoke({})


@app.get("/accounts", response_model=list[AccountOut])
def accounts(db: Session = Depends(get_db)) -> list[Account]:
    return db.query(Account).order_by(Account.name.asc()).all()


@app.get("/deals/at-risk")
def at_risk_deals():
    return get_at_risk_deals.invoke({})

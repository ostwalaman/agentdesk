from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.tools import tool
from openai import OpenAI
from rapidfuzz import fuzz, process
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from config import get_openai_api_key, get_openai_model
from database import SessionLocal
from models import Account, Contact, Opportunity, Task
from salesforce_client import get_salesforce_client


def _iso(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


def _money(value: float) -> float:
    return round(float(value or 0), 2)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _find_account(db, account_name: str) -> tuple[Account | None, str | None, int | None]:
    accounts = db.query(Account).all()
    if not accounts:
        return None, None, None
    choices = {account.name: account for account in accounts}
    match = process.extractOne(account_name, choices.keys(), scorer=fuzz.WRatio)
    if not match:
        return None, None, None
    name, score, _ = match
    return choices[name], name, int(score)


@tool
def get_account_summary(account_name: str) -> dict[str, Any]:
    """Find an account by fuzzy name match and return account details, open opportunities, and the most recent contact date."""
    try:
        with SessionLocal() as db:
            account, matched_name, score = _find_account(db, account_name)
            if not account:
                return {"error": "No accounts were found in the CRM database."}

            open_opportunities = (
                db.query(Opportunity)
                .filter(
                    Opportunity.account_id == account.id,
                    Opportunity.stage.notin_(["Closed Won", "Closed Lost"]),
                )
                .order_by(Opportunity.close_date.asc())
                .all()
            )
            last_contacted = (
                db.query(func.max(Contact.last_contacted_at))
                .filter(Contact.account_id == account.id)
                .scalar()
            )

            return {
                "matched_account": matched_name,
                "match_score": score,
                "closest_match_used": matched_name != account_name,
                "account": {
                    "id": account.id,
                    "name": account.name,
                    "industry": account.industry,
                    "annual_revenue": _money(account.annual_revenue),
                    "account_health": account.account_health,
                    "owner": account.owner,
                    "created_at": _iso(account.created_at),
                },
                "last_contacted_at": _iso(last_contacted),
                "open_opportunities": [
                    {
                        "id": opp.id,
                        "name": opp.name,
                        "stage": opp.stage,
                        "amount": _money(opp.amount),
                        "close_date": _iso(opp.close_date),
                        "probability": opp.probability,
                    }
                    for opp in open_opportunities
                ],
            }
    except Exception as exc:
        return {"error": f"Could not retrieve account summary: {exc}"}


@tool
def get_at_risk_deals() -> list[dict[str, Any]] | dict[str, str]:
    """Return open deals closing within 30 days with probability below 50 percent, ranked by urgency and deal amount."""
    try:
        today = _utc_now()
        cutoff = today + timedelta(days=30)
        with SessionLocal() as db:
            deals = (
                db.query(Opportunity)
                .options(joinedload(Opportunity.account), joinedload(Opportunity.contact))
                .filter(
                    Opportunity.close_date >= today,
                    Opportunity.close_date < cutoff,
                    Opportunity.stage.notin_(["Closed Won", "Closed Lost"]),
                    Opportunity.probability < 50,
                )
                .order_by(Opportunity.close_date.asc(), Opportunity.amount.desc())
                .all()
            )
            return [
                {
                    "opportunity_id": deal.id,
                    "opportunity": deal.name,
                    "account": deal.account.name,
                    "contact": deal.contact.name,
                    "stage": deal.stage,
                    "amount": _money(deal.amount),
                    "probability": deal.probability,
                    "close_date": _iso(deal.close_date),
                    "days_left": max((deal.close_date.date() - today.date()).days, 0),
                    "next_step": "Confirm decision process and create a mutual close plan.",
                }
                for deal in deals
            ]
    except Exception as exc:
        return {"error": f"Could not retrieve at-risk deals: {exc}"}


@tool
def draft_followup_email(contact_id: int, context: str = "") -> dict[str, str]:
    """Draft a personalized professional follow-up email for a CRM contact using their company and open opportunity context."""
    try:
        with SessionLocal() as db:
            contact = (
                db.query(Contact)
                .options(joinedload(Contact.account), joinedload(Contact.opportunities))
                .filter(Contact.id == contact_id)
                .one_or_none()
            )
            if not contact:
                return {"error": f"Contact id {contact_id} was not found."}

            open_opps = [opp for opp in contact.opportunities if opp.stage not in ["Closed Won", "Closed Lost"]]
            opportunity_context = "\n".join(
                f"- {opp.name}: {opp.stage}, ${opp.amount:,.0f}, closes {_iso(opp.close_date)}, {opp.probability}% probability"
                for opp in open_opps
            ) or "- No open opportunities"

            prompt = f"""
Draft a concise B2B sales follow-up email.

Contact: {contact.name}
Company: {contact.account.name}
Industry: {contact.account.industry}
Account health: {contact.account.account_health}
Last contacted: {_iso(contact.last_contacted_at)}
Open opportunities:
{opportunity_context}
Sales rep context: {context or "No extra context provided."}

Return exactly:
Subject: <subject>
Body:
<email body>
""".strip()

            api_key = get_openai_api_key()
            if not api_key:
                return {
                    "subject": f"Following up on next steps with {contact.account.name}",
                    "body": (
                        f"Hi {contact.name.split()[0]},\n\n"
                        f"I wanted to follow up on our recent conversation and see how your team is thinking about next steps. "
                        f"Based on the current priorities at {contact.account.name}, it would be useful to align on timeline, stakeholders, "
                        "and any remaining questions we can help answer.\n\n"
                        "Would you be open to a brief call this week to confirm the path forward?\n\n"
                        "Best,\nAgentDesk"
                    ),
                    "note": "OPENAI_API_KEY is not set, so AgentDesk returned a deterministic local draft.",
                }

            client = OpenAI(api_key=api_key)
            completion = client.chat.completions.create(
                model=get_openai_model(),
                temperature=0.4,
                max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            )
            text = completion.choices[0].message.content or ""
            subject = "Follow-up on next steps"
            body = text
            if "Subject:" in text and "Body:" in text:
                subject_part, body_part = text.split("Body:", 1)
                subject = subject_part.replace("Subject:", "").strip()
                body = body_part.strip()
            return {"subject": subject, "body": body}
    except Exception as exc:
        return {"error": f"Could not draft follow-up email: {exc}"}


@tool
def create_task(contact_id: int, title: str, due_days: int) -> dict[str, Any]:
    """Create an open CRM task for a contact due a given number of days from today and return the new task id and due date."""
    try:
        due_days = max(int(due_days), 0)
        with SessionLocal() as db:
            contact = db.query(Contact).filter(Contact.id == contact_id).one_or_none()
            if not contact:
                return {"error": f"Contact id {contact_id} was not found."}
            open_opp = (
                db.query(Opportunity)
                .filter(
                    Opportunity.contact_id == contact_id,
                    Opportunity.stage.notin_(["Closed Won", "Closed Lost"]),
                )
                .order_by(Opportunity.close_date.asc())
                .first()
            )
            task = Task(
                contact_id=contact_id,
                opportunity_id=open_opp.id if open_opp else None,
                title=title,
                due_date=_utc_now() + timedelta(days=due_days),
                status="Open",
                created_at=_utc_now(),
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            salesforce_result: dict[str, Any] = {"created": False}
            if contact.salesforce_id:
                try:
                    sf = get_salesforce_client()
                    payload = {
                        "WhoId": contact.salesforce_id,
                        "Subject": title,
                        "ActivityDate": task.due_date.date().isoformat(),
                        "Status": "Not Started",
                    }
                    if open_opp and open_opp.salesforce_id:
                        payload["WhatId"] = open_opp.salesforce_id
                    created = sf.Task.create(payload)
                    task.salesforce_id = created.get("id")
                    db.commit()
                    salesforce_result = {"created": True, "salesforce_id": task.salesforce_id}
                except Exception as exc:
                    salesforce_result = {"created": False, "error": str(exc)}

            return {
                "task_id": task.id,
                "salesforce": salesforce_result,
                "contact_id": contact.id,
                "contact": contact.name,
                "title": task.title,
                "due_date": _iso(task.due_date),
                "status": task.status,
                "message": f"Created task {task.id} for {contact.name}, due {_iso(task.due_date)}.",
            }
    except Exception as exc:
        return {"error": f"Could not create task: {exc}"}


@tool
def get_crm_counts() -> dict[str, Any]:
    """Return total CRM record counts for accounts, contacts, opportunities, tasks, and open opportunities."""
    try:
        with SessionLocal() as db:
            open_opportunities = (
                db.query(func.count(Opportunity.id))
                .filter(Opportunity.stage.notin_(["Closed Won", "Closed Lost"]))
                .scalar()
            )
            return {
                "accounts": db.query(func.count(Account.id)).scalar() or 0,
                "contacts": db.query(func.count(Contact.id)).scalar() or 0,
                "opportunities": db.query(func.count(Opportunity.id)).scalar() or 0,
                "open_opportunities": open_opportunities or 0,
                "tasks": db.query(func.count(Task.id)).scalar() or 0,
            }
    except Exception as exc:
        return {"error": f"Could not retrieve CRM counts: {exc}"}


@tool
def get_crm_totals() -> dict[str, Any]:
    """Return basic CRM monetary totals including account annual revenue, total opportunity value, and forecasted revenue."""
    try:
        with SessionLocal() as db:
            total_account_revenue = db.query(func.sum(Account.annual_revenue)).scalar() or 0
            total_opportunity_value = db.query(func.sum(Opportunity.amount)).scalar() or 0
            total_forecasted_revenue = (
                db.query(func.sum(Opportunity.amount * Opportunity.probability / 100.0)).scalar() or 0
            )
            open_opportunity_value = (
                db.query(func.sum(Opportunity.amount))
                .filter(Opportunity.stage.notin_(["Closed Won", "Closed Lost"]))
                .scalar()
                or 0
            )
            return {
                "total_account_annual_revenue": _money(total_account_revenue),
                "total_opportunity_value": _money(total_opportunity_value),
                "open_opportunity_value": _money(open_opportunity_value),
                "total_forecasted_revenue": _money(total_forecasted_revenue),
            }
    except Exception as exc:
        return {"error": f"Could not retrieve CRM totals: {exc}"}


@tool
def get_basic_crm_metrics() -> dict[str, Any]:
    """Return broad CRM metrics for basic business questions: counts, totals, averages, top account, top opportunity, health, industry, owner, stage, and task breakdowns."""
    try:
        with SessionLocal() as db:
            counts = get_crm_counts.invoke({})
            totals = get_crm_totals.invoke({})

            avg_account_revenue = db.query(func.avg(Account.annual_revenue)).scalar() or 0
            avg_opportunity_amount = db.query(func.avg(Opportunity.amount)).scalar() or 0
            avg_probability = db.query(func.avg(Opportunity.probability)).scalar() or 0
            won_value = (
                db.query(func.sum(Opportunity.amount)).filter(Opportunity.stage == "Closed Won").scalar() or 0
            )
            lost_value = (
                db.query(func.sum(Opportunity.amount)).filter(Opportunity.stage == "Closed Lost").scalar() or 0
            )
            won_count = db.query(func.count(Opportunity.id)).filter(Opportunity.stage == "Closed Won").scalar() or 0
            lost_count = db.query(func.count(Opportunity.id)).filter(Opportunity.stage == "Closed Lost").scalar() or 0

            top_account = db.query(Account).order_by(Account.annual_revenue.desc()).first()
            top_opportunity = (
                db.query(Opportunity)
                .options(joinedload(Opportunity.account))
                .order_by(Opportunity.amount.desc())
                .first()
            )

            def grouped(model_field, count_field, value_field=None) -> list[dict[str, Any]]:
                selected = [model_field, func.count(count_field)]
                if value_field is not None:
                    selected.append(func.sum(value_field))
                rows = db.query(*selected).group_by(model_field).all()
                result = []
                for row in rows:
                    if value_field is None:
                        key, count = row
                        result.append({"name": key or "Unknown", "count": int(count)})
                    else:
                        key, count, total = row
                        result.append({"name": key or "Unknown", "count": int(count), "total_value": _money(total)})
                return sorted(result, key=lambda item: (item.get("total_value", item["count"]), item["count"]), reverse=True)

            opportunities_by_owner = [
                {"name": owner or "Unknown", "count": int(count), "total_value": _money(total)}
                for owner, count, total in (
                    db.query(Account.owner, func.count(Opportunity.id), func.sum(Opportunity.amount))
                    .join(Opportunity, Opportunity.account_id == Account.id)
                    .group_by(Account.owner)
                    .all()
                )
            ]
            opportunities_by_owner.sort(key=lambda item: (item["total_value"], item["count"]), reverse=True)

            task_status = grouped(Task.status, Task.id)
            return {
                **counts,
                **totals,
                "average_account_annual_revenue": _money(avg_account_revenue),
                "average_opportunity_amount": _money(avg_opportunity_amount),
                "average_probability": round(float(avg_probability or 0), 1),
                "closed_won_opportunities": int(won_count),
                "closed_lost_opportunities": int(lost_count),
                "closed_won_value": _money(won_value),
                "closed_lost_value": _money(lost_value),
                "top_account_by_revenue": {
                    "name": top_account.name,
                    "annual_revenue": _money(top_account.annual_revenue),
                    "industry": top_account.industry,
                    "owner": top_account.owner,
                }
                if top_account
                else None,
                "largest_opportunity": {
                    "name": top_opportunity.name,
                    "account": top_opportunity.account.name,
                    "amount": _money(top_opportunity.amount),
                    "stage": top_opportunity.stage,
                    "close_date": _iso(top_opportunity.close_date),
                    "probability": top_opportunity.probability,
                }
                if top_opportunity
                else None,
                "accounts_by_health": grouped(Account.account_health, Account.id),
                "accounts_by_industry": grouped(Account.industry, Account.id),
                "accounts_by_owner": grouped(Account.owner, Account.id),
                "opportunities_by_stage": grouped(Opportunity.stage, Opportunity.id, Opportunity.amount),
                "opportunities_by_owner": opportunities_by_owner,
                "tasks_by_status": task_status,
            }
    except Exception as exc:
        return {"error": f"Could not retrieve basic CRM metrics: {exc}"}


@tool
def get_pipeline_summary() -> dict[str, Any]:
    """Aggregate all opportunities by stage with counts, total value, average probability, and total forecasted revenue."""
    try:
        preferred_stage_order = [
            "Prospecting",
            "Qualification",
            "Needs Analysis",
            "Value Proposition",
            "Id. Decision Makers",
            "Proposal/Price Quote",
            "Proposal",
            "Negotiation/Review",
            "Negotiation",
            "Closed Won",
            "Closed Lost",
        ]
        with SessionLocal() as db:
            rows = (
                db.query(
                    Opportunity.stage,
                    func.count(Opportunity.id),
                    func.sum(Opportunity.amount),
                    func.avg(Opportunity.probability),
                    func.sum(Opportunity.amount * Opportunity.probability / 100.0),
                )
                .group_by(Opportunity.stage)
                .all()
            )
            by_stage = {
                stage: {
                    "stage": stage,
                    "count": int(count),
                    "total_value": _money(total_value),
                    "average_probability": round(float(avg_probability or 0), 1),
                    "forecasted_revenue": _money(forecasted),
                }
                for stage, count, total_value, avg_probability, forecasted in rows
            }
            remaining_stages = sorted(stage for stage in by_stage if stage not in preferred_stage_order)
            stage_order = [stage for stage in preferred_stage_order if stage in by_stage] + remaining_stages
            stages = [
                by_stage[stage]
                for stage in stage_order
            ]
            return {
                "stages": stages,
                "total_pipeline": _money(sum(stage["total_value"] for stage in stages)),
                "total_forecasted_revenue": _money(sum(stage["forecasted_revenue"] for stage in stages)),
            }
    except Exception as exc:
        return {"error": f"Could not retrieve pipeline summary: {exc}"}


CRM_TOOLS = [
    get_account_summary,
    get_basic_crm_metrics,
    get_crm_counts,
    get_crm_totals,
    get_at_risk_deals,
    draft_followup_email,
    create_task,
    get_pipeline_summary,
]

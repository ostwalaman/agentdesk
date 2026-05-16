from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database import SessionLocal, utc_now
from models import Account, Activity, Contact, Opportunity, Task
from tools import draft_followup_email, get_account_summary, get_at_risk_deals, get_basic_crm_metrics, get_pipeline_summary


def get_pipeline_health() -> dict[str, Any]:
    """Return pipeline health by stage with totals, forecast, and high-level metrics."""
    return {"pipeline": get_pipeline_summary.invoke({}), "metrics": get_basic_crm_metrics.invoke({})}


def find_at_risk_deals(stage: str | None = None, inactivity_days: int = 14, limit: int = 10) -> dict[str, Any]:
    """Find at-risk opportunities based on low probability, inactivity, close date urgency, and optional stage filter."""
    today = utc_now()
    stale_before = today - timedelta(days=inactivity_days)
    with SessionLocal() as db:
        query = (
            db.query(Opportunity)
            .options(joinedload(Opportunity.account), joinedload(Opportunity.contact))
            .filter(Opportunity.stage.notin_(["Closed Won", "Closed Lost"]))
        )
        if stage:
            query = query.filter(Opportunity.stage.ilike(f"%{stage}%"))
        rows = query.order_by(Opportunity.probability.asc(), Opportunity.close_date.asc()).limit(max(limit * 3, 25)).all()
        results = []
        for opp in rows:
            last_activity = (
                db.query(func.max(Activity.occurred_at))
                .filter((Activity.opportunity_id == opp.id) | (Activity.account_id == opp.account_id))
                .scalar()
            )
            inactive = not last_activity or last_activity < stale_before
            days_to_close = (opp.close_date.date() - today.date()).days
            risk_score = 0
            risk_score += max(0, 50 - opp.probability)
            risk_score += 20 if inactive else 0
            risk_score += 20 if days_to_close <= 30 else 0
            if risk_score <= 0:
                continue
            results.append(
                {
                    "opportunity_id": opp.id,
                    "name": opp.name,
                    "account": opp.account.name,
                    "owner": opp.account.owner,
                    "stage": opp.stage,
                    "amount": opp.amount,
                    "probability": opp.probability,
                    "close_date": opp.close_date.date().isoformat(),
                    "days_to_close": days_to_close,
                    "last_activity_at": last_activity.date().isoformat() if last_activity else None,
                    "risk_score": round(risk_score, 1),
                }
            )
        results.sort(key=lambda item: item["risk_score"], reverse=True)
        return {"deals": results[:limit], "count": len(results[:limit]), "criteria": {"stage": stage, "inactivity_days": inactivity_days}}


def summarize_account(account_name: str) -> dict[str, Any]:
    """Summarize one account by fuzzy name search."""
    return get_account_summary.invoke({"account_name": account_name})


def draft_follow_up(opportunity_id: int | None = None, context: str = "") -> dict[str, Any]:
    """Draft a follow-up email for an opportunity contact."""
    with SessionLocal() as db:
        opp = (
            db.query(Opportunity)
            .options(joinedload(Opportunity.contact), joinedload(Opportunity.account))
            .filter(Opportunity.id == opportunity_id)
            .first()
            if opportunity_id
            else db.query(Opportunity)
            .options(joinedload(Opportunity.contact), joinedload(Opportunity.account))
            .filter(Opportunity.stage.notin_(["Closed Won", "Closed Lost"]))
            .order_by(Opportunity.close_date.asc())
            .first()
        )
        if not opp:
            return {"error": "No opportunity found for follow-up drafting."}
        result = draft_followup_email.invoke({"contact_id": opp.contact_id, "context": context or f"Follow up on {opp.name}"})
        return {"opportunity": {"id": opp.id, "name": opp.name, "account": opp.account.name}, "email": result}


def create_task_for_account(account_id: int, task_text: str, due_days: int = 3) -> dict[str, Any]:
    """Create a local task for the primary contact on an account."""
    with SessionLocal() as db:
        contact = db.query(Contact).filter(Contact.account_id == account_id).order_by(Contact.id.asc()).first()
        if not contact:
            return {"error": f"No contact found for account_id {account_id}."}
        opp = db.query(Opportunity).filter(Opportunity.account_id == account_id).order_by(Opportunity.close_date.asc()).first()
        task = Task(
            contact_id=contact.id,
            opportunity_id=opp.id if opp else None,
            title=task_text,
            due_date=utc_now() + timedelta(days=due_days),
            status="Open",
            created_at=utc_now(),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return {"task_id": task.id, "account_id": account_id, "contact": contact.name, "title": task.title, "due_date": task.due_date.date().isoformat()}


def forecast_revenue() -> dict[str, Any]:
    """Return forecasted revenue and pipeline totals."""
    metrics = get_basic_crm_metrics.invoke({})
    return {
        "total_opportunity_value": metrics["total_opportunity_value"],
        "open_opportunity_value": metrics["open_opportunity_value"],
        "forecasted_revenue": metrics["total_forecasted_revenue"],
        "average_probability": metrics["average_probability"],
    }


def get_stale_opportunities(inactivity_days: int = 14, limit: int = 20) -> dict[str, Any]:
    """Return open opportunities with no recent activity."""
    cutoff = utc_now() - timedelta(days=inactivity_days)
    with SessionLocal() as db:
        rows = (
            db.query(Opportunity)
            .options(joinedload(Opportunity.account), joinedload(Opportunity.contact))
            .filter(Opportunity.stage.notin_(["Closed Won", "Closed Lost"]))
            .limit(500)
            .all()
        )
        stale = []
        for opp in rows:
            last_activity = (
                db.query(func.max(Activity.occurred_at))
                .filter((Activity.opportunity_id == opp.id) | (Activity.account_id == opp.account_id))
                .scalar()
            )
            if not last_activity or last_activity < cutoff:
                stale.append(
                    {
                        "opportunity_id": opp.id,
                        "name": opp.name,
                        "account": opp.account.name,
                        "contact": opp.contact.name,
                        "amount": opp.amount,
                        "stage": opp.stage,
                        "last_activity_at": last_activity.date().isoformat() if last_activity else None,
                    }
                )
        return {"opportunities": stale[:limit], "count": len(stale), "inactivity_days": inactivity_days}


def high_revenue_low_activity(min_revenue: float = 1_000_000, inactivity_days: int = 14, limit: int = 20) -> dict[str, Any]:
    """Find high-revenue accounts with no recent activity."""
    cutoff = utc_now() - timedelta(days=inactivity_days)
    with SessionLocal() as db:
        accounts = db.query(Account).filter(Account.annual_revenue >= min_revenue).order_by(Account.annual_revenue.desc()).all()
        results = []
        for account in accounts:
            last_activity = db.query(func.max(Activity.occurred_at)).filter(Activity.account_id == account.id).scalar()
            if not last_activity or last_activity < cutoff:
                results.append(
                    {
                        "account_id": account.id,
                        "name": account.name,
                        "owner": account.owner,
                        "annual_revenue": account.annual_revenue,
                        "health": account.account_health,
                        "last_activity_at": last_activity.date().isoformat() if last_activity else None,
                    }
                )
        return {"accounts": results[:limit], "count": len(results), "min_revenue": min_revenue, "inactivity_days": inactivity_days}


TOOL_REGISTRY = {
    "get_pipeline_health": get_pipeline_health,
    "find_at_risk_deals": find_at_risk_deals,
    "summarize_account": summarize_account,
    "draft_follow_up": draft_follow_up,
    "create_task": create_task_for_account,
    "forecast_revenue": forecast_revenue,
    "get_stale_opportunities": get_stale_opportunities,
    "high_revenue_low_activity": high_revenue_low_activity,
}

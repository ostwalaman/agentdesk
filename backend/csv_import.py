from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import StringIO
from typing import Any

from database import SessionLocal, init_db, utc_now
from models import Account, Contact, Opportunity, Task


def _clean_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def _value(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and value.strip():
            return value.strip()
    return ""


def _float(value: str, default: float = 0) -> float:
    if not value:
        return default
    return float(value.replace("$", "").replace(",", ""))


def _date(value: str, default: datetime | None = None) -> datetime:
    if not value:
        return default or utc_now()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(value)


def _read_csv(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV must include a header row.")
    return [{_clean_key(key): value for key, value in row.items() if key is not None} for row in reader]


def _probability(value: str, stage: str) -> float:
    if value:
        return _float(value)
    defaults = {
        "Prospecting": 10,
        "Qualification": 20,
        "Needs Analysis": 20,
        "Value Proposition": 50,
        "Proposal": 70,
        "Proposal/Price Quote": 75,
        "Negotiation": 85,
        "Negotiation/Review": 90,
        "Closed Won": 100,
        "Closed Lost": 0,
    }
    return defaults.get(stage, 25)


def _maven_stage(stage: str) -> str:
    return {
        "Won": "Closed Won",
        "Lost": "Closed Lost",
        "Engaging": "Qualification",
        "Prospecting": "Prospecting",
    }.get(stage, stage or "Prospecting")


def _maven_probability(stage: str) -> float:
    return {
        "Closed Won": 100,
        "Closed Lost": 0,
        "Qualification": 35,
        "Prospecting": 10,
    }.get(stage, 25)


def _account_health_from_pipeline(account_name: str, opportunities: list[dict[str, str]]) -> str:
    account_opps = [row for row in opportunities if _value(row, "account") == account_name]
    if not account_opps:
        return "Good"
    lost = sum(1 for row in account_opps if _value(row, "deal_stage") == "Lost")
    open_low = sum(1 for row in account_opps if _value(row, "deal_stage") in {"Prospecting", "Engaging"})
    if lost > 2:
        return "Critical"
    if lost or open_low > 2:
        return "At Risk"
    return "Good"


def _best_date(*values: str) -> datetime:
    for value in values:
        if value:
            return _date(value)
    return utc_now()


def import_crm_csv(csv_text: str) -> dict[str, Any]:
    init_db(seed=False)
    rows = _read_csv(csv_text)
    if not rows:
        raise ValueError("CSV did not contain any data rows.")

    counts = {"accounts": 0, "contacts": 0, "opportunities": 0, "tasks": 0}
    with SessionLocal() as db:
        for row in rows:
            account_name = _value(row, "account_name", "account", "company", "company_name", "name")
            if not account_name:
                continue

            account = db.query(Account).filter(Account.name == account_name).one_or_none()
            if not account:
                account = Account(
                    name=account_name,
                    industry=_value(row, "industry") or "Unknown",
                    annual_revenue=_float(_value(row, "annual_revenue", "revenue")),
                    account_health=_value(row, "account_health", "health") or "Good",
                    owner=_value(row, "owner", "account_owner") or "CSV Import",
                    created_at=utc_now(),
                )
                db.add(account)
                db.flush()
                counts["accounts"] += 1
            else:
                account.industry = _value(row, "industry") or account.industry
                account.annual_revenue = _float(_value(row, "annual_revenue", "revenue"), account.annual_revenue)
                account.account_health = _value(row, "account_health", "health") or account.account_health
                account.owner = _value(row, "owner", "account_owner") or account.owner

            contact_name = _value(row, "contact_name", "contact", "primary_contact")
            contact = None
            if contact_name:
                contact = (
                    db.query(Contact)
                    .filter(Contact.account_id == account.id, Contact.name == contact_name)
                    .one_or_none()
                )
                if not contact:
                    contact = Contact(
                        account_id=account.id,
                        name=contact_name,
                        email=_value(row, "email", "contact_email"),
                        phone=_value(row, "phone", "contact_phone"),
                        last_contacted_at=_date(_value(row, "last_contacted_at", "last_contacted"), utc_now()),
                        status=_value(row, "contact_status", "status") or "New",
                    )
                    db.add(contact)
                    db.flush()
                    counts["contacts"] += 1

            opportunity_name = _value(row, "opportunity_name", "opportunity", "deal_name", "deal")
            opportunity = None
            if opportunity_name:
                if not contact:
                    contact = (
                        db.query(Contact)
                        .filter(Contact.account_id == account.id)
                        .order_by(Contact.id.asc())
                        .first()
                    )
                if not contact:
                    contact = Contact(
                        account_id=account.id,
                        name=f"{account.name} Buying Team",
                        email="",
                        phone="",
                        last_contacted_at=utc_now(),
                        status="New",
                    )
                    db.add(contact)
                    db.flush()
                    counts["contacts"] += 1

                opportunity = (
                    db.query(Opportunity)
                    .filter(Opportunity.account_id == account.id, Opportunity.name == opportunity_name)
                    .one_or_none()
                )
                stage = _value(row, "stage", "opportunity_stage") or "Prospecting"
                if not opportunity:
                    opportunity = Opportunity(
                        account_id=account.id,
                        contact_id=contact.id,
                        name=opportunity_name,
                        stage=stage,
                        amount=_float(_value(row, "amount", "deal_amount")),
                        close_date=_date(_value(row, "close_date"), utc_now() + timedelta(days=30)),
                        probability=_probability(_value(row, "probability"), stage),
                        created_at=utc_now(),
                    )
                    db.add(opportunity)
                    db.flush()
                    counts["opportunities"] += 1
                else:
                    opportunity.stage = stage
                    opportunity.amount = _float(_value(row, "amount", "deal_amount"), opportunity.amount)
                    opportunity.close_date = _date(_value(row, "close_date"), opportunity.close_date)
                    opportunity.probability = _probability(_value(row, "probability"), stage)

            task_title = _value(row, "task_title", "task", "title", "subject")
            if task_title:
                if not contact:
                    contact = db.query(Contact).filter(Contact.account_id == account.id).first()
                if contact:
                    task = Task(
                        contact_id=contact.id,
                        opportunity_id=opportunity.id if opportunity else None,
                        title=task_title,
                        due_date=_date(_value(row, "due_date", "task_due_date"), utc_now() + timedelta(days=7)),
                        status=_value(row, "task_status") or "Open",
                        created_at=utc_now(),
                    )
                    db.add(task)
                    counts["tasks"] += 1

        db.commit()

    return {"rows_processed": len(rows), **counts}


def import_multiple_crm_csv(files: dict[str, str]) -> dict[str, Any]:
    normalized_files = {name.lower(): content for name, content in files.items()}
    if any(name.endswith("sales_pipeline.csv") for name in normalized_files):
        return import_maven_crm_files(normalized_files)

    totals: dict[str, Any] = {
        "mode": "generic",
        "files_processed": len(files),
        "rows_processed": 0,
        "accounts": 0,
        "contacts": 0,
        "opportunities": 0,
        "tasks": 0,
    }
    for csv_text in files.values():
        result = import_crm_csv(csv_text)
        for key in ("rows_processed", "accounts", "contacts", "opportunities", "tasks"):
            totals[key] += result.get(key, 0)
    return totals


def import_maven_crm_files(files: dict[str, str]) -> dict[str, Any]:
    init_db(seed=False)

    def file_rows(suffix: str) -> list[dict[str, str]]:
        for filename, content in files.items():
            if filename.endswith(suffix):
                return _read_csv(content)
        return []

    account_rows = file_rows("accounts.csv")
    pipeline_rows = file_rows("sales_pipeline.csv")
    product_rows = file_rows("products.csv")
    team_rows = file_rows("sales_teams.csv")

    if not pipeline_rows:
        raise ValueError("Kaggle/Maven import requires sales_pipeline.csv.")

    products = {_value(row, "product"): row for row in product_rows}
    teams = {_value(row, "sales_agent"): row for row in team_rows}
    account_rows_by_name = {_value(row, "account"): row for row in account_rows if _value(row, "account")}

    agents_by_account: dict[str, Counter[str]] = defaultdict(Counter)
    latest_activity_by_account: dict[str, datetime] = {}
    for row in pipeline_rows:
        account_name = _value(row, "account")
        agent = _value(row, "sales_agent")
        if account_name and agent:
            agents_by_account[account_name][agent] += 1
        activity_date = _best_date(_value(row, "close_date"), _value(row, "engage_date"))
        if account_name:
            latest_activity_by_account[account_name] = max(
                latest_activity_by_account.get(account_name, activity_date),
                activity_date,
            )

    counts = {"accounts": 0, "contacts": 0, "opportunities": 0, "tasks": 0}
    with SessionLocal() as db:
        account_by_name: dict[str, Account] = {}
        contact_by_account_name: dict[str, Contact] = {}
        all_account_names = set(account_rows_by_name) | {
            _value(row, "account") for row in pipeline_rows if _value(row, "account")
        }

        for account_name in sorted(all_account_names):
            row = account_rows_by_name.get(account_name, {})
            owner = "Kaggle Import"
            if agents_by_account.get(account_name):
                owner = agents_by_account[account_name].most_common(1)[0][0]
            account = db.query(Account).filter(Account.name == account_name).one_or_none()
            revenue_millions = _float(_value(row, "revenue"))
            if not account:
                account = Account(
                    name=account_name,
                    industry=_value(row, "sector") or "Unknown",
                    annual_revenue=revenue_millions * 1_000_000,
                    account_health=_account_health_from_pipeline(account_name, pipeline_rows),
                    owner=owner,
                    created_at=utc_now(),
                )
                db.add(account)
                db.flush()
                counts["accounts"] += 1
            else:
                account.industry = _value(row, "sector") or account.industry
                account.annual_revenue = revenue_millions * 1_000_000 if revenue_millions else account.annual_revenue
                account.account_health = _account_health_from_pipeline(account_name, pipeline_rows)
                account.owner = owner
            account_by_name[account_name] = account

            contact_name = f"{account_name} Buying Team"
            contact = (
                db.query(Contact)
                .filter(Contact.account_id == account.id, Contact.name == contact_name)
                .one_or_none()
            )
            if not contact:
                domain = account_name.lower().replace("&", "and")
                domain = "".join(char for char in domain if char.isalnum())[:32] or "account"
                contact = Contact(
                    account_id=account.id,
                    name=contact_name,
                    email=f"buying.team@{domain}.example",
                    phone="",
                    last_contacted_at=latest_activity_by_account.get(account_name, utc_now()),
                    status="Active",
                )
                db.add(contact)
                db.flush()
                counts["contacts"] += 1
            else:
                contact.last_contacted_at = latest_activity_by_account.get(account_name, contact.last_contacted_at)
            contact_by_account_name[account_name] = contact

        for row in pipeline_rows:
            account_name = _value(row, "account")
            account = account_by_name.get(account_name)
            contact = contact_by_account_name.get(account_name)
            if not account or not contact:
                continue

            product_name = _value(row, "product")
            stage = _maven_stage(_value(row, "deal_stage"))
            close_value = _float(_value(row, "close_value"))
            product_price = _float(_value(products.get(product_name, {}), "sales_price"))
            amount = close_value or product_price
            opportunity_id = _value(row, "opportunity_id")
            opportunity_name = f"{account_name} - {product_name or 'Opportunity'}"
            if opportunity_id:
                opportunity_name = f"{opportunity_name} ({opportunity_id})"
            close_date = _date(_value(row, "close_date"), _date(_value(row, "engage_date"), utc_now()) + timedelta(days=45))
            created_at = _date(_value(row, "engage_date"), close_date - timedelta(days=45))

            opportunity = (
                db.query(Opportunity)
                .filter(Opportunity.account_id == account.id, Opportunity.name == opportunity_name)
                .one_or_none()
            )
            if not opportunity:
                opportunity = Opportunity(
                    account_id=account.id,
                    contact_id=contact.id,
                    name=opportunity_name,
                    stage=stage,
                    amount=amount,
                    close_date=close_date,
                    probability=_maven_probability(stage),
                    created_at=created_at,
                )
                db.add(opportunity)
                counts["opportunities"] += 1
            else:
                opportunity.stage = stage
                opportunity.amount = amount
                opportunity.close_date = close_date
                opportunity.probability = _maven_probability(stage)

        for account_name, contact in contact_by_account_name.items():
            account = account_by_name[account_name]
            owner = account.owner
            team = teams.get(owner, {})
            manager = _value(team, "manager")
            regional_office = _value(team, "regional_office")
            title = "Review imported Kaggle pipeline"
            if manager or regional_office:
                title = f"Review {regional_office or 'regional'} pipeline with {manager or owner}"
            existing = (
                db.query(Task)
                .filter(Task.contact_id == contact.id, Task.title == title)
                .one_or_none()
            )
            if not existing:
                db.add(
                    Task(
                        contact_id=contact.id,
                        opportunity_id=None,
                        title=title,
                        due_date=utc_now() + timedelta(days=7),
                        status="Open",
                        created_at=utc_now(),
                    )
                )
                counts["tasks"] += 1

        db.commit()

    return {
        "mode": "kaggle_maven",
        "files_processed": len(files),
        "rows_processed": len(account_rows) + len(pipeline_rows) + len(product_rows) + len(team_rows),
        **counts,
    }

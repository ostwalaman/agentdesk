from __future__ import annotations

import os
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import select

from database import SessionLocal, ensure_salesforce_columns, init_db, utc_now
from models import Account, Activity, Contact, Opportunity, Task
from salesforce_client import get_object_fields, get_salesforce_client


def parse_salesforce_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def parse_salesforce_date(value: str | None) -> datetime:
    if not value:
        return utc_now()
    return datetime.combine(datetime.fromisoformat(value).date(), time.min)


def account_health_from(record: dict[str, Any]) -> str:
    custom_health = record.get("Account_Health__c")
    if custom_health in {"Good", "At Risk", "Critical"}:
        return custom_health
    rating = record.get("Rating")
    if rating == "Hot":
        return "Good"
    if rating == "Warm":
        return "At Risk"
    if rating == "Cold":
        return "Critical"
    return "Good"


def contact_status_from(record: dict[str, Any]) -> str:
    if record.get("LastActivityDate"):
        return "Active"
    created_at = parse_salesforce_datetime(record.get("CreatedDate"))
    return "New" if (utc_now() - created_at).days <= 30 else "Cold"


def task_status_from(status: str | None) -> str:
    return "Done" if status in {"Completed", "Done"} else "Open"


def sync_salesforce_to_sqlite() -> dict[str, int | str]:
    init_db(seed=False)
    ensure_salesforce_columns()
    sf = get_salesforce_client()

    account_fields = get_object_fields(sf, "Account")
    contact_fields = get_object_fields(sf, "Contact")
    opportunity_fields = get_object_fields(sf, "Opportunity")

    account_select = ["Id", "Name", "CreatedDate", "Owner.Name"]
    for field in ("Industry", "AnnualRevenue", "Rating", "Account_Health__c"):
        if field in account_fields:
            account_select.append(field)

    contact_select = ["Id", "AccountId", "Name", "CreatedDate"]
    for field in ("Email", "Phone", "LastActivityDate"):
        if field in contact_fields:
            contact_select.append(field)

    opportunity_select = ["Id", "AccountId", "Name", "StageName", "CloseDate", "CreatedDate"]
    for field in ("Amount", "Probability"):
        if field in opportunity_fields:
            opportunity_select.append(field)

    account_limit = int(os.getenv("SALESFORCE_SYNC_ACCOUNT_LIMIT", "2000"))
    contact_limit = int(os.getenv("SALESFORCE_SYNC_CONTACT_LIMIT", "5000"))
    opportunity_limit = int(os.getenv("SALESFORCE_SYNC_OPPORTUNITY_LIMIT", "5000"))
    task_limit = int(os.getenv("SALESFORCE_SYNC_TASK_LIMIT", "5000"))

    accounts = sf.query_all(
        f"SELECT {', '.join(account_select)} FROM Account ORDER BY CreatedDate DESC LIMIT {account_limit}"
    )["records"]
    contacts = sf.query_all(
        f"SELECT {', '.join(contact_select)} FROM Contact WHERE AccountId != null "
        f"ORDER BY CreatedDate DESC LIMIT {contact_limit}"
    )["records"]
    opportunities = sf.query_all(
        f"SELECT {', '.join(opportunity_select)} FROM Opportunity WHERE AccountId != null "
        f"ORDER BY CreatedDate DESC LIMIT {opportunity_limit}"
    )["records"]

    opportunity_contact_roles: dict[str, str] = {}
    try:
        roles = sf.query_all(
            "SELECT OpportunityId, ContactId, IsPrimary FROM OpportunityContactRole "
            "WHERE ContactId != null ORDER BY IsPrimary DESC"
        )["records"]
        for role in roles:
            opportunity_contact_roles.setdefault(role["OpportunityId"], role["ContactId"])
    except Exception:
        opportunity_contact_roles = {}

    with SessionLocal() as db:
        db.query(Activity).filter(Activity.activity_type == "Salesforce Activity").delete()

        account_by_sf_id: dict[str, Account] = {}
        for record in accounts:
            owner = record.get("Owner") or {}
            account_name = record.get("Name") or "Unnamed Account"
            account = (
                db.scalar(select(Account).where(Account.salesforce_id == record["Id"]))
                or db.scalar(select(Account).where(Account.name == account_name))
                or Account()
            )
            account.salesforce_id = record["Id"]
            account.name = account_name
            account.industry = record.get("Industry") or "Unknown"
            account.annual_revenue = float(record.get("AnnualRevenue") or 0)
            account.account_health = account_health_from(record)
            account.owner = owner.get("Name") or "Unknown Owner"
            account.created_at = parse_salesforce_datetime(record.get("CreatedDate"))
            if account.id is None:
                db.add(account)
            db.flush()
            account_by_sf_id[record["Id"]] = account

        contact_by_sf_id: dict[str, Contact] = {}
        contacts_by_account_sf_id: dict[str, list[Contact]] = {}
        for record in contacts:
            account = account_by_sf_id.get(record.get("AccountId"))
            if not account:
                continue
            contact = db.scalar(select(Contact).where(Contact.salesforce_id == record["Id"])) or Contact()
            contact.salesforce_id = record["Id"]
            contact.account_id = account.id
            contact.name = record.get("Name") or "Unnamed Contact"
            contact.email = record.get("Email") or ""
            contact.phone = record.get("Phone") or ""
            contact.last_contacted_at = parse_salesforce_date(record.get("LastActivityDate"))
            contact.status = contact_status_from(record)
            if contact.id is None:
                db.add(contact)
            db.flush()
            contact_by_sf_id[record["Id"]] = contact
            contacts_by_account_sf_id.setdefault(record.get("AccountId"), []).append(contact)

        opportunity_by_sf_id: dict[str, Opportunity] = {}
        for record in opportunities:
            account = account_by_sf_id.get(record.get("AccountId"))
            if not account:
                continue
            contact = contact_by_sf_id.get(opportunity_contact_roles.get(record["Id"]) or "")
            if not contact:
                contact = next(iter(contacts_by_account_sf_id.get(record.get("AccountId"), [])), None)
            if not contact:
                continue
            opportunity = db.scalar(select(Opportunity).where(Opportunity.salesforce_id == record["Id"])) or Opportunity()
            opportunity.salesforce_id = record["Id"]
            opportunity.account_id = account.id
            opportunity.contact_id = contact.id
            opportunity.name = record.get("Name") or "Unnamed Opportunity"
            opportunity.stage = record.get("StageName") or "Prospecting"
            opportunity.amount = float(record.get("Amount") or 0)
            opportunity.close_date = parse_salesforce_date(record.get("CloseDate"))
            opportunity.probability = float(record.get("Probability") or 0)
            opportunity.created_at = parse_salesforce_datetime(record.get("CreatedDate"))
            if opportunity.id is None:
                db.add(opportunity)
            db.flush()
            opportunity_by_sf_id[record["Id"]] = opportunity

        contact_sf_ids = ",".join(f"'{sf_id}'" for sf_id in contact_by_sf_id)
        opportunity_sf_ids = ",".join(f"'{sf_id}'" for sf_id in opportunity_by_sf_id)
        tasks: list[dict[str, Any]] = []
        if contact_sf_ids:
            tasks = sf.query_all(
                "SELECT Id, WhoId, WhatId, Subject, ActivityDate, Status, CreatedDate "
                f"FROM Task WHERE WhoId IN ({contact_sf_ids}) ORDER BY CreatedDate DESC LIMIT {task_limit}"
            )["records"]
        if opportunity_sf_ids:
            opportunity_tasks = sf.query_all(
                "SELECT Id, WhoId, WhatId, Subject, ActivityDate, Status, CreatedDate "
                f"FROM Task WHERE WhatId IN ({opportunity_sf_ids}) ORDER BY CreatedDate DESC LIMIT {task_limit}"
            )["records"]
            seen_task_ids = {task["Id"] for task in tasks}
            tasks.extend(task for task in opportunity_tasks if task["Id"] not in seen_task_ids)

        for record in tasks:
            contact = contact_by_sf_id.get(record.get("WhoId") or "")
            opportunity = opportunity_by_sf_id.get(record.get("WhatId") or "")
            if not contact and opportunity:
                contact = db.scalar(select(Contact).where(Contact.id == opportunity.contact_id))
            if not contact:
                continue
            task = db.scalar(select(Task).where(Task.salesforce_id == record["Id"])) or Task()
            task.salesforce_id = record["Id"]
            task.contact_id = contact.id
            task.opportunity_id = opportunity.id if opportunity else None
            task.title = record.get("Subject") or "Salesforce Task"
            task.due_date = parse_salesforce_date(record.get("ActivityDate"))
            task.status = task_status_from(record.get("Status"))
            task.created_at = parse_salesforce_datetime(record.get("CreatedDate"))
            if task.id is None:
                db.add(task)

        activity_count = 0
        for contact in contact_by_sf_id.values():
            account = db.get(Account, contact.account_id)
            if not account:
                continue
            db.add(
                Activity(
                    account_id=account.id,
                    contact_id=contact.id,
                    opportunity_id=None,
                    activity_type="Salesforce Activity",
                    subject=f"Last activity for {contact.name}",
                    occurred_at=contact.last_contacted_at,
                    created_at=contact.last_contacted_at,
                )
            )
            activity_count += 1

        db.commit()
        return {
            "salesforce_instance": sf.sf_instance,
            "accounts": len(account_by_sf_id),
            "contacts": len(contact_by_sf_id),
            "opportunities": len(opportunity_by_sf_id),
            "tasks": len(tasks),
            "activities": activity_count,
        }


if __name__ == "__main__":
    result = sync_salesforce_to_sqlite()
    print("Salesforce sync complete")
    print(result)

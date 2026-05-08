from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from models import Account, Base, Contact, Opportunity, Task

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = f"sqlite:///{BASE_DIR / 'agentdesk.db'}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(seed: bool = True) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_salesforce_columns()
    if seed:
        seed_database()


def ensure_salesforce_columns() -> None:
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name in ("accounts", "contacts", "opportunities", "tasks"):
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "salesforce_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN salesforce_id VARCHAR"))


def seed_database(force: bool = False) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_salesforce_columns()
    with SessionLocal() as db:
        has_accounts = db.scalar(select(Account.id).limit(1))
        if has_accounts and not force:
            return

        if force:
            db.query(Task).delete()
            db.query(Opportunity).delete()
            db.query(Contact).delete()
            db.query(Account).delete()
            db.commit()

        now = utc_now()
        account_rows = [
            ("Acme Corp", "SaaS", 18500000, "At Risk", "Avery Stone"),
            ("TechCo Systems", "SaaS", 42000000, "Good", "Maya Chen"),
            ("Northstar Health", "Healthcare", 76000000, "Critical", "Jordan Blake"),
            ("Meridian Finance", "Finance", 120000000, "Good", "Avery Stone"),
            ("BrightMarket Retail", "Retail", 54000000, "At Risk", "Priya Shah"),
            ("CloudPeak Analytics", "SaaS", 22500000, "Good", "Maya Chen"),
            ("SummitCare Network", "Healthcare", 91000000, "Good", "Jordan Blake"),
            ("RiverBank Capital", "Finance", 145000000, "At Risk", "Elena Ruiz"),
            ("UrbanCart Group", "Retail", 33000000, "Critical", "Priya Shah"),
            ("DataForge Labs", "SaaS", 14800000, "Good", "Maya Chen"),
            ("HelioMed Partners", "Healthcare", 68000000, "At Risk", "Jordan Blake"),
            ("BlueLedger Trust", "Finance", 97000000, "Good", "Elena Ruiz"),
            ("FreshLoop Stores", "Retail", 28000000, "Good", "Priya Shah"),
            ("QuantumCRM", "SaaS", 39000000, "Critical", "Avery Stone"),
            ("Evergreen Clinics", "Healthcare", 44000000, "Good", "Jordan Blake"),
            ("Atlas Wealth", "Finance", 83000000, "At Risk", "Elena Ruiz"),
            ("Nimbus Works", "SaaS", 26000000, "Good", "Maya Chen"),
            ("OmniShop Brands", "Retail", 61000000, "Good", "Priya Shah"),
            ("Cobalt Insurance", "Finance", 112000000, "Critical", "Elena Ruiz"),
            ("MedAxis Solutions", "Healthcare", 57000000, "At Risk", "Avery Stone"),
        ]

        accounts: list[Account] = []
        for idx, (name, industry, revenue, health, owner) in enumerate(account_rows, start=1):
            accounts.append(
                Account(
                    id=idx,
                    name=name,
                    industry=industry,
                    annual_revenue=revenue,
                    account_health=health,
                    owner=owner,
                    created_at=now - timedelta(days=idx * 19),
                )
            )
        db.add_all(accounts)
        db.flush()

        contacts: list[Contact] = []
        first_names = [
            "Olivia", "Ethan", "Sophia", "Liam", "Emma", "Noah", "Ava", "Lucas", "Mia", "Mason",
            "Isabella", "Logan", "Charlotte", "James", "Amelia", "Benjamin", "Harper", "Henry", "Evelyn", "Jack",
            "Grace", "Owen", "Nora", "Caleb",
        ]
        last_names = [
            "Parker", "Nguyen", "Patel", "Rivera", "Brooks", "Morgan", "Kim", "Foster", "Singh", "Carter",
            "Bennett", "Reed", "Cooper", "Ward", "Hughes", "Bell", "Bailey", "Ross", "Coleman", "Hayes",
            "Price", "Murphy", "Kelly", "Bryant",
        ]
        statuses = ["Active", "Cold", "New", "Active", "Active", "Cold"]
        for idx in range(24):
            account = accounts[idx % len(accounts)]
            full_name = f"{first_names[idx]} {last_names[idx]}"
            domain = account.name.lower().replace(" ", "").replace(".", "") + ".com"
            contacts.append(
                Contact(
                    id=idx + 1,
                    account_id=account.id,
                    name=full_name,
                    email=f"{first_names[idx].lower()}.{last_names[idx].lower()}@{domain}",
                    phone=f"+1-415-555-{1000 + idx}",
                    last_contacted_at=now - timedelta(days=(idx * 3) % 55 + 1),
                    status=statuses[idx % len(statuses)],
                )
            )
        db.add_all(contacts)
        db.flush()

        stages = ["Prospecting", "Qualification", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]
        opportunity_rows = [
            ("Enterprise CRM Expansion", 420000, "Proposal", 42, 16),
            ("AI Sales Insights Pilot", 135000, "Qualification", 35, 22),
            ("Care Coordination Platform", 690000, "Negotiation", 48, 12),
            ("Wealth Desk Modernization", 980000, "Proposal", 64, 38),
            ("Retail Loyalty Cloud", 315000, "Prospecting", 25, 18),
            ("Analytics Seat Expansion", 240000, "Negotiation", 72, 9),
            ("Patient Outreach Suite", 510000, "Closed Won", 100, -8),
            ("Risk Operations Rollout", 760000, "Qualification", 44, 27),
            ("Store Ops Automation", 285000, "Proposal", 46, 7),
            ("Developer Platform Renewal", 175000, "Closed Lost", 0, -15),
            ("Revenue Intelligence Add-on", 330000, "Negotiation", 58, 31),
            ("Compliance Data Vault", 880000, "Proposal", 52, 25),
            ("Inventory Forecasting", 220000, "Prospecting", 30, 45),
            ("Agent Assist Deployment", 610000, "Qualification", 38, 14),
            ("Clinical Scheduling Upgrade", 450000, "Proposal", 61, 33),
            ("Portfolio Analytics", 720000, "Negotiation", 47, 20),
            ("Workflow Automation Pack", 190000, "Prospecting", 28, 11),
            ("Unified Customer Profile", 530000, "Closed Won", 100, -3),
            ("Claims Intelligence Suite", 640000, "Qualification", 32, 24),
            ("Provider Data Hub", 395000, "Proposal", 49, 29),
            ("Renewal Desk Automation", 255000, "Negotiation", 67, 5),
            ("Customer Success Copilot", 305000, "Proposal", 41, 26),
            ("Security Review Package", 150000, "Prospecting", 22, 60),
            ("Executive Reporting Layer", 470000, "Negotiation", 55, 17),
        ]

        opportunities: list[Opportunity] = []
        for idx, (name, amount, stage, probability, close_offset) in enumerate(opportunity_rows, start=1):
            account = accounts[(idx - 1) % len(accounts)]
            contact = contacts[(idx - 1) % len(contacts)]
            opportunities.append(
                Opportunity(
                    id=idx,
                    account_id=account.id,
                    contact_id=contact.id,
                    name=name,
                    stage=stage,
                    amount=amount,
                    close_date=now + timedelta(days=close_offset),
                    probability=probability,
                    created_at=now - timedelta(days=idx * 11),
                )
            )
        db.add_all(opportunities)
        db.flush()

        task_titles = [
            "Send pricing recap", "Schedule executive call", "Confirm legal review", "Share security questionnaire",
            "Book discovery workshop", "Update buying committee", "Send ROI calculator", "Check implementation timeline",
            "Follow up on pilot feedback", "Prepare renewal proposal", "Coordinate procurement intro", "Send case study",
            "Validate technical fit", "Review success criteria", "Create mutual action plan", "Confirm budget owner",
            "Share integration docs", "Schedule stakeholder demo", "Log competitive notes", "Send meeting notes",
            "Request close plan", "Update forecast notes", "Confirm next-step owner", "Prepare champion email",
        ]
        tasks: list[Task] = []
        for idx, title in enumerate(task_titles, start=1):
            contact = contacts[(idx - 1) % len(contacts)]
            opportunity = opportunities[(idx - 1) % len(opportunities)]
            tasks.append(
                Task(
                    id=idx,
                    contact_id=contact.id,
                    opportunity_id=opportunity.id,
                    title=title,
                    due_date=now + timedelta(days=(idx % 12) + 1),
                    status="Done" if idx % 5 == 0 else "Open",
                    created_at=now - timedelta(days=idx * 2),
                )
            )
        db.add_all(tasks)
        db.commit()


if __name__ == "__main__":
    seed_database(force=True)
    print(f"Seeded AgentDesk database at {BASE_DIR / 'agentdesk.db'}")

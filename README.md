# AgentDesk

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=0b1f3a)
![LangGraph](https://img.shields.io/badge/LangGraph-Agent-1f8cff)
![OpenAI](https://img.shields.io/badge/OpenAI-API-111827?logo=openai&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-CRM-003B57?logo=sqlite&logoColor=white)

AgentDesk is a full-stack AI CRM agent for sales teams. It gives sales reps a natural-language workspace for account summaries, pipeline inspection, risk triage, follow-up drafting, and CRM task creation on top of Salesforce-like data.

The project is built as an Agentforce-style multi-tool LLM agent. A LangGraph ReAct agent decides when to call CRM tools, the tools query or mutate a local SQLite CRM, and the React frontend presents a professional chat and pipeline command center.

## Architecture

```text
Sales Rep
   |
   v
React + TypeScript + Tailwind frontend
   |
   |  /chat, /pipeline, /accounts, /deals/at-risk
   v
FastAPI backend
   |
   v
LangGraph ReAct agent + LangChain tools
   |
   +--> SQLite CRM tables
   |      accounts, contacts, opportunities, tasks
   |
   +--> OpenAI chat model
          configured with OPENAI_MODEL
```

## Setup

### Backend

```bash
cd agentdesk
cp .env.example .env
# add OPENAI_API_KEY to .env
# optionally set OPENAI_MODEL, defaults to gpt-4o-mini

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python database.py
uvicorn main:app --reload --port 8000
```

The standalone seed command recreates `backend/agentdesk.db` with 20 accounts, 24 contacts, 24 opportunities, and 24 tasks.

### Frontend

```bash
cd agentdesk/frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The Vite dev server proxies `/api/*` calls to `http://localhost:8000`.

## CRM Agent Tools

AgentDesk exposes five LangChain tools to the agent:

- `get_account_summary(account_name)` fuzzy-searches accounts and returns account health, open opportunities, and last contact date.
- `get_at_risk_deals()` ranks open deals closing within 30 days with probability below 50%.
- `draft_followup_email(contact_id, context)` drafts a warm professional follow-up using OpenAI and CRM context.
- `create_task(contact_id, title, due_days)` creates an open CRM task.
- `get_pipeline_summary()` aggregates pipeline count, value, probability, and forecast by stage.

## Sample Prompts

- Give me a summary of Acme Corp
- Which deals are closing this month and look risky?
- Draft a follow-up email for contact id 3
- Create a follow-up task for contact 5 due in 3 days
- What does our overall pipeline look like?

## Optional Salesforce Developer Org Upgrade

The project includes `simple-salesforce` so the SQLite layer can be replaced or synchronized with a real Salesforce Developer Org.

1. Create a Salesforce Developer Org.
2. Add these values to `.env`:

```bash
SALESFORCE_USERNAME=your_username
SALESFORCE_PASSWORD=your_password
SALESFORCE_SECURITY_TOKEN=your_security_token
SALESFORCE_DOMAIN=login
```

3. Add a Salesforce client module:

```python
from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os

load_dotenv()

sf = Salesforce(
    username=os.getenv("SALESFORCE_USERNAME"),
    password=os.getenv("SALESFORCE_PASSWORD"),
    security_token=os.getenv("SALESFORCE_SECURITY_TOKEN"),
    domain=os.getenv("SALESFORCE_DOMAIN", "login"),
)
```

4. Sync Salesforce records into AgentDesk:

```bash
cd agentdesk/backend
source .venv/bin/activate
python salesforce_sync.py
```

This pulls Salesforce `Account`, `Contact`, `Opportunity`, and `Task` records into the local SQLite cache used by the agent and frontend.

You can also sync from the frontend by clicking `Sync Salesforce` in the left sidebar.

## Import CRM CSV

The left sidebar includes an `Import CRM CSV` button. The importer accepts CSV files with these headers:

```csv
account_name,industry,annual_revenue,account_health,owner,contact_name,email,phone,opportunity_name,stage,amount,close_date,probability,task_title,due_date
```

Only `account_name` is required. If contact, opportunity, or task columns are present, AgentDesk imports those records too. See `sample_crm_import.csv` for a ready-to-use template.

The importer also supports the Kaggle/Maven CRM Sales Opportunities bundle. Select and upload these files together:

```text
accounts.csv
products.csv
sales_pipeline.csv
sales_teams.csv
```

AgentDesk detects `sales_pipeline.csv` and maps the bundle into local CRM accounts, synthetic account contacts, opportunities, and follow-up tasks. See `sample_kaggle_crm/` for a tiny example bundle.

## Screenshots

Add screenshots here after running the frontend:

- Chat workspace
- Pipeline overview sidebar
- At-risk deals card
- Follow-up email draft response

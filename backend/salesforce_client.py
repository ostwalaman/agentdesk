from __future__ import annotations

import os
from typing import Any

from simple_salesforce import Salesforce

from config import get_salesforce_domain


def get_salesforce_client() -> Salesforce:
    username = os.getenv("SALESFORCE_USERNAME")
    password = os.getenv("SALESFORCE_PASSWORD")
    token = os.getenv("SALESFORCE_SECURITY_TOKEN")
    missing = [
        name
        for name, value in (
            ("SALESFORCE_USERNAME", username),
            ("SALESFORCE_PASSWORD", password),
            ("SALESFORCE_SECURITY_TOKEN", token),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Salesforce settings: {', '.join(missing)}")

    return Salesforce(
        username=username,
        password=password,
        security_token=token,
        domain=get_salesforce_domain(),
    )


def get_object_fields(sf: Salesforce, object_name: str) -> set[str]:
    description: dict[str, Any] = getattr(sf, object_name).describe()
    return {field["name"] for field in description.get("fields", [])}


def soql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

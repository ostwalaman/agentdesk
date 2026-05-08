from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
PROJECT_ENV_PATH = PROJECT_DIR / ".env"
BACKEND_ENV_PATH = BACKEND_DIR / ".env"

load_dotenv(PROJECT_ENV_PATH, override=True)
load_dotenv(BACKEND_ENV_PATH, override=True)


def get_openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY")


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_salesforce_domain() -> str:
    domain = os.getenv("SALESFORCE_DOMAIN", "login").strip()
    domain = domain.removeprefix("https://").removeprefix("http://")
    domain = domain.removesuffix("/")
    if domain.endswith(".salesforce.com"):
        domain = domain[: -len(".salesforce.com")]
    return domain or "login"


def _last6(value: str | None) -> str | None:
    if not value:
        return None
    return value[-6:]


def _masked(value: str | None) -> str | None:
    suffix = _last6(value)
    if not suffix:
        return None
    return f"...{suffix}"


def _env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    value = dotenv_values(path).get(key)
    return str(value) if value else None


def get_openai_key_debug() -> dict[str, Any]:
    runtime_key = get_openai_api_key()
    project_env_key = _env_value(PROJECT_ENV_PATH, "OPENAI_API_KEY")
    backend_env_key = _env_value(BACKEND_ENV_PATH, "OPENAI_API_KEY")

    if runtime_key and backend_env_key and runtime_key == backend_env_key:
        runtime_source = "backend/.env"
    elif runtime_key and project_env_key and runtime_key == project_env_key:
        runtime_source = ".env"
    elif runtime_key:
        runtime_source = "process environment"
    else:
        runtime_source = "not set"

    return {
        "openai_model": get_openai_model(),
        "runtime": {
            "is_set": bool(runtime_key),
            "last6": _last6(runtime_key),
            "masked": _masked(runtime_key),
            "detected_source": runtime_source,
        },
        "project_env": {
            "path": str(PROJECT_ENV_PATH),
            "exists": PROJECT_ENV_PATH.exists(),
            "last6": _last6(project_env_key),
            "masked": _masked(project_env_key),
            "matches_runtime": bool(runtime_key and project_env_key and runtime_key == project_env_key),
        },
        "backend_env": {
            "path": str(BACKEND_ENV_PATH),
            "exists": BACKEND_ENV_PATH.exists(),
            "last6": _last6(backend_env_key),
            "masked": _masked(backend_env_key),
            "matches_runtime": bool(runtime_key and backend_env_key and runtime_key == backend_env_key),
        },
    }

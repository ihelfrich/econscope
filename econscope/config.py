"""Central configuration — loads .env keys and sources.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"

load_dotenv(PROJECT_ROOT / ".env")


def get_key(env_var: str) -> Optional[str]:
    return os.environ.get(env_var)


def require_key(env_var: str) -> str:
    val = os.environ.get(env_var)
    if not val:
        raise RuntimeError(
            f"Missing API key: {env_var}. Add it to {PROJECT_ROOT / '.env'}"
        )
    return val

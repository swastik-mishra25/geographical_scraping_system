"""Autonomous geographical discovery and qualification pipeline entry point."""
from __future__ import annotations

from typing import Any

from app.services.orchestrator import execute_autonomous_run


def run_pipeline(
    city: str,
    category: str = "Digital Marketing",
    limit: int = 25,
    state: str = "",
    country: str = "India",
    locality: str = "",
) -> dict[str, Any]:
    """Execute autonomous business discovery pipeline maintaining backward-compatible response contract."""
    return execute_autonomous_run(
        city=city,
        category=category,
        limit=limit,
        state=state,
        country=country,
        locality=locality,
        trigger_type="api",
    )

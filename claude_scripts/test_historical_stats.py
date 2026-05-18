"""Smoke-test the new get_job_historical_stats with timeline filtering.

Usage:
    uv run python claude_scripts/test_historical_stats.py <job_id> <run_id>

Prints the full returned dict plus a one-line summary so we can confirm:
- state_filter_applied (did the timeline join work, or did we fall back?)
- confidence_tier  (high / emerging / limited / none)
- total_runs vs total_runs_unfiltered (how many were excluded as non-SUCCEEDED)
- current_run_state
- comparison + comparison_reference
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.services.databricks_service import DatabricksService  # noqa: E402


def _json_default(obj):
    try:
        return obj.isoformat()
    except AttributeError:
        return str(obj)


async def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: test_historical_stats.py <job_id> <run_id>")
        sys.exit(2)

    job_id, run_id = sys.argv[1], sys.argv[2]
    svc = DatabricksService()
    result = await svc.get_job_historical_stats(
        job_id=job_id, current_run_id=run_id
    )

    print("=== Full dict ===")
    print(json.dumps(result, indent=2, default=_json_default))

    if result is None:
        print("\nERROR: result is None — query failed unexpectedly.")
        sys.exit(1)

    print("\n=== Summary ===")
    keys = [
        "state_filter_applied",
        "confidence_tier",
        "total_runs",
        "total_runs_unfiltered",
        "current_run_state",
        "current_cost",
        "median_cost",
        "avg_cost",
        "comparison",
        "comparison_reference",
        "limited_history",
    ]
    for k in keys:
        print(f"  {k:>22}: {result.get(k)}")


if __name__ == "__main__":
    asyncio.run(main())

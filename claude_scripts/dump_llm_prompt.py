"""Dump the exact user message the LLM service builds for a given job_id+run_id.

Lets us verify that BASELINE_AVAILABLE: YES is reaching the model.

Usage:
    uv run python claude_scripts/dump_llm_prompt.py <job_id> <run_id>
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.services.databricks_service import DatabricksService  # noqa: E402
from server.services.llm_service import LLMService  # noqa: E402


async def main() -> None:
  if len(sys.argv) < 3:
    print('Usage: dump_llm_prompt.py <job_id> <run_id>')
    sys.exit(2)

  job_id, run_id = sys.argv[1], sys.argv[2]
  db = DatabricksService()
  llm = LLMService()

  breakdown = await db.get_job_cost_breakdown(job_id=job_id, run_id=run_id)
  historical = await db.get_job_historical_stats(job_id=job_id, current_run_id=run_id)
  job_name = await db.get_job_name(job_id=job_id)

  if breakdown is None:
    print('No breakdown found.')
    sys.exit(1)

  user_msg = llm._build_job_user_message(
    job_id=job_id,
    cloud_cost=breakdown.cloud_cost,
    databricks_cost=breakdown.databricks_cost,
    total_cost=breakdown.total_cost,
    job_name=job_name,
    historical_stats=historical,
  )

  print('=' * 70)
  print('USER MESSAGE SENT TO LLM:')
  print('=' * 70)
  print(user_msg)
  print('=' * 70)


if __name__ == '__main__':
  asyncio.run(main())

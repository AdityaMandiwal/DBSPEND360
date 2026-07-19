#!/usr/bin/env python3
"""Verify read-time job DBU product breakdown SQL against the warehouse.

Mirrors DatabricksService.get_job_product_breakdown() so it can be run
without standing up the FastAPI app.

Usage:
  uv run claude_scripts/verify_job_product_breakdown.py
  uv run claude_scripts/verify_job_product_breakdown.py \\
    --job-id 164677136540455 --start 2026-05-01 --end 2026-05-31
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

DEFAULT_JOB_ID = "164677136540455"

_PRODUCT_LABELS = {
    "JOBS": "Job Compute",
    "MODEL_SERVING": "Model Serving",
    "AI_FUNCTIONS": "AI Functions",
}


def _resolve_warehouse_id(client: WorkspaceClient, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env_id = os.getenv("DATABRICKS_WAREHOUSE_ID") or os.getenv("WAREHOUSE_ID")
    if env_id:
        return env_id
    try:
        from server.config.config_loader import app_config  # type: ignore

        return app_config.warehouse_id
    except Exception:
        pass
    warehouses = list(client.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouse id available.")
    return warehouses[0].id


def _resolve_table_name(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    try:
        from server.config.config_loader import app_config  # type: ignore

        return app_config.table_name
    except Exception:
        return "dbspend360.03apr.dbspend360_total_job_spends"


def _exec(client: WorkspaceClient, warehouse_id: str, sql: str, wait_timeout: str = "30s"):
    resp = client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=sql,
        wait_timeout=wait_timeout,
    )
    state = resp.status.state if resp.status else None
    waited = 0
    while state in (StatementState.PENDING, StatementState.RUNNING) and waited < 300:
        time.sleep(2)
        waited += 2
        resp = client.statement_execution.get_statement(resp.statement_id)
        state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        err = resp.status.error if resp.status else None
        raise RuntimeError(f"Query failed: state={state} error={err}")
    return resp


def build_breakdown_sql(job_id: str, start: str, end: str) -> str:
    escaped = job_id.replace("'", "''")
    return f"""
    WITH usage_priced AS (
        SELECT
            u.billing_origin_product,
            u.usage_quantity,
            CAST(lp.pricing['default'] AS DOUBLE) AS unit_price
        FROM system.billing.usage u
        LEFT JOIN system.billing.list_prices lp
            ON  u.sku_name = lp.sku_name
            AND u.usage_start_time >= lp.price_start_time
            AND (
                u.usage_start_time < lp.price_end_time
                OR lp.price_end_time IS NULL
            )
        WHERE u.usage_metadata.job_id = '{escaped}'
          AND u.usage_metadata.job_run_id IS NOT NULL
          AND u.usage_date >= '{start}'
          AND u.usage_date <= '{end}'
    )
    SELECT
        COALESCE(billing_origin_product, 'UNKNOWN') AS product,
        ROUND(SUM(usage_quantity * unit_price), 2) AS cost,
        SUM(CASE WHEN unit_price IS NULL THEN usage_quantity ELSE 0 END) AS unpriced_qty
    FROM usage_priced
    GROUP BY 1
    HAVING cost > 0 OR unpriced_qty > 0
    ORDER BY cost DESC
    """


def build_rollup_sql(table_name: str, job_id: str, start: str, end: str) -> str:
    escaped = job_id.replace("'", "''")
    return f"""
    SELECT ROUND(SUM(databricks_cost), 2)
    FROM {table_name}
    WHERE job_id = '{escaped}'
      AND usage_date >= '{start}'
      AND usage_date <= '{end}'
    """


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID)
    parser.add_argument("--start", default="2026-05-01")
    parser.add_argument("--end", default="2026-05-31")
    parser.add_argument("--warehouse-id", default=None)
    parser.add_argument("--table", default=None)
    parser.add_argument("--profile", default=os.getenv("DATABRICKS_CONFIG_PROFILE"))
    args = parser.parse_args()

    if args.profile:
        client = WorkspaceClient(profile=args.profile)
    else:
        client = WorkspaceClient()

    warehouse_id = _resolve_warehouse_id(client, args.warehouse_id)
    table_name = _resolve_table_name(args.table)

    print(f"job_id={args.job_id}  range={args.start}..{args.end}")
    print(f"warehouse={warehouse_id}  rollup_table={table_name}")
    print()

    breakdown_resp = _exec(
        client, warehouse_id, build_breakdown_sql(args.job_id, args.start, args.end)
    )
    rollup_resp = _exec(
        client,
        warehouse_id,
        build_rollup_sql(table_name, args.job_id, args.start, args.end),
    )

    rows = breakdown_resp.result.data_array if breakdown_resp.result else []
    total = 0.0
    print("product breakdown (estimate from system.billing.usage):")
    print(f"  {'product':<20} {'label':<20} {'cost':>12} {'pct':>8}")
    print("  " + "-" * 64)
    for row in rows or []:
        product = row[0] or "UNKNOWN"
        cost = float(row[1] or 0)
        total += cost
        label = _PRODUCT_LABELS.get(product, product)
        pct = (cost / total * 100) if total else 0
        print(f"  {product:<20} {label:<20} {cost:12.2f} {pct:7.1f}%")

    rollup = None
    if rollup_resp.result and rollup_resp.result.data_array:
        raw = rollup_resp.result.data_array[0][0]
        rollup = float(raw) if raw is not None else None

    print()
    print(f"estimate total:  ${total:,.2f}")
    print(f"rollup DBU cost: ${rollup:,.2f}" if rollup is not None else "rollup DBU cost: (none)")
    print()
    print(json.dumps({"total_cost": total, "rollup_databricks_cost": rollup}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

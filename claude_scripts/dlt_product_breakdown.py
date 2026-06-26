#!/usr/bin/env python3
"""Per-product $ + classic-share + snapshot coverage for dlt_pipeline_id spend.

Grounds the 'what should the tab actually show' decision in dollars, not DBU qty.
"""

import json
import subprocess
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

WAREHOUSE_ID = "8baced1ff014912d"

QUERIES = {
    "dollars_by_product_and_mode_30d": """
        SELECT
          u.billing_origin_product                               AS product,
          CASE WHEN u.usage_metadata.cluster_id IS NULL
               THEN 'serverless' ELSE 'classic' END             AS compute_mode,
          COUNT(DISTINCT u.usage_metadata.dlt_pipeline_id)       AS pipelines,
          ROUND(SUM(u.usage_quantity * lp.pricing['default']),0) AS list_dollars
        FROM system.billing.usage u
        LEFT JOIN system.billing.list_prices lp
          ON u.sku_name = lp.sku_name
         AND u.usage_start_time >= lp.price_start_time
         AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
        WHERE u.usage_metadata.dlt_pipeline_id IS NOT NULL
          AND u.usage_date >= current_date() - INTERVAL 30 DAYS
        GROUP BY 1, 2
        ORDER BY list_dollars DESC
    """,
    "snapshot_coverage_by_product_30d": """
        WITH billed AS (
          SELECT DISTINCT workspace_id,
                 usage_metadata.dlt_pipeline_id AS pipeline_id,
                 billing_origin_product         AS product
          FROM system.billing.usage
          WHERE usage_metadata.dlt_pipeline_id IS NOT NULL
            AND usage_date >= current_date() - INTERVAL 30 DAYS
        ),
        snap AS (SELECT DISTINCT workspace_id, pipeline_id FROM system.lakeflow.pipelines)
        SELECT
          b.product,
          COUNT(*)                                                 AS billed_pipelines,
          SUM(CASE WHEN s.pipeline_id IS NULL THEN 1 ELSE 0 END)   AS missing_snapshot
        FROM billed b
        LEFT JOIN snap s
          ON b.workspace_id = s.workspace_id AND b.pipeline_id = s.pipeline_id
        GROUP BY 1
        ORDER BY billed_pipelines DESC
    """,
}


def run(client, label, sql):
    print("=" * 72)
    print(label)
    print("-" * 72)
    resp = client.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="50s"
    )
    state = resp.status.state if resp.status else None
    waited = 0
    while state in (StatementState.PENDING, StatementState.RUNNING) and waited < 300:
        time.sleep(5)
        waited += 5
        resp = client.statement_execution.get_statement(resp.statement_id)
        state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        print(f"  STATE: {state}")
        if resp.status and resp.status.error:
            print(f"  ERROR: {resp.status.error}")
        return
    headers = [c.name for c in resp.manifest.schema.columns]
    print("  " + " | ".join(headers))
    for row in (resp.result.data_array or []):
        print("  " + " | ".join("NULL" if v is None else str(v) for v in row))
    print()


def main():
    tok = json.loads(
        subprocess.check_output(
            ["databricks", "auth", "token", "--profile", "e2-demo-field-eng"]
        )
    )["access_token"]
    client = WorkspaceClient(
        host="https://e2-demo-field-eng.cloud.databricks.com",
        token=tok,
        auth_type="pat",
    )
    for label, sql in QUERIES.items():
        run(client, label, sql)


if __name__ == "__main__":
    main()

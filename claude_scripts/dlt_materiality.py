#!/usr/bin/env python3
"""One-off: DLT materiality check against the dev SQL warehouse.

Runs the council-flagged query plus a couple of follow-ups so we can decide
whether the DLT Pipelines tab is worth building (and revise the plan).
"""

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

WAREHOUSE_ID = "8baced1ff014912d"

QUERIES = {
    "dollars_and_mode_30d": """
        SELECT
          CASE WHEN u.usage_metadata.cluster_id IS NULL
               THEN 'serverless' ELSE 'classic' END      AS compute_mode,
          COUNT(DISTINCT u.usage_metadata.dlt_pipeline_id) AS pipelines,
          SUM(u.usage_quantity)                            AS total_qty,
          SUM(u.usage_quantity * lp.pricing['default'])    AS list_dollars
        FROM system.billing.usage u
        LEFT JOIN system.billing.list_prices lp
          ON u.sku_name = lp.sku_name
         AND u.usage_start_time >= lp.price_start_time
         AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
        WHERE u.usage_metadata.dlt_pipeline_id IS NOT NULL
          AND u.usage_date >= current_date() - INTERVAL 30 DAYS
        GROUP BY 1
        ORDER BY list_dollars DESC
    """,
    "null_price_join_check_30d": """
        SELECT
          COUNT(*)                                                  AS total_rows,
          SUM(CASE WHEN lp.pricing['default'] IS NULL THEN 1 ELSE 0 END) AS null_price_rows
        FROM system.billing.usage u
        LEFT JOIN system.billing.list_prices lp
          ON u.sku_name = lp.sku_name
         AND u.usage_start_time >= lp.price_start_time
         AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
        WHERE u.usage_metadata.dlt_pipeline_id IS NOT NULL
          AND u.usage_date >= current_date() - INTERVAL 30 DAYS
    """,
    "dlt_only_dollars_30d": """
        SELECT
          CASE WHEN u.usage_metadata.cluster_id IS NULL
               THEN 'serverless' ELSE 'classic' END             AS compute_mode,
          COUNT(DISTINCT u.usage_metadata.dlt_pipeline_id)       AS pipelines,
          SUM(u.usage_quantity * lp.pricing['default'])          AS list_dollars
        FROM system.billing.usage u
        LEFT JOIN system.billing.list_prices lp
          ON u.sku_name = lp.sku_name
         AND u.usage_start_time >= lp.price_start_time
         AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
        WHERE u.usage_metadata.dlt_pipeline_id IS NOT NULL
          AND u.billing_origin_product = 'DLT'
          AND u.usage_date >= current_date() - INTERVAL 30 DAYS
        GROUP BY 1
        ORDER BY list_dollars DESC
    """,
}


def run(client, label, sql):
    import time

    print("=" * 72)
    print(label)
    print("-" * 72)
    try:
        resp = client.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="50s"
        )
        state = resp.status.state if resp.status else None
        # Poll until the statement finishes (some aggregates exceed 50s).
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
        rows = resp.result.data_array if resp.result else []
        if not rows:
            print("  (no rows)")
        for row in rows:
            print("  " + " | ".join("NULL" if v is None else str(v) for v in row))
    except Exception as e:
        print(f"  EXCEPTION: {e}")
    print()


def main():
    import json
    import subprocess

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

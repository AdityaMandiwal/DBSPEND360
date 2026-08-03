#!/usr/bin/env python3
"""Pre-implementation validation for the SQL Warehouse costs plan.

Answers three load-bearing questions from the LLM Council verdict:
  1. Is usage_metadata.warehouse_id reliably populated for billing_origin_product = 'SQL'?
  2. How many cluster_ids exist per warehouse-day (grain contradiction check)?
  3. Which SKU types have data, and what warehouse types do they map to?

Also checks:
  4. Does system.compute.warehouses exist and is it accessible?
  5. Do any warehouse cluster_ids appear in the cloud cost explorer?
"""

import os
import sys
import textwrap

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

WAREHOUSE_ID = os.getenv('DBSPEND_WAREHOUSE_ID', '148ccb90800933a1')
SCHEMA = os.getenv('DBSPEND_SCHEMA', 'dbspend360.03apr')
WINDOW_DAYS = int(os.getenv('DBSPEND_WINDOW_DAYS', '30'))

QUERY_1_WAREHOUSE_ID_AND_GRAIN = f"""
SELECT
  sku_name,
  COUNT(*) AS rows,
  COUNT(DISTINCT usage_metadata.warehouse_id) AS distinct_warehouses,
  SUM(CASE WHEN usage_metadata.warehouse_id IS NULL THEN 1 ELSE 0 END) AS null_warehouse_id,
  ROUND(100.0 * SUM(CASE WHEN usage_metadata.warehouse_id IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS null_pct,
  COUNT(DISTINCT usage_metadata.cluster_id) AS distinct_clusters,
  SUM(CASE WHEN usage_metadata.cluster_id IS NULL THEN 1 ELSE 0 END) AS null_cluster_id
FROM system.billing.usage
WHERE billing_origin_product = 'SQL'
  AND usage_date >= date_sub(current_date(), {WINDOW_DAYS})
GROUP BY sku_name
ORDER BY rows DESC
"""

QUERY_2_CLUSTERS_PER_WAREHOUSE_DAY = f"""
SELECT
  usage_metadata.warehouse_id AS warehouse_id,
  usage_date,
  COUNT(DISTINCT usage_metadata.cluster_id) AS cluster_count
FROM system.billing.usage
WHERE billing_origin_product = 'SQL'
  AND usage_date >= date_sub(current_date(), {WINDOW_DAYS})
  AND usage_metadata.warehouse_id IS NOT NULL
  AND usage_metadata.cluster_id IS NOT NULL
GROUP BY usage_metadata.warehouse_id, usage_date
HAVING COUNT(DISTINCT usage_metadata.cluster_id) > 1
ORDER BY cluster_count DESC
LIMIT 20
"""

QUERY_3_SYSTEM_COMPUTE_WAREHOUSES = """
SELECT *
FROM system.compute.warehouses
LIMIT 5
"""

QUERY_4_CLOUD_COST_EXPLORER_TAGS = f"""
WITH wh_clusters AS (
  SELECT DISTINCT usage_metadata.cluster_id AS cluster_id
  FROM system.billing.usage
  WHERE billing_origin_product = 'SQL'
    AND usage_date >= date_sub(current_date(), {WINDOW_DAYS})
    AND usage_metadata.cluster_id IS NOT NULL
)
SELECT
  COUNT(*) AS explorer_rows_matching_wh_clusters,
  COUNT(DISTINCT e.cluster_id) AS distinct_matched_clusters,
  SUM(e.cloud_cost) AS total_cloud_cost
FROM {SCHEMA}.dbspend360_cloud_cost_explorer e
JOIN wh_clusters wc ON e.cluster_id = wc.cluster_id
WHERE e.cost_incurred_date >= date_sub(current_date(), {WINDOW_DAYS})
"""

QUERY_5_WAREHOUSE_TYPE_SUMMARY = f"""
SELECT
  CASE
    WHEN upper(sku_name) LIKE '%SERVERLESS%' THEN 'SERVERLESS'
    WHEN upper(sku_name) LIKE '%PRO%' THEN 'PRO'
    ELSE 'CLASSIC'
  END AS derived_warehouse_type,
  COUNT(DISTINCT usage_metadata.warehouse_id) AS warehouses,
  COUNT(*) AS billing_rows,
  ROUND(SUM(usage_quantity), 2) AS total_dbus
FROM system.billing.usage
WHERE billing_origin_product = 'SQL'
  AND usage_date >= date_sub(current_date(), {WINDOW_DAYS})
GROUP BY 1
ORDER BY total_dbus DESC
"""


def run_query(w, sql, label):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    try:
        resp = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID,
            statement=sql,
            wait_timeout='50s',
        )
        if resp.status and resp.status.state == StatementState.FAILED:
            err = resp.status.error
            print(f"  FAILED: {err.message if err else 'unknown error'}")
            return None
        if resp.manifest and resp.manifest.schema and resp.manifest.schema.columns:
            cols = [c.name for c in resp.manifest.schema.columns]
            print(f"  Columns: {', '.join(cols)}")
        if resp.result and resp.result.data_array:
            for i, row in enumerate(resp.result.data_array):
                print(f"  [{i}] {row}")
            print(f"  ({len(resp.result.data_array)} rows)")
        else:
            print("  (0 rows)")
        return resp
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def main():
    print(f"SQL Warehouse Prerequisites Check")
    print(f"Warehouse: {WAREHOUSE_ID} | Schema: {SCHEMA} | Window: {WINDOW_DAYS} days")

    w = WorkspaceClient()
    me = w.current_user.me()
    print(f"Authenticated as: {me.user_name}")

    run_query(w, QUERY_1_WAREHOUSE_ID_AND_GRAIN,
              "Q1: warehouse_id population + cluster_id per SKU")

    run_query(w, QUERY_2_CLUSTERS_PER_WAREHOUSE_DAY,
              "Q2: Warehouse-days with >1 cluster_id (grain contradiction check)")

    run_query(w, QUERY_3_SYSTEM_COMPUTE_WAREHOUSES,
              "Q3: system.compute.warehouses accessibility")

    run_query(w, QUERY_4_CLOUD_COST_EXPLORER_TAGS,
              "Q4: Cloud cost explorer rows matching warehouse cluster_ids")

    run_query(w, QUERY_5_WAREHOUSE_TYPE_SUMMARY,
              "Q5: Warehouse type distribution (CLASSIC/PRO/SERVERLESS)")

    print(f"\n{'='*70}")
    print("  INTERPRETATION GUIDE")
    print(f"{'='*70}")
    print(textwrap.dedent("""\
      Q1: If null_warehouse_id > 0 for any SKU, the grain assumption is broken.
      Q2: If rows appear, staging grain must be (warehouse_id, usage_date, cluster_id)
          not (warehouse_id, usage_date). The council's grain concern is confirmed.
      Q3: If FAILED, system.compute.warehouses is not accessible; metadata_missing
          fallback will be needed for all warehouses.
      Q4: If explorer_rows_matching_wh_clusters = 0, cloud cost join is dead on
          arrival for Classic/Pro warehouses. Consider DBU-only for v1.
      Q5: Shows the distribution across warehouse types by DBU volume.
    """))


if __name__ == '__main__':
    main()

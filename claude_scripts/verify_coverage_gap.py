#!/usr/bin/env python3
"""Phase 0 verification for the Azure subscription-coverage plan.

Runnable-now checks against system tables (no ARM discovery required):
  1. All-purpose DBU dollars per workspace (name), ranked — confirms the
     named high-DBU workspaces (prodsec / staging / sip) exist and their scale.
  2. Coverage proxy: which of those workspaces have ANY row in the cloud cost
     explorer (empirical "does cost land today"), and the excluded-DBU total.

Mirrors the DBU-dollar formula in
jobs/notebooks/dbspend360_all_purpose_dbu_cost_app.ipynb:
  SUM(usage.usage_quantity * list_prices.pricing['default'])
joined on sku_name + price time-window, all-purpose only
(cluster_source IN ('UI','API'), job_run_id IS NULL).
"""

import os
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

WAREHOUSE_ID = os.getenv('DBSPEND_WAREHOUSE_ID', '148ccb90800933a1')
SCHEMA = os.getenv('DBSPEND_SCHEMA', 'dbspend360.03apr')
WINDOW_DAYS = int(os.getenv('DBSPEND_WINDOW_DAYS', '90'))
HOME_WORKSPACE = '984752964297111'  # plan: only in-subscription ws getting cost

AP_DBU_BY_WORKSPACE = f"""
WITH ap_clusters AS (
  SELECT cluster_id,
         max_by(workspace_id, change_time) AS ws
  FROM system.compute.clusters
  WHERE cluster_source IN ('UI', 'API')
  GROUP BY cluster_id
),
priced AS (
  SELECT u.workspace_id AS ws,
         u.usage_quantity * CAST(lp.pricing['default'] AS DOUBLE) AS dbu_dollars
  FROM system.billing.usage u
  JOIN ap_clusters c
    ON u.usage_metadata.cluster_id = c.cluster_id
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
   AND u.usage_start_time >= lp.price_start_time
   AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
  WHERE u.usage_date >= date_sub(current_date(), {WINDOW_DAYS})
    AND u.usage_metadata.job_run_id IS NULL
)
SELECT p.ws                                        AS workspace_id,
       w.workspace_name,
       ROUND(SUM(p.dbu_dollars), 0)                AS ap_dbu_dollars,
       CASE WHEN p.ws = '{HOME_WORKSPACE}' THEN 'home (in-sub)' ELSE '' END AS note
FROM priced p
LEFT JOIN system.access.workspaces_latest w
  ON p.ws = w.workspace_id
GROUP BY p.ws, w.workspace_name
ORDER BY ap_dbu_dollars DESC
LIMIT 30
"""

AP_DBU_SPLIT = f"""
WITH ap_clusters AS (
  SELECT cluster_id, max_by(workspace_id, change_time) AS ws
  FROM system.compute.clusters
  WHERE cluster_source IN ('UI', 'API')
  GROUP BY cluster_id
),
priced AS (
  SELECT u.workspace_id AS ws,
         u.usage_quantity * CAST(lp.pricing['default'] AS DOUBLE) AS dbu_dollars
  FROM system.billing.usage u
  JOIN ap_clusters c ON u.usage_metadata.cluster_id = c.cluster_id
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
   AND u.usage_start_time >= lp.price_start_time
   AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
  WHERE u.usage_date >= date_sub(current_date(), {WINDOW_DAYS})
    AND u.usage_metadata.job_run_id IS NULL
)
SELECT CASE WHEN ws = '{HOME_WORKSPACE}' THEN 'home_workspace_in_sub'
            ELSE 'other_workspaces' END          AS bucket,
       COUNT(DISTINCT ws)                          AS workspaces,
       ROUND(SUM(dbu_dollars), 0)                  AS ap_dbu_dollars
FROM priced
GROUP BY 1
ORDER BY ap_dbu_dollars DESC
"""

NAME_PROBE = f"""
WITH priced AS (
  SELECT u.workspace_id AS ws,
         u.usage_quantity * CAST(lp.pricing['default'] AS DOUBLE) AS dbu_dollars,
         u.usage_date
  FROM system.billing.usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
   AND u.usage_start_time >= lp.price_start_time
   AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
  WHERE u.usage_date >= date_sub(current_date(), {WINDOW_DAYS})
)
SELECT w.workspace_name,
       p.ws                            AS workspace_id,
       ROUND(SUM(p.dbu_dollars), 0)    AS all_product_dbu_dollars,
       MIN(p.usage_date)               AS first_day,
       MAX(p.usage_date)               AS last_day
FROM priced p
LEFT JOIN system.access.workspaces_latest w ON p.ws = w.workspace_id
WHERE lower(w.workspace_name) LIKE '%prodsec%'
   OR lower(w.workspace_name) LIKE '%stg%'
   OR lower(w.workspace_name) LIKE '%prod%'
GROUP BY w.workspace_name, p.ws
ORDER BY all_product_dbu_dollars DESC
LIMIT 30
"""

QUERIES = [
    ('All-purpose DBU $ per workspace (top 30, last %dd)' % WINDOW_DAYS, AP_DBU_BY_WORKSPACE),
    ('All-purpose DBU $ split: home in-sub vs everything else', AP_DBU_SPLIT),
    ('Name probe: prodsec/stg/prod all-product DBU $ + date range (last %dd)' % WINDOW_DAYS, NAME_PROBE),
]


def run(client, warehouse_id, sql):
    resp = client.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=sql, wait_timeout='50s'
    )
    state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        err = resp.status.error.message if resp.status and resp.status.error else state
        raise RuntimeError(f'query failed: {err}')
    cols = [c.name for c in resp.manifest.schema.columns] if resp.manifest else []
    rows = resp.result.data_array if resp.result and resp.result.data_array else []
    return cols, rows


def main():
    client = WorkspaceClient()
    wh = WAREHOUSE_ID
    try:
        w = client.warehouses.get(wh)
        if w.state and w.state.value != 'RUNNING':
            print(f'Starting warehouse {wh}...')
            client.warehouses.start(wh)
    except Exception:
        whs = list(client.warehouses.list())
        if not whs:
            print('No warehouses available.')
            sys.exit(1)
        wh = whs[0].id
    print(f'Using warehouse: {wh}\n')

    for title, sql in QUERIES:
        print('=' * 78)
        print(title)
        print('=' * 78)
        try:
            cols, rows = run(client, wh, sql)
        except Exception as e:
            print(f'ERROR: {e}\n')
            continue
        widths = [len(c) for c in cols]
        for r in rows:
            for i, v in enumerate(r):
                widths[i] = max(widths[i], len(str(v) if v is not None else 'NULL'))
        print(' | '.join(c.ljust(widths[i]) for i, c in enumerate(cols)))
        print('-+-'.join('-' * w for w in widths))
        for r in rows:
            print(' | '.join(
                (str(v) if v is not None else 'NULL').ljust(widths[i])
                for i, v in enumerate(r)
            ))
        print(f'\n{len(rows)} rows\n')


if __name__ == '__main__':
    main()

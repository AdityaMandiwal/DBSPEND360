#!/usr/bin/env python3
"""Investigate whether Pro/Classic SQL Warehouses have attributable Azure VM cost.

Motivation
----------
The audit report and downstream docs / prompts / banner copy assert:
    "SQL Warehouses run on Databricks-managed compute, so DBU IS the complete
    cost."

That statement is strictly true for Serverless SQL Warehouses (compute runs in
Databricks' Azure subscription). For Pro and Classic SQL Warehouses on Azure,
compute runs in the CUSTOMER's Azure subscription — meaning the customer sees
separate Azure VM cost that DBSpend360 currently attributes to no tab.

This script gathers evidence to answer three questions:

    Q1. Is the "no cloud cost" claim wrong for Pro/Classic warehouses in this
        deployment's audit window?
    Q2. If so, is the cost material enough to justify plumbing a `cloud_cost`
        column into the SQL Warehouse rollup?
    Q3. Is there a viable tag/join path from Azure VM cost → warehouse_id, or
        is the attribution problem effectively unsolvable with today's data?

Approach
--------
1. Enumerate the Pro/Classic warehouses in the audit window ($6,522.66 DBU).
2. Cross-check `system.compute.clusters` for any cluster_source signalling
   SQL-warehouse-backed compute (Pro/Classic spin up internal compute clusters).
3. Sample `system.billing.usage.custom_tags` for SQL-origin rows to see what
   tag keys are STAMPED on Databricks' side (Azure Cost Management would see
   the same tag keys on the VMs).
4. Check whether `dbspend360.03apr.dbspend360_cloud_cost_explorer` already
   contains any cluster_ids that match Pro/Classic warehouse internal
   clusters — an indirect signal that Azure IS billing VMs for them.
5. Print a decision matrix: is Fix option 3 (cloud_cost column) worth it?

Run
---
    uv run python claude_scripts/investigate_sql_warehouse_cloud_cost.py
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, List

from dotenv import load_dotenv

load_dotenv(".env.local")

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementState  # noqa: E402

WAREHOUSE_ID = os.getenv("DBSPEND_WAREHOUSE_ID", "148ccb90800933a1")
ROLLUP = os.getenv(
    "DBSPEND_ROLLUP",
    "dbspend360.03apr.dbspend360_total_sql_warehouse_spends",
)
STAGING = os.getenv(
    "DBSPEND_STAGING",
    "dbspend360.03apr.dbspend360_sql_warehouse_dbu_cost",
)
CLOUD_EXPLORER = os.getenv(
    "DBSPEND_CLOUD_EXPLORER",
    "dbspend360.03apr.dbspend360_cloud_cost_explorer",
)

END_DATE = date(2026, 8, 6)
START_DATE = date(2026, 7, 7)

w = WorkspaceClient()


def sql(statement: str) -> List[List[Any]]:
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=statement,
        wait_timeout="50s",
    )
    if r.status and r.status.state == StatementState.FAILED:
        err = r.status.error
        raise RuntimeError(f"SQL failed: {err.message if err else 'unknown'}")
    if r.result and r.result.data_array:
        return r.result.data_array
    return []


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n  {title}\n{'=' * 78}")


section("Q1 — Pro/Classic warehouses in the audit window")
pro_classic = sql(
    f"""
    WITH filtered AS (
      SELECT *
      FROM {ROLLUP}
      WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
    ),
    per_wh AS (
      SELECT
        warehouse_id,
        COALESCE(ANY_VALUE(warehouse_name), '') AS warehouse_name,
        UPPER(COALESCE(ANY_VALUE(warehouse_type), 'UNKNOWN')) AS warehouse_type,
        ANY_VALUE(workspace_id) AS workspace_id,
        SUM(databricks_cost) AS dbu
      FROM filtered
      GROUP BY warehouse_id
    )
    SELECT warehouse_id, warehouse_name, warehouse_type, workspace_id, dbu
    FROM per_wh
    WHERE warehouse_type IN ('PRO', 'CLASSIC')
    ORDER BY dbu DESC
    """
)
print(
    f"Found {len(pro_classic)} Pro/Classic warehouses "
    f"(sum DBU = ${sum(float(r[4]) for r in pro_classic):,.2f})"
)
for r in pro_classic[:10]:
    wh_id, wh_name, wh_type, ws_id, dbu = r
    name = wh_name if wh_name else f"<unnamed {wh_id}>"
    print(f"  {wh_type:8s} ${float(dbu):>10,.2f}  ws={ws_id}  {name}")
if len(pro_classic) > 10:
    print(f"  ... and {len(pro_classic) - 10} more")

pro_classic_workspaces = sorted({r[3] for r in pro_classic if r[3]})
pro_classic_ids = [r[0] for r in pro_classic]


section("Q3a — What tags does system.billing.usage carry for SQL-origin rows?")
tag_sample = sql(
    f"""
    SELECT
      usage_date,
      workspace_id,
      usage_metadata.warehouse_id AS warehouse_id,
      usage_metadata.cluster_id  AS cluster_id,
      custom_tags,
      usage_quantity
    FROM system.billing.usage
    WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
      AND billing_origin_product = 'SQL'
      AND usage_metadata.warehouse_id IS NOT NULL
      AND workspace_id IN ({', '.join(f"'{w}'" for w in pro_classic_workspaces[:5])})
    LIMIT 10
    """
)
print(f"Sampled {len(tag_sample)} SQL-origin usage rows from Pro/Classic workspaces:")
for row in tag_sample:
    print(
        f"  ws={row[1]}  wh={row[2]}  cluster_id={row[3]}  "
        f"qty={row[5]}  tags={row[4]}"
    )


section(
    "Q3b — Does system.compute.clusters have entries for SQL-warehouse-backed compute?"
)
sql_clusters = sql(
    f"""
    SELECT
      cluster_source,
      COUNT(DISTINCT cluster_id) AS distinct_clusters,
      COUNT(*) AS rows
    FROM system.compute.clusters
    WHERE workspace_id IN ({', '.join(f"'{w}'" for w in pro_classic_workspaces)})
      AND change_time >= '{START_DATE}'
    GROUP BY cluster_source
    ORDER BY rows DESC
    """
)
for row in sql_clusters:
    print(f"  cluster_source={row[0]:20s}  distinct_clusters={row[1]}  rows={row[2]}")

section(
    "Q3c — Do any cluster_ids in system.compute.clusters carry SQL warehouse tags?"
)
sql_tagged_clusters = sql(
    f"""
    SELECT
      cluster_id,
      cluster_source,
      cluster_name,
      tags
    FROM system.compute.clusters
    WHERE workspace_id IN ({', '.join(f"'{w}'" for w in pro_classic_workspaces)})
      AND change_time >= '{START_DATE}'
      AND (
        cluster_source LIKE '%SQL%'
        OR cluster_name LIKE '%warehouse%'
        OR cluster_name LIKE '%endpoint%'
        OR tags['SqlEndpointId'] IS NOT NULL
        OR tags['WarehouseId'] IS NOT NULL
        OR tags['DatabricksSqlEndpointId'] IS NOT NULL
      )
    LIMIT 20
    """
)
print(f"Found {len(sql_tagged_clusters)} clusters possibly linked to SQL warehouses")
for row in sql_tagged_clusters[:5]:
    print(f"  cluster_id={row[0]} source={row[1]} name={row[2]!r}")
    print(f"    tags={row[3]}")


section(
    "Q2 — Is any Pro/Classic warehouse's workspace present in cloud_cost_explorer?"
)
cloud_cost_by_ws = sql(
    f"""
    SELECT
      cce.cluster_id,
      SUM(cce.cloud_cost) AS cloud_cost,
      cc.cluster_source,
      cc.cluster_name
    FROM {CLOUD_EXPLORER} cce
    LEFT JOIN system.compute.clusters cc
      ON cce.cluster_id = cc.cluster_id
    WHERE cce.cost_incurred_date >= '{START_DATE}'
      AND cce.cost_incurred_date <= '{END_DATE}'
      AND cc.workspace_id IN ({', '.join(f"'{w}'" for w in pro_classic_workspaces)})
    GROUP BY cce.cluster_id, cc.cluster_source, cc.cluster_name
    HAVING SUM(cce.cloud_cost) > 0
    ORDER BY cloud_cost DESC
    LIMIT 20
    """
)
print(
    f"Top attributed cloud cost lines from Pro/Classic warehouses' workspaces "
    f"(showing top 20 of possibly more):"
)
for row in cloud_cost_by_ws:
    print(
        f"  ${float(row[1]):>10,.2f}  source={row[2]!r:20s}  "
        f"cluster_id={row[0]}  name={row[3]!r}"
    )


section("Q2b — Sum of cloud cost currently attributed to any workspace with Pro/Classic")
totals = sql(
    f"""
    SELECT
      COUNT(DISTINCT cce.cluster_id) AS distinct_clusters_with_cost,
      COALESCE(SUM(cce.cloud_cost), 0) AS total_cloud_cost
    FROM {CLOUD_EXPLORER} cce
    LEFT JOIN system.compute.clusters cc
      ON cce.cluster_id = cc.cluster_id
    WHERE cce.cost_incurred_date >= '{START_DATE}'
      AND cce.cost_incurred_date <= '{END_DATE}'
      AND cc.workspace_id IN ({', '.join(f"'{w}'" for w in pro_classic_workspaces)})
    """
)
if totals:
    dc, tc = totals[0]
    print(
        f"  distinct_clusters_with_cost={dc}  "
        f"total_cloud_cost=${float(tc):,.2f}"
    )

print()
print("=" * 78)
print("  Decision inputs collected. See above for evidence.")
print("=" * 78)

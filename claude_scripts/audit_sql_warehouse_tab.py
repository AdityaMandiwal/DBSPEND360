#!/usr/bin/env python3
"""End-to-end audit of the deployed SQL Warehouse tab.

Cross-references the deployed FastAPI endpoints against direct SQL queries
on the underlying rollup + staging + system tables to verify every metric
matches its source data and expected business logic.

Sections verified:
  A. /api/warehouses/summary  (KPI strip)
  B. /api/warehouses/grouped  (By-Warehouse table + per-day drill-down)
  C. /api/warehouses/top-warehouses  (top-N card)
  D. /api/warehouses/{id}/details    (details modal metadata + tags)
  E. Rollup vs. staging table reconciliation
  F. Staging vs. system.billing.usage reconciliation
  G. workspace_covered / dbu_in_non_covered_workspaces cross-check
  H. metadata_missing distribution + three-state badge invariant
  I. warehouse_type bucket parity between UI and SQL
  J. days[] sum invariant, pagination totals, edge cases
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from dotenv import load_dotenv

load_dotenv('.env.local')

WAREHOUSE_ID = os.getenv('DBSPEND_WAREHOUSE_ID', '148ccb90800933a1')
ROLLUP_TABLE = os.getenv('DBSPEND_ROLLUP', 'dbspend360.03apr.dbspend360_total_sql_warehouse_spends')
STAGING_TABLE = os.getenv('DBSPEND_STAGING', 'dbspend360.03apr.dbspend360_sql_warehouse_dbu_cost')
COVERED_TABLE = os.getenv('DBSPEND_COVERED', 'dbspend360.03apr.dbspend360_covered_workspaces')
APP_URL = os.getenv('DBSPEND_APP_URL',
                    'https://dbspend360-984752964297111.11.azure.databricksapps.com')

END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=30)


class Findings:
    def __init__(self) -> None:
        self.ok: List[str] = []
        self.warn: List[str] = []
        self.bad: List[str] = []

    def ok_(self, msg: str) -> None:
        self.ok.append(msg)
        print(f'  \u2713 OK    {msg}')

    def warn_(self, msg: str) -> None:
        self.warn.append(msg)
        print(f'  ! WARN  {msg}')

    def bad_(self, msg: str) -> None:
        self.bad.append(msg)
        print(f'  X FAIL  {msg}')


F = Findings()


def sql(w: WorkspaceClient, statement: str) -> List[List[Any]]:
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=statement,
        wait_timeout='50s',
    )
    if resp.status and resp.status.state == StatementState.FAILED:
        err = resp.status.error
        raise RuntimeError(f'SQL failed: {err.message if err else "unknown"}')
    if resp.result and resp.result.data_array:
        return resp.result.data_array
    return []


def get_oauth_token() -> str:
    profile = os.getenv('DATABRICKS_CONFIG_PROFILE', 'fevm')
    result = subprocess.run(
        ['databricks', 'auth', 'token', '--profile', profile],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)['access_token']


def http_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    token = get_oauth_token()
    resp = requests.get(
        f'{APP_URL}{path}',
        params=params,
        headers={'Authorization': f'Bearer {token}'},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def section(title: str) -> None:
    print(f'\n{"=" * 78}\n  {title}\n{"=" * 78}')


def main() -> int:
    w = WorkspaceClient()
    me = w.current_user.me()
    print(f'Authenticated as: {me.user_name}')
    print(f'App URL:  {APP_URL}')
    print(f'Rollup:   {ROLLUP_TABLE}')
    print(f'Staging:  {STAGING_TABLE}')
    print(f'Window:   {START_DATE} to {END_DATE}')

    section('A. GROUND TRUTH: rollup aggregates for the window')
    rollup_agg = sql(w, f"""
        SELECT
          COUNT(DISTINCT warehouse_id) AS distinct_warehouses,
          COUNT(*) AS raw_rows,
          COALESCE(SUM(databricks_cost), 0) AS sum_dbu,
          COALESCE(SUM(total_cost), 0) AS sum_total,
          COALESCE(SUM(CASE WHEN COALESCE(workspace_covered, true) THEN total_cost ELSE 0 END), 0) AS sum_total_covered,
          COALESCE(SUM(CASE WHEN COALESCE(workspace_covered, true) THEN databricks_cost ELSE 0 END), 0) AS sum_dbu_covered,
          COALESCE(SUM(CASE WHEN NOT COALESCE(workspace_covered, true) THEN databricks_cost ELSE 0 END), 0) AS sum_dbu_noncov,
          MIN(usage_date), MAX(usage_date)
        FROM {ROLLUP_TABLE}
        WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
    """)[0]

    (distinct_wh, raw_rows, sum_dbu, sum_total,
     sum_total_cov, sum_dbu_cov, sum_dbu_noncov,
     min_date, max_date) = rollup_agg
    # Statement Execution API returns everything as strings; coerce numerics.
    distinct_wh = int(distinct_wh)
    raw_rows = int(raw_rows)
    sum_dbu = float(sum_dbu)
    sum_total = float(sum_total)
    sum_total_cov = float(sum_total_cov)
    sum_dbu_cov = float(sum_dbu_cov)
    sum_dbu_noncov = float(sum_dbu_noncov)
    print(f'  distinct_warehouses={distinct_wh}  raw_rows={raw_rows}')
    print(f'  sum_dbu={float(sum_dbu):.2f}  sum_total={float(sum_total):.2f}')
    print(f'  sum_total_covered={float(sum_total_cov):.2f}  sum_dbu_covered={float(sum_dbu_cov):.2f}')
    print(f'  sum_dbu_non_covered={float(sum_dbu_noncov):.2f}')
    print(f'  date range: {min_date} .. {max_date}')

    # Warehouse-level rollup (matches Backend group-by)
    type_bucket_sql = """CASE
        WHEN UPPER(COALESCE(warehouse_type, '')) LIKE '%PRO%' THEN 'PRO'
        WHEN UPPER(COALESCE(warehouse_type, '')) = 'CLASSIC' THEN 'CLASSIC'
        ELSE 'SERVERLESS' END"""
    wh_split = sql(w, f"""
        WITH filtered AS (
          SELECT * FROM {ROLLUP_TABLE}
          WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
        ),
        wh AS (
          SELECT warehouse_id,
                 MAX({type_bucket_sql}) AS type_bucket,
                 SUM(total_cost) AS wh_cost,
                 SUM(databricks_cost) AS wh_dbu,
                 BOOL_AND(COALESCE(workspace_covered, true)) AS wsc
          FROM filtered
          GROUP BY warehouse_id
        )
        SELECT COUNT(*),
               SUM(CASE WHEN type_bucket='CLASSIC' THEN 1 ELSE 0 END),
               SUM(CASE WHEN type_bucket='PRO' THEN 1 ELSE 0 END),
               SUM(CASE WHEN type_bucket='SERVERLESS' THEN 1 ELSE 0 END),
               COALESCE(SUM(CASE WHEN wsc THEN wh_cost ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN wsc AND type_bucket='CLASSIC' THEN wh_cost ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN wsc AND type_bucket='PRO' THEN wh_cost ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN wsc AND type_bucket='SERVERLESS' THEN wh_cost ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN wsc THEN wh_dbu ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN NOT wsc THEN wh_dbu ELSE 0 END), 0)
        FROM wh
    """)[0]
    (gt_total_wh, gt_classic_wh, gt_pro_wh, gt_serverless_wh,
     gt_total_spend, gt_classic_spend, gt_pro_spend, gt_serverless_spend,
     gt_total_dbu, gt_dbu_noncov) = [
        int(x) if i < 4 else float(x) for i, x in enumerate(wh_split)]
    print(f'  ground-truth: total_warehouses={gt_total_wh}  classic={gt_classic_wh} pro={gt_pro_wh} serverless={gt_serverless_wh}')
    print(f'  ground-truth: total_spend={gt_total_spend:.2f}  classic={gt_classic_spend:.2f} pro={gt_pro_spend:.2f} serverless={gt_serverless_spend:.2f}')
    print(f'  ground-truth: total_dbu={gt_total_dbu:.2f}  dbu_noncov={gt_dbu_noncov:.2f}')

    section('B. /api/warehouses/summary')
    summary = http_get('/api/warehouses/summary', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
    })
    print(json.dumps(summary, indent=2))

    def cmp(label: str, api_v: float, gt_v: float, tol: float = 0.01) -> None:
        if isinstance(api_v, int) and isinstance(gt_v, int):
            if api_v == gt_v:
                F.ok_(f'{label}: {api_v}')
            else:
                F.bad_(f'{label}: api={api_v} vs. sql={gt_v}')
        else:
            diff = abs(float(api_v) - float(gt_v))
            if diff <= tol:
                F.ok_(f'{label}: {api_v:.4f}')
            else:
                F.bad_(f'{label}: api={api_v:.4f} vs. sql={gt_v:.4f}  (diff={diff:.4f})')

    cmp('total_warehouses', summary['total_warehouses'], gt_total_wh)
    cmp('classic_warehouses', summary['classic_warehouses'], gt_classic_wh)
    cmp('pro_warehouses', summary['pro_warehouses'], gt_pro_wh)
    cmp('serverless_warehouses', summary['serverless_warehouses'], gt_serverless_wh)
    cmp('total_spend', summary['total_spend'], gt_total_spend)
    cmp('classic_spend', summary['classic_spend'], gt_classic_spend)
    cmp('pro_spend', summary['pro_spend'], gt_pro_spend)
    cmp('serverless_spend', summary['serverless_spend'], gt_serverless_spend)
    cmp('total_databricks_cost', summary['total_databricks_cost'], gt_total_dbu)
    cmp('dbu_in_non_covered_workspaces',
        summary.get('dbu_in_non_covered_workspaces', 0.0), gt_dbu_noncov)

    # Invariant: exhaustive three-bucket split
    if (summary['classic_warehouses'] + summary['pro_warehouses']
            + summary['serverless_warehouses']) == summary['total_warehouses']:
        F.ok_('count split is exhaustive (classic+pro+serverless == total)')
    else:
        F.bad_('count split not exhaustive!')

    triple = summary['classic_spend'] + summary['pro_spend'] + summary['serverless_spend']
    if abs(triple - summary['total_spend']) <= 0.02:
        F.ok_(f'$ split is exhaustive (sum={triple:.4f} == total_spend={summary["total_spend"]:.4f})')
    else:
        F.bad_(f'$ split not exhaustive (sum={triple:.4f} vs. total={summary["total_spend"]:.4f})')

    if abs(summary['total_spend'] - summary['total_databricks_cost']) <= 0.01:
        F.ok_('DBU-only invariant: total_spend == total_databricks_cost')
    else:
        F.bad_(f'DBU-only invariant broken: total_spend={summary["total_spend"]:.4f} '
               f'total_databricks_cost={summary["total_databricks_cost"]:.4f}')

    api_days = summary['date_range_days']
    expected_days = (END_DATE - START_DATE).days + 1
    if api_days == expected_days:
        F.ok_(f'date_range_days: {api_days}')
    else:
        F.bad_(f'date_range_days: api={api_days} vs. expected={expected_days}')

    section('C. /api/warehouses/grouped')
    grouped = http_get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'page': 1,
        'per_page': 1000,
    })
    print(f'  total_count={grouped["total_count"]}  page={grouped["page"]} of {grouped["total_pages"]}')
    if grouped['total_count'] == gt_total_wh:
        F.ok_(f'grouped total_count == warehouse count ({gt_total_wh})')
    else:
        F.bad_(f'grouped total_count={grouped["total_count"]} vs. sql={gt_total_wh}')

    # Sum of returned rows' total_cost == warehouse-level SUM
    api_row_sum = sum(r['total_cost'] for r in grouped['data'])
    if abs(api_row_sum - float(sum_total)) <= 0.02:
        F.ok_(f'grouped row-total sum matches rollup sum ({api_row_sum:.4f})')
    else:
        F.bad_(f'grouped row sum={api_row_sum:.4f} vs. rollup sum={float(sum_total):.4f}')

    # Per-row days[] sum invariant
    invariant_break = 0
    active_days_mismatch = 0
    for r in grouped['data']:
        days_sum = sum(d['total_cost'] for d in r['days'])
        if abs(days_sum - r['total_cost']) > 0.005:
            invariant_break += 1
            if invariant_break <= 3:
                F.bad_(f'days invariant broken for {r["warehouse_id"]}: '
                       f'row.total_cost={r["total_cost"]:.4f} vs. sum(days)={days_sum:.4f}')
        # active_days should equal len(days)
        if len(r['days']) != r['active_days']:
            active_days_mismatch += 1
            if active_days_mismatch <= 3:
                F.bad_(f'active_days mismatch for {r["warehouse_id"]}: '
                       f'row.active_days={r["active_days"]} vs. len(days)={len(r["days"])}')

    if invariant_break == 0:
        F.ok_(f'days[] sum invariant holds for all {len(grouped["data"])} rows')
    else:
        F.bad_(f'days[] sum invariant broken for {invariant_break} rows')

    if active_days_mismatch == 0:
        F.ok_(f'active_days matches len(days) for all {len(grouped["data"])} rows')
    else:
        F.bad_(f'active_days mismatches len(days) for {active_days_mismatch} rows')

    # Sort order: descending by total_cost
    sorted_ok = all(
        grouped['data'][i]['total_cost'] >= grouped['data'][i + 1]['total_cost']
        for i in range(len(grouped['data']) - 1)
    )
    F.ok_('rows sorted by total_cost DESC') if sorted_ok else F.bad_('rows not DESC-sorted!')

    section('D. /api/warehouses/top-warehouses')
    top = http_get('/api/warehouses/top-warehouses', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'limit': 5,
    })
    if len(top) <= 5:
        F.ok_(f'top returned {len(top)} rows (<= limit)')
    else:
        F.bad_(f'top returned {len(top)} > limit=5')

    # Top rows should exactly match first 5 grouped rows on total_cost
    grouped_top5 = [(r['warehouse_id'], r['total_cost']) for r in grouped['data'][:5]]
    api_top5 = [(r['warehouse_id'], r['total_cost']) for r in top]
    if grouped_top5 == api_top5:
        F.ok_('top-warehouses[:5] matches grouped[:5] by (id, total_cost)')
    else:
        F.bad_(f'top vs. grouped mismatch:\n  top={api_top5}\n  grouped={grouped_top5}')

    # top has days=[]
    if all(r['days'] == [] for r in top):
        F.ok_('top-warehouses returns days=[] for all rows (spec)')
    else:
        F.bad_('top-warehouses carries days[] (should be empty)')

    section('E. Rollup vs. staging reconciliation')
    stg = sql(w, f"""
        SELECT COALESCE(SUM(databricks_cost), 0),
               COUNT(*),
               COUNT(DISTINCT warehouse_id)
        FROM {STAGING_TABLE}
        WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
    """)[0]
    stg_sum, stg_rows, stg_wh = float(stg[0]), int(stg[1]), int(stg[2])
    print(f'  staging: rows={stg_rows}  distinct_warehouses={stg_wh}  sum_dbu={stg_sum:.2f}')
    if abs(stg_sum - float(sum_dbu)) <= 0.05:
        F.ok_(f'rollup SUM(databricks_cost) matches staging ({stg_sum:.2f})')
    else:
        F.bad_(f'rollup vs. staging drift: rollup={float(sum_dbu):.2f} staging={stg_sum:.2f}')
    if raw_rows == stg_rows:
        F.ok_(f'rollup row count matches staging ({raw_rows})')
    else:
        F.warn_(f'row-count differs (rollup={raw_rows}, staging={stg_rows}) '
                '- expected equal at (warehouse_id, usage_date) grain')
    if distinct_wh == stg_wh:
        F.ok_(f'distinct warehouse count matches ({distinct_wh})')
    else:
        F.warn_(f'distinct warehouses drift: rollup={distinct_wh} vs. staging={stg_wh}')

    section('F. Staging vs. system.billing.usage reconciliation')
    usage_agg = sql(w, f"""
        SELECT
          COUNT(*) AS rows,
          COUNT(DISTINCT usage_metadata.warehouse_id) AS distinct_wh,
          COUNT(DISTINCT usage_metadata.cluster_id) AS distinct_clusters,
          SUM(CASE WHEN usage_metadata.cluster_id IS NOT NULL THEN 1 ELSE 0 END) AS non_null_cluster_id
        FROM system.billing.usage
        WHERE billing_origin_product = 'SQL'
          AND usage_metadata.warehouse_id IS NOT NULL
          AND usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
    """)[0]
    src_rows, src_wh, src_clusters, src_non_null_cluster = [int(x) for x in usage_agg]
    print(f'  system.billing.usage: rows={src_rows}  distinct_wh={src_wh}  '
          f'distinct_clusters={src_clusters}  non_null_cluster_id={src_non_null_cluster}')
    if src_wh == stg_wh:
        F.ok_(f'system.billing.usage distinct_wh matches staging ({src_wh})')
    else:
        F.warn_(f'distinct_wh drift usage={src_wh} vs. staging={stg_wh}')

    if src_non_null_cluster == 0:
        F.ok_('cluster_id 100% NULL for SQL-origin warehouse rows (spec: no cluster in grain)')
    else:
        F.warn_(f'{src_non_null_cluster} SQL usage rows have non-null cluster_id '
                f'(staging drops it - possible per-cluster loss)')

    # SKU-derived warehouse_type buckets in staging
    stg_types = sql(w, f"""
        SELECT
          CASE WHEN UPPER(sku_name) LIKE '%SERVERLESS%' THEN 'SERVERLESS'
               WHEN UPPER(sku_name) LIKE '%PRO%' THEN 'PRO'
               ELSE 'CLASSIC' END AS sku_bucket,
          warehouse_type AS staging_type,
          COUNT(*) AS rows
        FROM {STAGING_TABLE}
        WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)
    mismatched = [row for row in stg_types if row[0] != row[1]]
    if not mismatched:
        F.ok_(f'staging.warehouse_type derived from sku_name matches SKU bucket rule ({len(stg_types)} classes)')
    else:
        F.bad_(f'staging.warehouse_type != SKU bucket for {len(mismatched)} classes: {mismatched}')

    section('G. Coverage cross-check (dbu_in_non_covered_workspaces)')
    covered = sql(w, f"""SELECT COUNT(*), COUNT(DISTINCT workspace_id) FROM {COVERED_TABLE}""")[0]
    print(f'  covered_workspaces table: rows={int(covered[0])}  distinct_ws={int(covered[1])}')
    # Cross-check the non-covered slice from rollup
    non_cov = sql(w, f"""
        SELECT COUNT(DISTINCT warehouse_id),
               COALESCE(SUM(databricks_cost), 0),
               COALESCE(SUM(total_cost), 0)
        FROM {ROLLUP_TABLE}
        WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
          AND workspace_covered = false
    """)[0]
    print(f'  rollup non-covered: distinct_wh={int(non_cov[0])}  sum_dbu={float(non_cov[1]):.2f}  '
          f'sum_total={float(non_cov[2]):.2f}')
    if abs(summary.get('dbu_in_non_covered_workspaces', 0.0) - float(non_cov[1])) <= 0.01:
        F.ok_('dbu_in_non_covered_workspaces matches rollup non-covered sum')
    else:
        F.bad_(f'dbu_in_non_covered_workspaces mismatch: '
               f'api={summary.get("dbu_in_non_covered_workspaces")} '
               f'sql={float(non_cov[1])}')

    section('H. metadata_missing distribution')
    meta_dist = sql(w, f"""
        WITH wh AS (
          SELECT warehouse_id, BOOL_OR(metadata_missing) AS mm
          FROM {ROLLUP_TABLE}
          WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
          GROUP BY warehouse_id
        )
        SELECT SUM(CASE WHEN mm THEN 1 ELSE 0 END), SUM(CASE WHEN NOT mm THEN 1 ELSE 0 END), COUNT(*)
        FROM wh
    """)[0]
    mm_count, has_meta, total = int(meta_dist[0]), int(meta_dist[1]), int(meta_dist[2])
    pct_missing = (100.0 * mm_count / total) if total else 0.0
    print(f'  metadata_missing warehouses: {mm_count}/{total} ({pct_missing:.1f}%)  has_metadata: {has_meta}')

    # Cross-check: any warehouse with metadata_missing=true but warehouse_name populated to something
    #              other than the "Warehouse <id>" sentinel is inconsistent.
    bad_meta = sql(w, f"""
        WITH wh AS (
          SELECT warehouse_id,
                 BOOL_OR(metadata_missing) AS mm,
                 MAX(warehouse_name) AS wname
          FROM {ROLLUP_TABLE}
          WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
          GROUP BY warehouse_id
        )
        SELECT COUNT(*)
        FROM wh
        WHERE mm = true
          AND wname IS NOT NULL
          AND wname NOT LIKE 'Warehouse %'
    """)[0][0]
    if int(bad_meta) == 0:
        F.ok_('metadata_missing warehouses all fall back to "Warehouse <id>" name (spec)')
    else:
        F.bad_(f'{bad_meta} metadata_missing warehouses carry a non-sentinel name')

    # Cross-check three-state badge: (metadata_missing, warehouse_deleted_at)
    three_state = sql(w, f"""
        WITH wh AS (
          SELECT warehouse_id,
                 BOOL_OR(metadata_missing) AS mm,
                 MAX(warehouse_deleted_at) AS del
          FROM {ROLLUP_TABLE}
          WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
          GROUP BY warehouse_id
        )
        SELECT
          SUM(CASE WHEN NOT mm AND del IS NULL THEN 1 ELSE 0 END) AS active,
          SUM(CASE WHEN NOT mm AND del IS NOT NULL THEN 1 ELSE 0 END) AS deleted,
          SUM(CASE WHEN mm AND del IS NULL THEN 1 ELSE 0 END) AS missing,
          SUM(CASE WHEN mm AND del IS NOT NULL THEN 1 ELSE 0 END) AS impossible
        FROM wh
    """)[0]
    active_n, deleted_n, missing_n, impossible_n = [int(x) for x in three_state]
    print(f'  three-state badge: active={active_n}  deleted={deleted_n}  missing={missing_n}  impossible={impossible_n}')
    if impossible_n == 0:
        F.ok_('no warehouse has both metadata_missing=true AND warehouse_deleted_at set (spec)')
    else:
        F.bad_(f'{impossible_n} warehouses have both flags - three-state badge undefined')

    section('I. warehouse_type parity: staging (SKU) vs. rollup (system table preferred)')
    parity = sql(w, f"""
        WITH r AS (
          SELECT warehouse_id, MAX(warehouse_type) AS rollup_type,
                 BOOL_OR(metadata_missing) AS mm
          FROM {ROLLUP_TABLE}
          WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
          GROUP BY warehouse_id
        ),
        s AS (
          SELECT warehouse_id, MAX(warehouse_type) AS stg_type
          FROM {STAGING_TABLE}
          WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
          GROUP BY warehouse_id
        )
        SELECT
          COUNT(*) AS joined,
          SUM(CASE WHEN r.rollup_type IS NULL THEN 1 ELSE 0 END) AS null_rollup,
          SUM(CASE WHEN r.mm AND r.rollup_type <> s.stg_type THEN 1 ELSE 0 END) AS mm_but_diff,
          SUM(CASE WHEN NOT r.mm AND r.rollup_type <> s.stg_type THEN 1 ELSE 0 END) AS has_meta_and_diff
        FROM r JOIN s USING (warehouse_id)
    """)[0]
    joined_n, null_rollup, mm_but_diff, meta_and_diff = [int(x) for x in parity]
    print(f'  joined={joined_n}  null_rollup_type={null_rollup}  '
          f'mm+diff_from_staging={mm_but_diff}  has_meta+diff_from_staging={meta_and_diff}')
    if mm_but_diff == 0:
        F.ok_('metadata_missing rows all use staging (SKU) warehouse_type as fallback')
    else:
        F.bad_(f'{mm_but_diff} metadata_missing rows have rollup_type != staging_type')

    if null_rollup == 0:
        F.ok_('no warehouse has NULL warehouse_type in rollup (spec)')
    else:
        F.bad_(f'{null_rollup} warehouses have NULL warehouse_type in rollup')

    # This is not a defect - system table can legitimately override the SKU bucket.
    print(f'  note: {meta_and_diff} warehouses with metadata have system_type != sku_type '
          f'(expected: system table wins, e.g. REAL_TIME).')

    section('J. Details endpoint spot check')
    # Try an existing warehouse
    if grouped['data']:
        picked = grouped['data'][0]['warehouse_id']
        details = http_get(f'/api/warehouses/{picked}/details')
        row = grouped['data'][0]
        checks = [
            ('warehouse_id', details['warehouse_id'], row['warehouse_id']),
            ('warehouse_type', details.get('warehouse_type'), row.get('warehouse_type')),
            ('warehouse_size', details.get('warehouse_size'), row.get('warehouse_size')),
            ('auto_stop_mins', details.get('auto_stop_mins'), row.get('auto_stop_mins')),
            ('min_clusters', details.get('min_clusters'), row.get('min_clusters')),
            ('max_clusters', details.get('max_clusters'), row.get('max_clusters')),
            ('metadata_missing', details.get('metadata_missing'), row.get('metadata_missing')),
        ]
        for k, api_v, row_v in checks:
            if api_v == row_v:
                F.ok_(f'details[{k}]={api_v} matches grouped row')
            else:
                F.bad_(f'details[{k}]={api_v} vs. grouped row={row_v}')

        # tags shape
        tags = details.get('tags')
        print(f'  details.tags = {tags!r}')

    # Made-up ID should return metadata_missing sentinel, not 500
    try:
        made_up = http_get('/api/warehouses/nonexistent-warehouse-id/details')
        if made_up.get('metadata_missing') is True:
            F.ok_('nonexistent id returns metadata_missing=true (sentinel)')
        else:
            F.bad_(f'nonexistent id returned unexpected shape: {made_up}')
    except requests.HTTPError as e:
        F.bad_(f'nonexistent id raised HTTP error instead of sentinel: {e}')

    section('K. Pagination sanity')
    page1 = http_get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'page': 1, 'per_page': 5,
    })
    if page1['total_count'] == gt_total_wh:
        F.ok_(f'paginated total_count still matches ({gt_total_wh})')
    else:
        F.bad_(f'paginated total_count={page1["total_count"]}')

    if page1['total_pages'] == max(1, (gt_total_wh + 4) // 5) if gt_total_wh > 0 else True:
        F.ok_(f'total_pages consistent with total_count / per_page ({page1["total_pages"]})')
    else:
        F.bad_(f'total_pages={page1["total_pages"]} unexpected')

    # has_next / has_previous
    if (page1['has_next'] == (page1['total_pages'] > 1)
            and page1['has_previous'] is False):
        F.ok_('has_next/has_previous on page 1 correct')
    else:
        F.bad_(f'has_next={page1["has_next"]} has_previous={page1["has_previous"]}')

    section('L. Search filter')
    if grouped['data']:
        pick = grouped['data'][0]
        search_by_id = http_get('/api/warehouses/grouped', {
            'start_date': START_DATE.isoformat(),
            'end_date': END_DATE.isoformat(),
            'search': pick['warehouse_id'],
            'page': 1, 'per_page': 50,
        })
        if search_by_id['total_count'] == 1 and search_by_id['data'][0]['warehouse_id'] == pick['warehouse_id']:
            F.ok_('search by warehouse_id (exact) returns exactly that warehouse')
        else:
            F.bad_(f'search by id returned {search_by_id["total_count"]} rows: '
                   f'{[r["warehouse_id"] for r in search_by_id["data"]]}')

        if pick.get('warehouse_name'):
            # Search case-insensitive substring of first 3 chars
            sub = pick['warehouse_name'][:3].upper()
            search_by_name = http_get('/api/warehouses/grouped', {
                'start_date': START_DATE.isoformat(),
                'end_date': END_DATE.isoformat(),
                'search': sub,
                'page': 1, 'per_page': 50,
            })
            hit = any(r['warehouse_id'] == pick['warehouse_id'] for r in search_by_name['data'])
            if hit:
                F.ok_(f'search by name substring "{sub}" hits the picked warehouse')
            else:
                F.warn_(f'search by name "{sub}" did not hit picked warehouse')

    section('M. Bad-input handling')
    # inverted date range should 400
    try:
        r = requests.get(
            f'{APP_URL}/api/warehouses/summary',
            params={'start_date': END_DATE.isoformat(),
                    'end_date': START_DATE.isoformat()},
            headers={'Authorization': f'Bearer {get_oauth_token()}'},
            timeout=30,
        )
        if r.status_code == 400:
            F.ok_('inverted date range -> HTTP 400 (spec)')
        else:
            F.bad_(f'inverted date range returned {r.status_code}: {r.text[:200]}')
    except requests.RequestException as e:
        F.bad_(f'inverted date range request failed: {e}')

    section('N. Health endpoint (router mount above StaticFiles)')
    health = http_get('/api/warehouses/health')
    if health == {'status': 'healthy', 'service': 'sql-warehouses'}:
        F.ok_('/api/warehouses/health returns JSON (router mounted correctly)')
    else:
        F.bad_(f'/api/warehouses/health returned {health}')

    # ---- summary ----
    print(f'\n{"=" * 78}\n  AUDIT SUMMARY\n{"=" * 78}')
    print(f'  OK      : {len(F.ok)}')
    print(f'  WARN    : {len(F.warn)}')
    print(f'  FAIL    : {len(F.bad)}')
    if F.bad:
        print('\n  FAILURES:')
        for msg in F.bad:
            print(f'    - {msg}')
    if F.warn:
        print('\n  WARNINGS:')
        for msg in F.warn:
            print(f'    - {msg}')
    return 0 if not F.bad else 1


if __name__ == '__main__':
    sys.exit(main())

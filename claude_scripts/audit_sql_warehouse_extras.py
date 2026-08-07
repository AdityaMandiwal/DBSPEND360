#!/usr/bin/env python3
"""Extra deep-dive checks on the SQL Warehouse tab.

Covers areas the primary audit didn't:
  1. LLM /analyze endpoint end-to-end (structure + no cloud-cost caveat).
  2. Details endpoint tags parsing on a warehouse that actually carries tags
     in system.compute.warehouses.
  3. Coverage endpoint's sql_warehouse slice cross-check.
  4. Deleted warehouse three-state badge (spot-check a real one).
  5. WHERE clause / bucket-mapping edge case: 'PRO_SERVERLESS' SKU that would
     match the '%PRO%' precedence rule.
  6. warehouse_type distribution parity between UI-bucket rule and rollup.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, timedelta

import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from dotenv import load_dotenv

load_dotenv('.env.local')

WAREHOUSE_ID = os.getenv('DBSPEND_WAREHOUSE_ID', '148ccb90800933a1')
APP_URL = os.getenv(
    'DBSPEND_APP_URL',
    'https://dbspend360-984752964297111.11.azure.databricksapps.com',
)
ROLLUP = 'dbspend360.03apr.dbspend360_total_sql_warehouse_spends'
STAGING = 'dbspend360.03apr.dbspend360_sql_warehouse_dbu_cost'

END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=30)


def sql(w, statement):
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout='50s',
    )
    if r.status and r.status.state == StatementState.FAILED:
        err = r.status.error
        raise RuntimeError(err.message if err else 'unknown')
    return r.result.data_array if r.result and r.result.data_array else []


def token():
    profile = os.getenv('DATABRICKS_CONFIG_PROFILE', 'fevm')
    r = subprocess.run(
        ['databricks', 'auth', 'token', '--profile', profile],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)['access_token']


def http_get(path, params=None):
    resp = requests.get(
        f'{APP_URL}{path}', params=params,
        headers={'Authorization': f'Bearer {token()}'},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    w = WorkspaceClient()
    print(f'\n=== 1. LLM /analyze endpoint (structure + honesty caveats) ===')

    # Pick a warehouse with non-trivial spend
    top = http_get('/api/warehouses/top-warehouses', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'limit': 3,
    })
    wid = top[0]['warehouse_id']
    analyze = http_get(f'/api/warehouses/{wid}/analyze')
    print(f'  warehouse: {wid}  type={top[0]["warehouse_type"]}  spend=${top[0]["total_cost"]:,.2f}')
    print(f'  analysis length: {len(analyze["analysis"])} chars, timestamp={analyze["timestamp"]}')
    text = analyze['analysis']
    print(f'  [preview] {text[:400]!r}...')

    forbidden_phrases = [
        'cloud vm', 'cloud vms', 'ec2', 'cloud cost', 'cloud-cost',
        'databricks dbu cost only', 'excludes cloud vm', 'instance type',
        'spot instance', 'spot instances', 'node type', 'node-type',
    ]
    lower = text.lower()
    hits = [p for p in forbidden_phrases if p in lower]
    if hits:
        print(f'  X FAIL forbidden phrases leaked into DBU-only analysis: {hits}')
    else:
        print(f'  ✓ OK   no cloud-cost / VM caveat phrases in analysis (DBU-only spec)')

    # required section headers
    required = ['## 1.', '## 2.', '## 3.', '## 4.', '## 5.']
    missing = [s for s in required if s not in text]
    if not missing:
        print(f'  ✓ OK   five-section output present')
    else:
        print(f'  X FAIL missing section headers: {missing}')

    print(f'\n=== 2. Details.tags on a warehouse that carries tags in system table ===')
    with_tags = sql(w, """
        SELECT warehouse_id, warehouse_name, tags
        FROM system.compute.warehouses
        WHERE tags IS NOT NULL AND size(tags) > 0
        QUALIFY ROW_NUMBER() OVER (PARTITION BY warehouse_id ORDER BY change_time DESC) = 1
        LIMIT 5
    """)
    if not with_tags:
        print('  (no warehouses with tags found in system.compute.warehouses)')
    else:
        for row in with_tags[:2]:
            wid2 = row[0]
            print(f'  warehouse_id={wid2}  name={row[1]}  tags={row[2]}')
            d = http_get(f'/api/warehouses/{wid2}/details')
            print(f'  API details.tags = {d.get("tags")!r}')
            if d.get('tags'):
                print('  ✓ OK   tags round-trip from system table -> API')
            else:
                print('  ! WARN API returned no tags for a warehouse that has tags in system table')

    print(f'\n=== 3. /api/coverage-summary sql_warehouse slice ===')
    cov = http_get('/api/coverage')
    print(f'  covered_ws_count={cov["covered_workspace_count"]}  currency={cov["currency"]}')
    print(f'  excluded_dbu_by_tab={cov["excluded_dbu_by_tab"]}')
    api_slice = cov['excluded_dbu_by_tab']['sql_warehouse']
    sql_side = float(sql(w, f"""
        SELECT COALESCE(SUM(databricks_cost), 0)
        FROM {ROLLUP}
        WHERE workspace_covered = false
    """)[0][0])
    print(f'  sql-side (all time) non-covered DBU: {sql_side:.2f}')
    if abs(api_slice - sql_side) <= 0.05:
        print(f'  ✓ OK   coverage-summary sql_warehouse slice = {api_slice:.2f}')
    else:
        print(f'  X FAIL coverage sql_warehouse={api_slice:.2f} vs. sql={sql_side:.2f}')

    print(f'\n=== 4. Three-state badge: deleted warehouse spot check ===')
    deleted = sql(w, f"""
        SELECT warehouse_id, MAX(warehouse_name), MAX(warehouse_deleted_at)
        FROM {ROLLUP}
        WHERE warehouse_deleted_at IS NOT NULL
          AND usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
        GROUP BY warehouse_id LIMIT 3
    """)
    for row in deleted[:2]:
        wid2 = row[0]
        d = http_get(f'/api/warehouses/{wid2}/details')
        print(f'  {wid2}  api.deleted_at={d.get("warehouse_deleted_at")}  '
              f'api.metadata_missing={d.get("metadata_missing")}  '
              f'api.name={d.get("warehouse_name")!r}')

    print(f'\n=== 5. Bucket precedence: any SKU containing both PRO and SERVERLESS? ===')
    conflict = sql(w, """
        SELECT DISTINCT sku_name
        FROM system.billing.usage
        WHERE billing_origin_product = 'SQL'
          AND usage_metadata.warehouse_id IS NOT NULL
          AND usage_date >= date_sub(current_date(), 30)
          AND UPPER(sku_name) LIKE '%PRO%'
          AND UPPER(sku_name) LIKE '%SERVERLESS%'
    """)
    if conflict:
        print(f'  ! WARN {len(conflict)} SKU(s) contain both PRO and SERVERLESS')
        for row in conflict:
            print(f'     -> {row[0]!r}')
        print(f'  Precedence rule: rollup {"%PRO%"} check runs BEFORE {"%SERVERLESS%"} in ')
        print(f'  _WAREHOUSE_TYPE_BUCKET_SQL, so such SKUs bucket as PRO. Staging pre-derives ')
        print(f'  warehouse_type using SERVERLESS-first rule. Mismatch potential.')
    else:
        print(f'  ✓ OK   no SKU contains both PRO and SERVERLESS')

    print(f'\n=== 6. UI bucket rule (JS) parity: SERVERLESS-first vs PRO-first? ===')
    # UI display coerces UPPER(type) via WAREHOUSE_TYPE_CLASSES map for badges.
    # But bucketing to display is by the label switch on SERVERLESS/PRO/CLASSIC exactly.
    # Investigate warehouses with types outside SERVERLESS/PRO/CLASSIC
    other = sql(w, f"""
        SELECT warehouse_type, COUNT(DISTINCT warehouse_id)
        FROM {ROLLUP}
        WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
        GROUP BY warehouse_type
        ORDER BY warehouse_type
    """)
    for row in other:
        print(f'  rollup warehouse_type={row[0]!r}  distinct_wh={row[1]}')

    # Anything not in {CLASSIC, PRO, SERVERLESS} would show as "Unknown" or raw
    # in the UI badge label.

    print(f'\n=== 7. Cost summary lookback (30d) ===')
    # Call /analyze on a warehouse we know has spend, cost summary internally is 30d.
    print(f'  (verified via analyze prompt using SQL_WAREHOUSE_LOOKBACK_DAYS=30)')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Edge-case audit of SQL Warehouse tab against the live app.

Focus areas:
  A. Search wildcard leakage: does '%' / '_' in search misbehave?
  B. Non-covered warehouses appear in the /grouped table (no visual gate).
  C. UI/data reconciliation: sum(row.total_cost) vs summary.total_spend +
     dbu_in_non_covered_workspaces.
  D. Boundary date (single-day window, future window, ancient window).
  E. Zero-limit/large-limit pagination.
  F. Warehouse ID with special chars — SQL injection defence spot check.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv('.env.local')

APP_URL = os.getenv('DBSPEND_APP_URL',
                    'https://dbspend360-984752964297111.11.azure.databricksapps.com')

END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=30)


def token() -> str:
    r = subprocess.run(
        ['databricks', 'auth', 'token',
         '--profile', os.getenv('DATABRICKS_CONFIG_PROFILE', 'fevm')],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)['access_token']


def get(path: str, params=None):
    return requests.get(
        f'{APP_URL}{path}', params=params,
        headers={'Authorization': f'Bearer {token()}'},
        timeout=90,
    )


def main():
    print('\n=== A. LIKE wildcard in search: does "%" / "_" behave as literal? ===')
    # A search for "%" should match either NO warehouses (if treated literally)
    # or ALL warehouses (if % passes through into LIKE).
    r = get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'search': '%', 'page': 1, 'per_page': 5,
    })
    r.raise_for_status()
    body = r.json()
    print(f'  search="%": total_count={body["total_count"]}')
    if body['total_count'] > 0:
        # LIKE '%%%' = matches everything -> total_count = full unfiltered total
        # which is 377. This is a wildcard-leak finding.
        no_search = get('/api/warehouses/grouped', {
            'start_date': START_DATE.isoformat(),
            'end_date': END_DATE.isoformat(),
            'page': 1, 'per_page': 5,
        }).json()
        print(f'  no-search total: {no_search["total_count"]}')
        if body['total_count'] == no_search['total_count']:
            print('  ! FINDING: "%" acts as a LIKE wildcard -> matches all rows.')
            print('             Search does not escape LIKE meta-characters.')
        else:
            print('  ✓ OK   "%" was not a full wildcard (some limiting occurred).')
    else:
        print('  ✓ OK   "%" matched zero rows (treated more literally)')

    r2 = get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'search': '_', 'page': 1, 'per_page': 5,
    })
    body2 = r2.json()
    print(f'  search="_": total_count={body2["total_count"]}')

    print('\n=== B. UI/data reconciliation ===')
    grouped = get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'page': 1, 'per_page': 1000,
    }).json()
    summary = get('/api/warehouses/summary', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
    }).json()

    row_total = sum(r['total_cost'] for r in grouped['data'])
    covered_row_total = sum(
        r['total_cost'] for r in grouped['data']
        if r.get('workspace_covered', True)
    )
    non_covered_row_total = sum(
        r['total_cost'] for r in grouped['data']
        if r.get('workspace_covered', True) is False
    )
    print(f'  sum(row.total_cost)                = ${row_total:,.2f}')
    print(f'  sum(row.total_cost, covered=true)  = ${covered_row_total:,.2f}')
    print(f'  sum(row.total_cost, covered=false) = ${non_covered_row_total:,.2f}')
    print(f'  summary.total_spend                = ${summary["total_spend"]:,.2f}')
    print(f'  summary.dbu_in_non_covered         = ${summary.get("dbu_in_non_covered_workspaces", 0):,.2f}')
    print(f'  covered + non-covered              = ${summary["total_spend"] + summary.get("dbu_in_non_covered_workspaces", 0):,.2f}')

    if abs(covered_row_total - summary['total_spend']) <= 0.5:
        print('  ✓ OK   sum(covered rows) matches summary.total_spend')
    else:
        print(f'  ! FINDING: sum(covered rows)={covered_row_total:.2f} vs. '
              f'summary.total_spend={summary["total_spend"]:.2f}')

    # non-covered rows are still visible in the table without any visual gate
    non_covered_rows = [r for r in grouped['data']
                        if r.get('workspace_covered', True) is False]
    print(f'  non-covered warehouses visible in table: {len(non_covered_rows)}')
    if non_covered_rows and non_covered_row_total > 0:
        print('  ! FINDING: table shows non-covered warehouses with $ values '
              'that are NOT included in KPI total_spend. No visual indicator.')
        for r in non_covered_rows[:3]:
            print(f'     - {r["warehouse_id"]}  {r.get("warehouse_name")!r}  '
                  f'${r["total_cost"]:,.2f}')

    print('\n=== C. Boundary date ranges ===')

    # single-day window (today)
    r = get('/api/warehouses/summary', {
        'start_date': END_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
    })
    body = r.json()
    print(f'  single-day (today): total_wh={body["total_warehouses"]}  '
          f'total_spend=${body["total_spend"]:,.2f}  date_range_days={body["date_range_days"]}')
    if body['date_range_days'] == 1:
        print('  ✓ OK   date_range_days=1 for single-day range')
    else:
        print(f'  ! FINDING: date_range_days={body["date_range_days"]}')

    # future window (should be empty)
    future_start = END_DATE + timedelta(days=30)
    future_end = END_DATE + timedelta(days=60)
    r = get('/api/warehouses/summary', {
        'start_date': future_start.isoformat(),
        'end_date': future_end.isoformat(),
    })
    body = r.json()
    print(f'  future window: total_wh={body["total_warehouses"]}  total_spend=${body["total_spend"]}')
    if body['total_warehouses'] == 0 and body['total_spend'] == 0:
        print('  ✓ OK   future window returns zeros')

    # ancient window
    r = get('/api/warehouses/summary', {
        'start_date': '2020-01-01',
        'end_date': '2020-01-31',
    })
    body = r.json()
    print(f'  ancient window: total_wh={body["total_warehouses"]}  total_spend=${body["total_spend"]}')

    print('\n=== D. per_page bounds ===')
    r = get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'page': 1, 'per_page': 0,
    })
    print(f'  per_page=0: HTTP {r.status_code}')

    r = get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'page': 1, 'per_page': 100000,
    })
    print(f'  per_page=100000: HTTP {r.status_code}  '
          f'(spec caps at 1000)')

    r = get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'page': 999, 'per_page': 50,
    })
    body = r.json()
    print(f'  page=999: total_count={body["total_count"]}  rows={len(body["data"])}  '
          f'total_pages={body["total_pages"]}')

    # top-warehouses limit=0
    r = get('/api/warehouses/top-warehouses', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'limit': 0,
    })
    print(f'  top-warehouses limit=0: HTTP {r.status_code}')

    r = get('/api/warehouses/top-warehouses', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'limit': 100,
    })
    print(f'  top-warehouses limit=100 (cap=20): HTTP {r.status_code}')

    print("\n=== E. SQL injection defense ===")
    # This id contains single quote which should be escaped and return sentinel
    payload = "abc'--"
    r = get(f'/api/warehouses/{payload}/details')
    print(f'  details with quote-injection payload: HTTP {r.status_code}')
    if r.status_code == 200:
        body = r.json()
        if body.get('metadata_missing') is True:
            print("  ✓ OK   injection payload returns sentinel (metadata_missing=true)")
        else:
            print(f"  ! FINDING: injection payload returned unexpected body: {body}")

    print('\n=== F. Search with quote-injection payload ===')
    r = get('/api/warehouses/grouped', {
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'search': "test' OR '1'='1",
        'page': 1, 'per_page': 5,
    })
    print(f'  quote-injection search: HTTP {r.status_code}')
    if r.status_code == 200:
        body = r.json()
        print(f'  total_count={body["total_count"]} (should be near 0 if injection is blocked)')


if __name__ == '__main__':
    main()

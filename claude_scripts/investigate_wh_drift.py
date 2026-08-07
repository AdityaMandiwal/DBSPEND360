#!/usr/bin/env python3
"""Investigate the 378 vs 377 warehouse-count drift between
system.billing.usage and dbspend360_sql_warehouse_dbu_cost staging.
"""

import os
from datetime import date, timedelta

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from dotenv import load_dotenv

load_dotenv('.env.local')

WAREHOUSE_ID = os.getenv('DBSPEND_WAREHOUSE_ID', '148ccb90800933a1')
STAGING = 'dbspend360.03apr.dbspend360_sql_warehouse_dbu_cost'
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=30)


def sql(w, statement):
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout='50s',
    )
    if r.status and r.status.state == StatementState.FAILED:
        raise RuntimeError(r.status.error.message)
    return r.result.data_array if r.result and r.result.data_array else []


def main():
    w = WorkspaceClient()

    # Warehouses present in usage but missing from staging
    print('\n[1] Warehouses in system.billing.usage but NOT in staging:')
    missing = sql(w, f"""
        WITH src AS (
          SELECT DISTINCT usage_metadata.warehouse_id AS warehouse_id
          FROM system.billing.usage
          WHERE billing_origin_product = 'SQL'
            AND usage_metadata.warehouse_id IS NOT NULL
            AND usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
        ),
        stg AS (
          SELECT DISTINCT warehouse_id FROM {STAGING}
          WHERE usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
        )
        SELECT src.warehouse_id
        FROM src LEFT JOIN stg USING (warehouse_id)
        WHERE stg.warehouse_id IS NULL
    """)
    for row in missing:
        print(f'  MISSING: {row[0]}')

    # Detailed usage for those missing warehouses
    for row in missing:
        wid = row[0]
        print(f'\n[2] Usage detail for missing warehouse {wid}:')
        detail = sql(w, f"""
            SELECT
              sku_name,
              COUNT(*) AS n_rows,
              SUM(usage_quantity) AS dbu_qty,
              MIN(usage_date) AS min_date,
              MAX(usage_date) AS max_date,
              COUNT(DISTINCT workspace_id) AS n_workspaces
            FROM system.billing.usage
            WHERE billing_origin_product = 'SQL'
              AND usage_metadata.warehouse_id = '{wid}'
              AND usage_date >= '{START_DATE}' AND usage_date <= '{END_DATE}'
            GROUP BY sku_name
            ORDER BY dbu_qty DESC
        """)
        for d in detail:
            print(f'  sku={d[0]!r}  rows={d[1]}  dbu={d[2]}  min_d={d[3]}  max_d={d[4]}  ws={d[5]}')

        # Check if that SKU has a list-price row (inner-join precondition)
        for d in detail:
            sku = d[0]
            price = sql(w, f"""
                SELECT COUNT(*) AS price_rows,
                       MIN(price_start_time) AS min_start,
                       MAX(price_end_time) AS max_end
                FROM system.billing.list_prices
                WHERE sku_name = '{sku}'
            """)[0]
            print(f'  list_prices for {sku!r}: rows={price[0]}  start={price[1]}  end={price[2]}')


if __name__ == '__main__':
    main()

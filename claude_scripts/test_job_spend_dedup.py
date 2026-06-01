#!/usr/bin/env python3
"""Verification test for the SCD-dedup fix in databricks_service.

Reproduces the duplicate-rows bug for a known renamed job
(id 164677136540455 — "ProServ Benchmark Intelligence Pipeline" was renamed to
"ProServ Benchmark Intelligence Pipeline v2.0" on 2026-05-28) and asserts the
fixed grouped-job query returns exactly one row.

Also asserts that the new aggregated top-jobs query (used by /api/top-jobs)
returns one row per job_id with strictly distinct ids, and that its #1 entry
agrees with the #1 entry of the grouped-jobs query for the same window — the
two endpoints must not disagree about what "the top job" is.

Mirrors the SQL used in DatabricksService.get_grouped_job_spends() and
DatabricksService.get_top_jobs() so this can be run against any
workspace/warehouse without standing up the full FastAPI app.

Usage:
  uv run claude_scripts/test_job_spend_dedup.py
  uv run claude_scripts/test_job_spend_dedup.py --job-id 164677136540455
  uv run claude_scripts/test_job_spend_dedup.py --table dbspend360.03apr.dbspend360_total_job_spends
"""

import argparse
import os
import sys
from datetime import date, timedelta
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState


KNOWN_RENAMED_JOB_ID = '164677136540455'
DEFAULT_LOOKBACK_DAYS = 90


def _resolve_warehouse_id(client: WorkspaceClient, explicit: Optional[str]) -> str:
  if explicit:
    return explicit
  env_id = os.getenv('DATABRICKS_WAREHOUSE_ID') or os.getenv('WAREHOUSE_ID')
  if env_id:
    return env_id

  try:
    from server.config.config_loader import app_config  # type: ignore

    return app_config.warehouse_id
  except Exception:
    pass

  warehouses = list(client.warehouses.list())
  if not warehouses:
    raise RuntimeError(
      'No SQL warehouses available and no warehouse id provided '
      '(set --warehouse-id or DATABRICKS_WAREHOUSE_ID).'
    )
  return warehouses[0].id


def _resolve_table_name(explicit: Optional[str]) -> str:
  if explicit:
    return explicit
  env_table = os.getenv('DBSPEND_TABLE_NAME')
  if env_table:
    return env_table

  try:
    from server.config.config_loader import app_config  # type: ignore

    return app_config.table_name
  except Exception:
    return 'dbspend360.03apr.dbspend360_total_job_spends'


def _exec(client: WorkspaceClient, warehouse_id: str, sql: str):
  resp = client.statement_execution.execute_statement(
    warehouse_id=warehouse_id,
    statement=sql,
    wait_timeout='30s',
  )
  if not resp.status or resp.status.state != StatementState.SUCCEEDED:
    err = resp.status.error.message if (resp.status and resp.status.error) else 'unknown error'
    raise RuntimeError(
      f'Query failed ({resp.status.state if resp.status else "no status"}): {err}\nSQL:\n{sql}'
    )
  return resp


def _scd_row_count(client: WorkspaceClient, warehouse_id: str, job_id: str) -> tuple[int, int]:
  """Return (total_rows, distinct_names) for the job in system.lakeflow.jobs."""
  sql = f"""
    SELECT COUNT(*) AS total_rows,
           COUNT(DISTINCT name) AS distinct_names
    FROM system.lakeflow.jobs
    WHERE job_id = '{job_id}'
    """
  resp = _exec(client, warehouse_id, sql)
  if not resp.result or not resp.result.data_array:
    return 0, 0
  row = resp.result.data_array[0]
  return int(row[0]), int(row[1])


def _run_grouped_query(
  client: WorkspaceClient,
  warehouse_id: str,
  table_name: str,
  job_id: str,
  start_date: date,
  end_date: date,
  *,
  fixed: bool,
) -> list[list]:
  """Run the grouped-job query, in either the buggy or fixed shape."""
  if fixed:
    jobs_subquery = """
            SELECT job_id, MAX_BY(name, change_time) AS name
            FROM system.lakeflow.jobs
            GROUP BY job_id
        """
  else:
    jobs_subquery = """
            SELECT DISTINCT job_id, name
            FROM system.lakeflow.jobs
        """

  sql = f"""
    WITH filtered AS (
        SELECT *
        FROM {table_name}
        WHERE usage_date >= '{start_date.isoformat()}'
          AND usage_date <= '{end_date.isoformat()}'
          AND job_id = '{job_id}'
    ),
    run_level AS (
        SELECT job_id, run_id,
               SUM(cloud_cost) AS cloud_cost,
               SUM(databricks_cost) AS databricks_cost
        FROM filtered
        GROUP BY job_id, run_id
    ),
    job_level AS (
        SELECT job_id,
               SUM(cloud_cost) AS total_cloud_cost,
               SUM(databricks_cost) AS total_databricks_cost,
               COUNT(*) AS run_count
        FROM run_level
        GROUP BY job_id
    )
    SELECT j.job_id,
           j.total_cloud_cost,
           j.total_databricks_cost,
           j.run_count,
           lj.name
    FROM job_level j
    LEFT JOIN (
        {jobs_subquery}
    ) lj ON j.job_id = lj.job_id
    """
  resp = _exec(client, warehouse_id, sql)
  return resp.result.data_array if (resp.result and resp.result.data_array) else []


def _run_top_jobs_query(
  client: WorkspaceClient,
  warehouse_id: str,
  table_name: str,
  start_date: date,
  end_date: date,
  limit: int = 5,
) -> list[list]:
  """Mirror of DatabricksService.get_top_jobs() — one aggregated row per job_id."""
  sql = f"""
    WITH filtered AS (
        SELECT *
        FROM {table_name}
        WHERE usage_date >= '{start_date.isoformat()}'
          AND usage_date <= '{end_date.isoformat()}'
    ),
    run_level AS (
        SELECT job_id, run_id,
               SUM(cloud_cost) AS cloud_cost,
               SUM(databricks_cost) AS databricks_cost
        FROM filtered
        GROUP BY job_id, run_id
    ),
    job_level AS (
        SELECT job_id,
               SUM(cloud_cost) AS total_cloud_cost,
               SUM(databricks_cost) AS total_databricks_cost,
               COUNT(*) AS run_count
        FROM run_level
        GROUP BY job_id
    )
    SELECT j.job_id,
           j.total_cloud_cost,
           j.total_databricks_cost,
           j.run_count,
           lj.name,
           (j.total_cloud_cost + j.total_databricks_cost) AS total_cost
    FROM job_level j
    LEFT JOIN (
        SELECT job_id, MAX_BY(name, change_time) AS name
        FROM system.lakeflow.jobs
        GROUP BY job_id
    ) lj ON j.job_id = lj.job_id
    ORDER BY (j.total_cloud_cost + j.total_databricks_cost) DESC
    LIMIT {limit}
    """
  resp = _exec(client, warehouse_id, sql)
  return resp.result.data_array if (resp.result and resp.result.data_array) else []


def _run_grouped_query_unfiltered(
  client: WorkspaceClient,
  warehouse_id: str,
  table_name: str,
  start_date: date,
  end_date: date,
) -> list[list]:
  """Run the grouped-jobs query without a job_id filter, sorted by total cost.

  Used to assert /api/top-jobs and /api/grouped-job-spends agree on the #1
  job for the same window.
  """
  sql = f"""
    WITH filtered AS (
        SELECT *
        FROM {table_name}
        WHERE usage_date >= '{start_date.isoformat()}'
          AND usage_date <= '{end_date.isoformat()}'
    ),
    run_level AS (
        SELECT job_id, run_id,
               SUM(cloud_cost) AS cloud_cost,
               SUM(databricks_cost) AS databricks_cost
        FROM filtered
        GROUP BY job_id, run_id
    ),
    job_level AS (
        SELECT job_id,
               SUM(cloud_cost) AS total_cloud_cost,
               SUM(databricks_cost) AS total_databricks_cost,
               COUNT(*) AS run_count
        FROM run_level
        GROUP BY job_id
    )
    SELECT j.job_id,
           (j.total_cloud_cost + j.total_databricks_cost) AS total_cost,
           j.run_count
    FROM job_level j
    ORDER BY (j.total_cloud_cost + j.total_databricks_cost) DESC
    LIMIT 5
    """
  resp = _exec(client, warehouse_id, sql)
  return resp.result.data_array if (resp.result and resp.result.data_array) else []


def _assert_top_jobs_aggregation(
  client: WorkspaceClient,
  warehouse_id: str,
  table_name: str,
  start_date: date,
  end_date: date,
  limit: int = 5,
) -> None:
  """Assert /api/top-jobs returns distinct job_ids and matches grouped-jobs #1."""
  print('Running aggregated top-jobs query (mirrors /api/top-jobs) ...')
  rows = _run_top_jobs_query(client, warehouse_id, table_name, start_date, end_date, limit=limit)
  print(f'  rows returned: {len(rows)}')
  for row in rows:
    # row = [job_id, total_cloud_cost, total_databricks_cost, run_count, name, total_cost]
    print(
      f'    job_id={row[0]!s:>20}  total_cost={float(row[5]):>12.4f}  runs={row[3]}  name={row[4]}'
    )

  if not rows:
    print('WARNING: top-jobs query returned no rows. Cannot assert aggregation behaviour.')
    print('         Try widening --days, or run against a workspace with recent spend.')
    return

  job_ids = [row[0] for row in rows]
  distinct_ids = set(job_ids)
  assert len(distinct_ids) == len(job_ids), (
    f'FAIL: /api/top-jobs response has duplicate job_ids '
    f'({len(job_ids)} rows, {len(distinct_ids)} distinct). '
    f'Aggregation is not collapsing per-job_id correctly. Got: {job_ids}'
  )
  print(f'PASS: all {len(job_ids)} top-jobs rows have distinct job_ids.')

  totals = [float(row[5]) for row in rows]
  sorted_totals = sorted(totals, reverse=True)
  assert totals == sorted_totals, (
    f'FAIL: top-jobs rows are not sorted by total_cost DESC. Got: {totals}'
  )
  print('PASS: top-jobs rows are sorted by total_cost DESC.')

  print('Cross-checking #1 against grouped-jobs query ...')
  grouped_rows = _run_grouped_query_unfiltered(
    client, warehouse_id, table_name, start_date, end_date
  )
  if not grouped_rows:
    print('WARNING: grouped-jobs query returned no rows; cannot cross-check.')
    return

  top_job_id = rows[0][0]
  top_total = float(rows[0][5])
  grouped_top_job_id = grouped_rows[0][0]
  grouped_top_total = float(grouped_rows[0][1])
  assert top_job_id == grouped_top_job_id, (
    f'FAIL: top-jobs #1 job_id ({top_job_id}) != grouped-jobs #1 '
    f'job_id ({grouped_top_job_id}). The two endpoints disagree about '
    f'the top job for this window.'
  )
  assert abs(top_total - grouped_top_total) < 1e-6, (
    f'FAIL: top-jobs #1 total_cost ({top_total}) != grouped-jobs #1 '
    f'total_cost ({grouped_top_total}) for the same job ({top_job_id}).'
  )
  print(f'PASS: top-jobs #1 == grouped-jobs #1 (job_id={top_job_id}, total_cost={top_total:.4f}).')


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    '--job-id',
    default=KNOWN_RENAMED_JOB_ID,
    help=f'Job id to test (default: {KNOWN_RENAMED_JOB_ID})',
  )
  parser.add_argument(
    '--warehouse-id',
    default=None,
    help='SQL warehouse id (defaults to app config / env / first available)',
  )
  parser.add_argument(
    '--table', default=None, help='Fully-qualified spend table name (defaults to app config)'
  )
  parser.add_argument(
    '--days',
    type=int,
    default=DEFAULT_LOOKBACK_DAYS,
    help=f'Lookback window in days (default: {DEFAULT_LOOKBACK_DAYS})',
  )
  parser.add_argument(
    '--compare-buggy',
    action='store_true',
    help='Also run the old buggy query to show what the duplication used to look like',
  )
  args = parser.parse_args()

  end_date = date.today()
  start_date = end_date - timedelta(days=args.days)

  print('DBSPEND360 — job-spend dedup verification')
  print('=' * 60)
  print(f'Job id        : {args.job_id}')
  print(f'Date range    : {start_date} -> {end_date}')

  client = WorkspaceClient()
  warehouse_id = _resolve_warehouse_id(client, args.warehouse_id)
  table_name = _resolve_table_name(args.table)
  print(f'Warehouse id  : {warehouse_id}')
  print(f'Spend table   : {table_name}')
  print()

  total_rows, distinct_names = _scd_row_count(client, warehouse_id, args.job_id)
  print(f'system.lakeflow.jobs rows for this job: {total_rows} ({distinct_names} distinct names)')
  if total_rows == 0:
    print(
      '  WARNING: job not present in system.lakeflow.jobs — bug cannot be reproduced for this id.'
    )
  elif distinct_names < 2:
    print(
      '  NOTE: job has only one distinct name in SCD history — this id no longer exercises the bug.'
    )
  print()

  if args.compare_buggy:
    print('Running OLD (buggy) query — SELECT DISTINCT job_id, name ...')
    buggy_rows = _run_grouped_query(
      client, warehouse_id, table_name, args.job_id, start_date, end_date, fixed=False
    )
    print(f'  rows returned: {len(buggy_rows)}')
    for row in buggy_rows:
      print(f'    {row}')
    print()

  print('Running FIXED query — MAX_BY(name, change_time) GROUP BY job_id ...')
  rows = _run_grouped_query(
    client, warehouse_id, table_name, args.job_id, start_date, end_date, fixed=True
  )
  print(f'  rows returned: {len(rows)}')
  for row in rows:
    print(f'    {row}')
  print()

  if len(rows) == 0:
    print(
      'WARNING: no spend rows in the selected window for this job. Cannot assert dedup behaviour.'
    )
    print('         Try widening --days, or pass a --job-id with recent spend.')
    return 0

  assert len(rows) == 1, (
    f'FAIL: expected exactly 1 row for job {args.job_id} after dedup fix, got {len(rows)}'
  )
  print(f'PASS: exactly 1 row returned for job {args.job_id}.')

  if distinct_names >= 2:
    print(f'      (Job has {distinct_names} historical names in SCD — fix is exercised.)')
  print()

  print('-' * 60)
  print('Top-jobs aggregation verification')
  print('-' * 60)
  _assert_top_jobs_aggregation(client, warehouse_id, table_name, start_date, end_date, limit=5)
  return 0


if __name__ == '__main__':
  try:
    sys.exit(main())
  except AssertionError as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
  except KeyboardInterrupt:
    print('\nInterrupted.', file=sys.stderr)
    sys.exit(130)

#!/usr/bin/env python3
"""Slice 0 verification spike for the Shared Clusters + Instance Pools plan.

Runs the five read-only checks documented in
docs/plans/shared_clusters_and_pools/01-verification-spike.md against the
configured workspace, prints structured results, and emits a Markdown block
ready to paste into the "Verification results" section of that file.

What is covered locally:
  1. Cluster source breakdown in system.compute.clusters
  2. instance_pool_id population in system.billing.usage
  4. Whether the app SP can list instance pools via the SDK
  5a. Whether system.compute.clusters exposes worker_instance_pool_id /
      driver_instance_pool_id columns (the worker column is named
      `worker_instance_pool_id`, not `instance_pool_id` — confirmed during
      this spike)
  5b. Sample of clusters attached to a pool (column-presence sanity check)

What this script does NOT cover (cannot be done locally without cloud SP
credentials): check 3 against Azure Cost Management. A ready-to-paste notebook
snippet is produced at claude_scripts/verify_slice_0_azure_check.py — run that
inside the workspace and paste the result back into the same Markdown section.

Usage:
    uv run python claude_scripts/verify_slice_0.py

Reads DATABRICKS_HOST / DATABRICKS_TOKEN from .env.local (or the ambient
environment) and warehouse_id from config/app.<env>.config via
server.config.config_loader.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv(path: Path) -> None:
  """Minimal .env loader so this script works without python-dotenv installed."""
  if not path.exists():
    return
  for raw in path.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
      continue
    key, _, value = line.partition('=')
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    os.environ.setdefault(key, value)


_load_dotenv(REPO_ROOT / '.env.local')

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementState  # noqa: E402

from server.config.config_loader import app_config  # noqa: E402


@dataclass
class CheckResult:
  name: str
  passed: bool
  summary: str
  columns: Sequence[str] = field(default_factory=tuple)
  rows: Sequence[Sequence[Any]] = field(default_factory=tuple)
  note: str = ''


def _build_client() -> WorkspaceClient:
  host = os.getenv('DATABRICKS_HOST')
  token = os.getenv('DATABRICKS_TOKEN')
  if not host or not token:
    raise SystemExit(
      'DATABRICKS_HOST / DATABRICKS_TOKEN not set. Populate .env.local (see CLAUDE.md) and retry.'
    )
  return WorkspaceClient(host=host, token=token)


def _run_sql(
  client: WorkspaceClient, warehouse_id: str, sql: str, label: str
) -> tuple[Sequence[str], Sequence[Sequence[Any]], Optional[str]]:
  """Execute a single SQL statement and return (columns, rows, error)."""
  response = client.statement_execution.execute_statement(
    warehouse_id=warehouse_id,
    statement=sql,
    wait_timeout='50s',
  )
  state = response.status.state if response.status else None
  if state != StatementState.SUCCEEDED:
    err = (
      response.status.error.message
      if response.status and response.status.error
      else f'unexpected state: {state}'
    )
    return (), (), f'{label} failed: {err}'

  columns: Sequence[str] = ()
  if response.manifest and response.manifest.schema:
    columns = tuple(col.name for col in response.manifest.schema.columns)
  rows: Sequence[Sequence[Any]] = ()
  if response.result and response.result.data_array:
    rows = tuple(tuple(r) for r in response.result.data_array)
  return columns, rows, None


def check_1_cluster_sources(client: WorkspaceClient, warehouse_id: str) -> CheckResult:
  sql = textwrap.dedent(
    """
        SELECT cluster_source, COUNT(*) AS cluster_count
        FROM system.compute.clusters
        WHERE create_time >= current_date() - INTERVAL 30 DAYS
        GROUP BY cluster_source
        ORDER BY cluster_count DESC
        """
  ).strip()
  cols, rows, err = _run_sql(client, warehouse_id, sql, 'check_1')
  if err:
    return CheckResult('1. cluster source breakdown', False, err)
  sources = {row[0]: int(row[1]) for row in rows}
  interactive = sources.get('UI', 0) + sources.get('API', 0)
  passed = interactive > 0
  summary = (
    f'UI={sources.get("UI", 0)}, API={sources.get("API", 0)}, '
    f'JOB={sources.get("JOB", 0)}, interactive_total={interactive}'
  )
  return CheckResult(
    '1. cluster source breakdown',
    passed,
    summary,
    cols,
    rows,
    'Interactive clusters present in the last 30 days — Shared Clusters tab has data to render.'
    if passed
    else 'No UI/API clusters in last 30 days — Shared Clusters tab will be empty.',
  )


def check_2_pool_dbu(client: WorkspaceClient, warehouse_id: str) -> CheckResult:
  sql = textwrap.dedent(
    """
        SELECT usage_metadata.instance_pool_id AS instance_pool_id,
               SUM(usage_quantity) AS total_dbus
        FROM system.billing.usage
        WHERE usage_date >= current_date() - INTERVAL 30 DAYS
          AND usage_metadata.instance_pool_id IS NOT NULL
        GROUP BY 1
        ORDER BY total_dbus DESC
        LIMIT 20
        """
  ).strip()
  cols, rows, err = _run_sql(client, warehouse_id, sql, 'check_2')
  if err:
    return CheckResult('2. instance_pool_id in billing usage', False, err)
  passed = len(rows) > 0
  summary = f'distinct pools with non-null pool DBU rows in last 30d: {len(rows)}'
  note = (
    'Pool-attributed DBU present. Note: this is typically near zero '
    '(premium-edition pool surcharge only); the headline pool metric '
    'will be cloud idle cost, not DBU.'
    if passed
    else 'No pool DBU rows found — per the §4 decision gate, downgrade '
    'Instance Pools tab to DBU-only attribution would not apply; '
    'instead, the pool tab will rely entirely on the cloud-cost '
    'subtraction path (see slice 3).'
  )
  return CheckResult(
    '2. instance_pool_id in billing usage',
    passed,
    summary,
    cols,
    rows,
    note,
  )


def check_4_sdk_pool_listing(client: WorkspaceClient) -> CheckResult:
  try:
    pools = list(client.instance_pools.list())
  except Exception as exc:  # noqa: BLE001 — SDK can throw various REST errors
    return CheckResult(
      '4. SDK can list instance pools',
      False,
      f'instance_pools.list() raised: {type(exc).__name__}: {exc}',
      note=(
        'App SP cannot list pools. Backend pool catalog must fall '
        'back to listing pool_ids from system.compute.clusters and '
        "rendering 'pool name unknown'."
      ),
    )
  cols = ('instance_pool_id', 'instance_pool_name', 'node_type_id', 'state')
  rows = tuple(
    (
      p.instance_pool_id,
      p.instance_pool_name,
      p.node_type_id,
      str(p.state) if p.state else None,
    )
    for p in pools[:20]
  )
  summary = f'pools visible to app SP: {len(pools)}'
  return CheckResult(
    '4. SDK can list instance pools',
    True,
    summary,
    cols,
    rows,
    'SP can enumerate pools — backend catalog can use the SDK directly '
    '(see slice 3, list_instance_pools).',
  )


def check_5_clusters_pool_columns(client: WorkspaceClient, warehouse_id: str) -> CheckResult:
  describe_sql = 'DESCRIBE TABLE system.compute.clusters'
  cols, rows, err = _run_sql(client, warehouse_id, describe_sql, 'check_5a')
  if err:
    return CheckResult('5. pool columns on system.compute.clusters', False, err)

  column_names = {
    (row[0] or '').lower() for row in rows if row and not str(row[0] or '').startswith('#')
  }
  has_worker_pool = 'worker_instance_pool_id' in column_names
  has_driver_pool = 'driver_instance_pool_id' in column_names

  if not (has_worker_pool and has_driver_pool):
    return CheckResult(
      '5. pool columns on system.compute.clusters',
      False,
      f'worker_instance_pool_id present={has_worker_pool}, '
      f'driver_instance_pool_id present={has_driver_pool}',
      note=(
        'One or both pool columns absent. Per §4 decision gate, fall '
        'back to SDK-only pool catalog and hide the idle-vs-active '
        'subtraction (pool_total_cost only) on the Instance Pools tab.'
      ),
    )

  sample_sql = textwrap.dedent(
    """
        SELECT cluster_id, worker_instance_pool_id, driver_instance_pool_id
        FROM system.compute.clusters
        WHERE worker_instance_pool_id IS NOT NULL
           OR driver_instance_pool_id IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY cluster_id ORDER BY change_time DESC) = 1
        LIMIT 10
        """
  ).strip()
  s_cols, s_rows, s_err = _run_sql(client, warehouse_id, sample_sql, 'check_5b')
  if s_err:
    return CheckResult(
      '5. pool columns on system.compute.clusters',
      True,
      'columns present, sample query failed: ' + s_err,
      ('column',),
      tuple(('instance_pool_id',), ('driver_instance_pool_id',)),
      note='Columns exist on the table but sample query errored — '
      'investigate before slice 3 ETL work.',
    )

  return CheckResult(
    '5. pool columns on system.compute.clusters',
    True,
    f'both pool columns present; clusters attached to a pool (sampled): {len(s_rows)}',
    s_cols,
    s_rows,
    'Pool↔cluster attachment join in slice 3 is feasible.'
    if s_rows
    else 'Columns exist but no current clusters reference a pool. '
    'Pool tab will show pool_total_cost with active_cloud_cost=0 '
    'until clusters start using pools.',
  )


def _format_markdown_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
  if not columns:
    return '_no columns reported_'
  if not rows:
    return '_no rows returned_'
  header = '| ' + ' | '.join(columns) + ' |'
  sep = '| ' + ' | '.join('---' for _ in columns) + ' |'
  body = []
  for row in rows:
    body.append('| ' + ' | '.join('NULL' if v is None else str(v) for v in row) + ' |')
  return '\n'.join([header, sep, *body])


def _format_console(result: CheckResult) -> str:
  status = 'PASS' if result.passed else 'FAIL'
  head = f'[{status}] {result.name}\n        {result.summary}'
  if result.note:
    head += f'\n        note: {result.note}'
  if result.columns and result.rows:
    head += '\n        ' + ' | '.join(result.columns)
    head += '\n        ' + '-' * 60
    for row in result.rows[:10]:
      head += '\n        ' + ' | '.join('NULL' if v is None else str(v) for v in row)
    if len(result.rows) > 10:
      head += f'\n        ... ({len(result.rows) - 10} more rows)'
  return head


def _build_markdown_block(
  results: List[CheckResult],
  workspace_host: str,
  warehouse_id: str,
) -> str:
  timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
  sections = [
    '## Verification results',
    '',
    f'_Captured {timestamp} against `{workspace_host}` (warehouse `{warehouse_id}`)._',
    '',
  ]
  for r in results:
    status = 'PASS' if r.passed else 'FAIL'
    sections.append(f'### {r.name} — {status}')
    sections.append('')
    sections.append(f'- **Summary:** {r.summary}')
    if r.note:
      sections.append(f'- **Note:** {r.note}')
    sections.append('')
    sections.append(_format_markdown_table(r.columns, r.rows))
    sections.append('')
  sections.append('### 3. Azure CM `databricksinstancepoolid` tag presence')
  sections.append('')
  sections.append(
    'Run `claude_scripts/verify_slice_0_azure_check.py` inside a Databricks '
    'notebook in this workspace (it needs the same Azure SP identity used by '
    '`azure_cloud_cost_explorer_app.ipynb`) and paste the printed Markdown '
    'block here.'
  )
  sections.append('')
  return '\n'.join(sections)


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    '--markdown-out',
    type=Path,
    default=None,
    help="Write the Markdown 'Verification results' block to this file.",
  )
  args = parser.parse_args()

  client = _build_client()
  warehouse_id = app_config.warehouse_id

  print(f'Workspace: {os.getenv("DATABRICKS_HOST")}')
  print(f'Warehouse: {warehouse_id}')
  print(f'Cloud:     {app_config.cloud_platform.value}')
  print('-' * 72)

  results: List[CheckResult] = [
    check_1_cluster_sources(client, warehouse_id),
    check_2_pool_dbu(client, warehouse_id),
    check_4_sdk_pool_listing(client),
    check_5_clusters_pool_columns(client, warehouse_id),
  ]

  for r in results:
    print(_format_console(r))
    print()

  print('=' * 72)
  print('DECISION GATE')
  c1, c2, c4, c5 = results

  if not c2.passed:
    print(
      '  - check 2 returned no rows: Instance Pools tab cannot show '
      'DBU attribution. Cloud-cost subtraction path is still viable '
      'if check 3 (Azure CM) passes.'
    )
  if not c5.passed:
    print(
      '  - check 5 failed: instance_pool_id column missing on '
      'system.compute.clusters. Drop the idle-vs-active split in slice 3 '
      'and show pool_total_cost only.'
    )
  if not c4.passed:
    print(
      '  - check 4 failed: SP cannot list pools. Backend catalog must '
      'fall back to pool_ids from system.compute.clusters with '
      "'pool name unknown' labels."
    )
  if all(r.passed for r in results):
    print('  All locally-runnable checks PASS. Still required: check 3 (Azure CM).')
  print('=' * 72)

  markdown = _build_markdown_block(results, os.getenv('DATABRICKS_HOST', '<unknown>'), warehouse_id)
  if args.markdown_out:
    args.markdown_out.write_text(markdown)
    print(f'\nMarkdown block written to {args.markdown_out}')
  else:
    print('\n# --- Markdown block (copy into 01-verification-spike.md) ---\n')
    print(markdown)

  return 0 if all(r.passed for r in results) else 1


if __name__ == '__main__':
  sys.exit(main())

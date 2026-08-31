"""Regression coverage for SQL Warehouse audit fixes."""

import inspect
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.databricks_service import DatabricksService
from server.services.llm_service import LLMService

ROOT = Path(__file__).parents[1]


def _response(rows):
  return SimpleNamespace(result=SimpleNamespace(data_array=rows))


def _notebook_source(path: Path) -> str:
  notebook = json.loads(path.read_text())
  return '\n'.join(line for cell in notebook['cells'] for line in cell.get('source', []))


def test_sql_warehouse_price_join_and_workspace_fanout_abort_etl():
  """Ambiguous source rows must fail before costs or coverage are written."""
  source = _notebook_source(
    ROOT / 'jobs' / 'notebooks' / 'dbspend360_sql_warehouse_dbu_cost_app.ipynb'
  )

  price_guard = source[source.index('if join_cnt != left_cnt:') :]
  price_guard = price_guard[: price_guard.index('# warehouse_id is documented')]
  assert 'raise DataQualityError(' in price_guard
  assert 'refusing to ' in price_guard
  assert 'write incomplete or inflated SQL Warehouse cost' in price_guard

  fanout_guard = source[source.index('fanout_count = ws_fanout.count()') :]
  fanout_guard = fanout_guard[: fanout_guard.index('# All columns are already clean')]
  assert 'raise DataQualityError(message)' in fanout_guard
  assert 'risk incorrect coverage attribution' in fanout_guard


@pytest.mark.asyncio
async def test_sql_warehouse_summary_uses_day_coverage_and_freshness():
  """Coverage flips remain at day grain and source freshness is exposed."""
  statements = []
  service = object.__new__(DatabricksService)
  service.sql_warehouse_table_name = 'catalog.schema.total_sql_warehouse_spends'
  service._workspace_covered_sql = lambda _table: ('COALESCE(workspace_covered, true)')

  def execute(statement):
    statements.append(statement)
    return _response(
      [
        [
          3,
          1,
          1,
          1,
          '120.0',
          '30.0',
          '40.0',
          '50.0',
          '120.0',
          '7.0',
          '0.0',
          '120.0',
          '0.0',
          4,
          '2026-08-24',
        ]
      ]
    )

  service._execute_statement = execute
  metrics = await service.get_sql_warehouse_summary_metrics(
    date(2026, 8, 20),
    date(2026, 8, 26),
  )

  assert metrics.total_spend == 120.0
  assert metrics.dbu_in_non_covered_workspaces == 7.0
  assert metrics.covered_databricks_cost == metrics.total_spend
  assert metrics.covered_cloud_cost == 0.0
  assert metrics.uncovered_cloud_cost == 0.0
  assert (
    metrics.total_spend + metrics.dbu_in_non_covered_workspaces
    == metrics.covered_databricks_cost + metrics.dbu_in_non_covered_workspaces
  )
  assert metrics.landed_days == 4
  assert metrics.data_through_date == date(2026, 8, 24)
  assert 'CASE WHEN covered THEN total_cost' in statements[0]
  assert 'MAX_BY(type_bucket, usage_date)' in statements[0]


@pytest.mark.asyncio
async def test_sql_warehouse_analysis_summary_uses_requested_window_and_cost_basis():
  """Modal analysis must match its selected date range and disclose DBU-only."""
  statements = []
  service = object.__new__(DatabricksService)
  service.sql_warehouse_table_name = 'catalog.schema.total_sql_warehouse_spends'

  def execute(statement):
    statements.append(statement)
    return _response([['91.0', '91.0', 3, '30.333', 'PRO', 'Warehouse 1']])

  service._execute_statement = execute
  summary = await service.get_sql_warehouse_cost_summary(
    'wh-1',
    start_date=date(2026, 8, 1),
    end_date=date(2026, 8, 7),
  )

  assert summary is not None
  assert summary['cost_basis'] == 'dbu_only'
  assert summary['lookback_days'] == 7
  assert summary['start_date'] == '2026-08-01'
  assert summary['end_date'] == '2026-08-07'
  assert "usage_date >= '2026-08-01'" in statements[0]
  assert "usage_date <= '2026-08-07'" in statements[0]


def test_sql_warehouse_prompt_preserves_type_specific_cost_scope():
  """LLM input and fallback must never call Classic/Pro DBU complete cost."""
  details = SimpleNamespace(
    warehouse_id='wh-1',
    warehouse_name='Warehouse 1',
    warehouse_type='PRO',
    warehouse_size='SMALL',
    creator_id='owner',
    auto_stop_mins=10,
    min_clusters=1,
    max_clusters=2,
    metadata_missing=False,
    warehouse_deleted_at=None,
    tags=None,
    cost_basis='dbu_only',
  )
  summary = {
    'total_cost': 91.0,
    'total_dbu_cost': 91.0,
    'active_days': 3,
    'avg_daily_cost': 30.333,
    'warehouse_type': 'PRO',
    'warehouse_name': 'Warehouse 1',
    'lookback_days': 7,
    'start_date': '2026-08-01',
    'end_date': '2026-08-07',
    'cost_basis': 'dbu_only',
  }

  message = LLMService.__new__(LLMService)._build_sql_warehouse_user_message(
    details,
    summary,
  )
  fallback = LLMService._build_sql_warehouse_fallback(details, summary)

  assert 'Classic/Pro tracked spend is DBU-only' in message
  assert 'customer-cloud infrastructure' in fallback
  assert 'DBU — complete cost' not in message + fallback


def test_create_all_tables_bootstraps_sql_warehouse_and_coverage_tables():
  """Fresh environments must receive every SQL Warehouse prerequisite."""
  source = _notebook_source(ROOT / 'jobs' / 'ddls' / 'create_all_tables.ipynb')

  assert '"dbspend360_covered_workspaces"' in source
  assert '"dbspend360_sql_warehouse_dbu_cost"' in source
  assert '"dbspend360_total_sql_warehouse_spends"' in source


def test_sql_warehouse_job_has_no_in_dag_ddl_tasks():
  """SQL Warehouse tables are created at setup, not on every job run."""
  yaml_text = (ROOT / 'jobs' / 'resource_templates' / 'DBSPEND360.yaml').read_text()
  assert 'create_sql_warehouse_dbu_cost_table' not in yaml_text
  assert 'create_total_sql_warehouse_spends_table' not in yaml_text
  assert 'create_covered_workspaces_table' not in yaml_text
  assert '- task_key: Dbspend360_sql_warehouse_dbu_costs' in yaml_text
  assert '- task_key: sql_warehouse_spends' in yaml_text


def test_grouped_sql_warehouse_supports_server_side_sorting():
  """UI sort controls must map to a safe server-side order expression."""
  source = inspect.getsource(DatabricksService.get_sql_warehouses_grouped)

  assert "'warehouse_name': 'LOWER(COALESCE(wl.warehouse_name, wl.warehouse_id))'" in source
  assert "order_direction = 'ASC' if sort_dir == 'asc' else 'DESC'" in source
  assert 'ORDER BY {order_column} {order_direction}, wl.warehouse_id ASC' in source

"""Regression coverage for Instance Pools audit fixes."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.databricks_service import DatabricksService

ROOT = Path(__file__).parents[1]


def _response(rows):
  return SimpleNamespace(result=SimpleNamespace(data_array=rows))


def _pool_service(responses):
  statements = []
  remaining = list(responses)

  def execute_statement(**kwargs):
    statements.append(kwargs['statement'])
    return _response(remaining.pop(0))

  service = object.__new__(DatabricksService)
  service.pool_table_name = 'catalog.schema.total_pool_spends'
  service.warehouse_id = 'warehouse'
  service.client = SimpleNamespace(
    statement_execution=SimpleNamespace(execute_statement=execute_statement)
  )
  service._workspace_covered_sql = lambda _table: ('COALESCE(workspace_covered, true)')
  return service, statements


@pytest.mark.asyncio
async def test_pool_summary_includes_all_dbu_and_exposes_freshness():
  """Summary must reconcile with rows and disclose stale source dates."""
  service, statements = _pool_service(
    [
      [
        [
          2,
          3,
          1,
          '125.0',
          '62.5',
          '100.0',
          '25.0',
          '25.0',
          '100.0',
          '10.0',
          '2026-08-18',
          '2026-08-18',
          '2026-08-07',
          12,
        ]
      ]
    ]
  )

  metrics = await service.get_instance_pool_summary_metrics(
    date(2026, 7, 28),
    date(2026, 8, 26),
  )

  assert metrics.total_spend == 125.0
  assert metrics.dbu_in_non_covered_workspaces == 10.0
  assert metrics.latest_data_date == date(2026, 8, 18)
  assert metrics.latest_cloud_date == date(2026, 8, 7)
  assert metrics.cloud_data_days == 12
  assert 'COALESCE(SUM(total_cost), 0)' in statements[0]
  assert 'CASE WHEN COALESCE(workspace_covered, true) THEN total_cost' not in statements[0]


@pytest.mark.asyncio
async def test_pool_daily_trend_uses_same_all_dbu_total_as_summary():
  """Trend and summary must apply the same all-known-DBU policy."""
  service, statements = _pool_service([[]])

  await service.get_instance_pool_daily_trend(
    date(2026, 8, 1),
    date(2026, 8, 2),
  )

  assert 'COALESCE(SUM(total_cost), 0)' in statements[0]
  assert 'CASE WHEN' not in statements[0]


@pytest.mark.asyncio
async def test_pool_analysis_excludes_overhead_from_cluster_counts():
  """The overhead sentinel must never inflate workload cluster counts."""
  service, statements = _pool_service([[['0', '0', '0', '0', '0', None, None, 0, None, None]]])

  summary = await service.get_pool_cost_summary(
    'pool-1',
    start_date=date(2026, 8, 1),
    end_date=date(2026, 8, 7),
  )

  assert summary is not None
  assert summary['distinct_cluster_count'] == 0
  assert summary['peak_concurrent_clusters'] == 0
  assert summary['lookback_days'] == 7
  assert statements[0].count("cluster_id <> '__pool_overhead__'") >= 2
  assert "usage_date >= '2026-08-01'" in statements[0]
  assert "usage_date <= '2026-08-07'" in statements[0]


@pytest.mark.asyncio
async def test_failed_pool_rest_lookup_is_not_cached():
  """Transient metadata failures must be retried on a later request."""

  class FailingPools:
    def get(self, **_kwargs):
      raise RuntimeError('transient')

  service = object.__new__(DatabricksService)
  service.pool_metadata_cache = {}
  service.client = SimpleNamespace(instance_pools=FailingPools())

  result = await service.get_pool_metadata('pool-1')

  assert result == ('Pool pool-1', None)
  assert service.pool_metadata_cache == {}


@pytest.mark.parametrize(
  'notebook_name',
  ['aws_cloud_cost_explorer_app.ipynb', 'azure_cloud_cost_explorer_app.ipynb'],
)
def test_pool_cloud_failure_propagates(notebook_name):
  """Cloud ingestion failures must prevent a false successful refresh."""
  notebook = json.loads((ROOT / 'jobs' / 'notebooks' / notebook_name).read_text())
  source = '\n'.join(line for cell in notebook['cells'] for line in cell.get('source', []))

  failure_block = source[source.index('Pool explorer run failed:') :]
  failure_block = failure_block[: failure_block.index('def _pool_dbu_present')]
  assert 'raise' in failure_block
  assert 'never re-raises' not in source.lower()


def test_pool_dbu_merge_refreshes_dimension_fields():
  """Matched DBU rows must refresh mutable dimensions such as SKU."""
  notebook = json.loads(
    (ROOT / 'jobs' / 'notebooks' / 'dbspend360_pool_dbu_cost_app.ipynb').read_text()
  )
  source = '\n'.join(line for cell in notebook['cells'] for line in cell.get('source', []))

  assert '"workspace_id": "s.workspace_id"' in source
  assert '"currency": "s.currency"' in source
  assert '"sku_name": "s.sku_name"' in source


def test_pool_ui_uses_inclusive_30_day_window_and_scoped_coverage():
  """The default window and coverage disclosure must match KPI scope."""
  dashboard = (ROOT / 'client' / 'src' / 'components' / 'InstancePoolsDashboard.tsx').read_text()

  assert 'subDays(new Date(), 29)' in dashboard
  assert '<CoverageBanner tab="pool" dateRange={dateRange} />' in dashboard
  assert 'ClusterId-free idle/warm' in dashboard
  assert 'idle + active' not in dashboard


def test_pool_llm_uses_correct_cloud_scope():
  """Analysis copy must describe ClusterId-free cloud attribution."""
  llm = (ROOT / 'server' / 'services' / 'llm_service.py').read_text()

  assert 'POOL_CLOUD_SCOPE_CAVEAT' in llm
  assert 'active pool-backed VM cost is attributed to the Job or All-Purpose tab' in llm
  assert 'idle-vs-active VM cost split is not available yet' not in llm

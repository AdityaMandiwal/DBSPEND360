"""Regression coverage for the All-Purpose Clusters audit fixes."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.databricks_service import DatabricksService


def _response(rows):
  return SimpleNamespace(result=SimpleNamespace(data_array=rows))


def _service_with_capture(responses):
  service = object.__new__(DatabricksService)
  service.all_purpose_table_name = 'catalog.schema.total_all_purpose'
  service.table_name = 'catalog.schema.total_jobs'
  service._workspace_covered_agg_sql = lambda _table: (
    'BOOL_AND(COALESCE(workspace_covered, true)) AS workspace_covered'
  )
  service._workspace_covered_sql = lambda _table: 'COALESCE(workspace_covered, true)'
  statements = []
  remaining = list(responses)

  def execute(statement, **_kwargs):
    statements.append(statement)
    return _response(remaining.pop(0))

  service._execute_statement = execute
  return service, statements


@pytest.mark.asyncio
async def test_summary_includes_known_dbu_from_uncovered_workspaces():
  service, statements = _service_with_capture(
    [
      [
        [
          2,
          2,
          '25.0',
          '12.5',
          '20.0',
          '5.0',
          '5.0',
          '20.0',
          None,
          None,
          None,
          None,
          '15.0',
        ]
      ]
    ]
  )

  metrics = await service.get_all_purpose_summary_metrics(
    date(2026, 8, 1),
    date(2026, 8, 1),
  )

  assert metrics.total_spend == 25.0
  assert metrics.dbu_in_non_covered_workspaces == 15.0
  assert 'SUM(COALESCE(cloud_cost, 0) + COALESCE(databricks_cost, 0))' in statements[0]
  assert 'CASE WHEN COALESCE(workspace_covered, true) THEN' not in statements[0]


@pytest.mark.asyncio
async def test_other_cost_breakdown_uses_all_purpose_rollup_scope():
  service, statements = _service_with_capture([[]])
  service.schema_name = 'catalog.schema'

  # get_other_cost_breakdown reads app_config.schema_name rather than the
  # instance field, so use the configured schema but assert the selected
  # rollup table independently.
  await service.get_other_cost_breakdown(
    date(2026, 8, 1),
    date(2026, 8, 2),
    cluster_id='cluster-1',
    cluster_kind='all_purpose',
  )

  assert 'FROM catalog.schema.total_all_purpose a' in statements[0]
  assert 'a.cluster_id = b.cluster_id' in statements[0]
  assert 'FROM catalog.schema.total_jobs j' not in statements[0]


@pytest.mark.asyncio
async def test_grouped_cluster_sort_is_allowlisted_and_window_drilldown_is_complete():
  service, statements = _service_with_capture(
    [
      [
        [
          'cluster-1',
          'owner@example.com',
          'SINGLE_USER',
          31,
          None,
          '10.0',
          None,
          None,
          None,
          None,
          'Cluster One',
          'true',
          1,
        ]
      ]
    ]
  )
  service._get_batch_cluster_days = AsyncMock(return_value={})

  result = await service.get_all_purpose_grouped_by_cluster(
    date(2026, 7, 27),
    date(2026, 8, 26),
    sort_by='active_days',
    sort_dir='asc',
  )

  assert result.total_count == 1
  assert 'ORDER BY c.active_days ASC, c.cluster_id' in statements[0]
  assert service._get_batch_cluster_days.await_args.kwargs['days_per_cluster'] == 31


@pytest.mark.asyncio
async def test_unknown_sort_field_falls_back_to_total_cost_expression():
  service, statements = _service_with_capture([[]])

  await service.get_all_purpose_grouped_by_user(
    date(2026, 8, 1),
    date(2026, 8, 2),
    sort_by='DROP TABLE',
    sort_dir='desc',
  )

  assert 'DROP TABLE' not in statements[0]
  assert (
    'ORDER BY (COALESCE(total_cloud_cost, 0) + '
    'COALESCE(total_databricks_cost, 0)) DESC'
  ) in statements[0]


@pytest.mark.asyncio
async def test_top_cluster_preserves_workspace_coverage():
  service, _statements = _service_with_capture(
    [
      [
        [
          'cluster-1',
          'owner@example.com',
          'USER_ISOLATION',
          3,
          None,
          '100.0',
          None,
          None,
          None,
          None,
          'Cluster One',
          'false',
        ]
      ]
    ]
  )

  rows = await service.get_all_purpose_top_clusters(
    date(2026, 8, 1),
    date(2026, 8, 3),
  )

  assert rows[0].workspace_covered is False
  assert rows[0].total_cost == 100.0


@pytest.mark.parametrize(
  'notebook_name',
  [
    'dbspend360_all_purpose_dbu_cost_app.ipynb',
    'all_purpose_spends_app.ipynb',
  ],
)
def test_owner_change_deletes_stale_key_in_recomputed_window(notebook_name):
  notebook_path = (
    Path(__file__).parents[1] / 'jobs' / 'notebooks' / notebook_name
  )
  notebook = json.loads(notebook_path.read_text())
  source = '\n'.join(
    line
    for cell in notebook['cells']
    for line in cell.get('source', [])
  )

  assert 't.cluster_id = s.cluster_id AND t.user_id = s.user_id' in source
  assert 'AND t.usage_date = s.usage_date' in source
  assert '"user_id": "s.user_id"' in source
  assert '.whenNotMatchedBySourceDelete' in source
  assert "t.usage_date >= '{start_dt}'" in source
  assert "t.usage_date <= '{end_dt}'" in source

  if notebook_name == 'dbspend360_all_purpose_dbu_cost_app.ipynb':
    assert 't.workspace_id IN ({ids})' in source

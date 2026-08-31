"""Regression coverage for Job Clusters audit fixes."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.models.job_spend import GroupedJob, JobRun
from server.routers.dashboard import get_date_presets
from server.services.databricks_service import DatabricksService


def _response(rows):
  return SimpleNamespace(result=SimpleNamespace(data_array=rows))


def _service_with_capture(rows):
  service = object.__new__(DatabricksService)
  service.table_name = 'catalog.schema.dbspend360_total_job_spends'
  service._workspace_covered_agg_sql = lambda _table: (
    'BOOL_AND(COALESCE(workspace_covered, true)) AS workspace_covered'
  )
  service._workspace_covered_sql = lambda _table: ('COALESCE(workspace_covered, true)')
  statements = []

  def execute(statement, **_kwargs):
    statements.append(statement)
    return _response(rows)

  service._execute_statement = execute
  return service, statements


def test_nullable_cloud_cost_keeps_dbu_in_total():
  """Unknown cloud cost must not erase known Databricks spend."""
  run = JobRun(
    run_id='run-1',
    cluster_id='cluster-1',
    cluster_ids=['cluster-1'],
    start_date=date(2026, 8, 1),
    end_date=date(2026, 8, 1),
    cloud_cost=None,
    databricks_cost=12.5,
  )
  job = GroupedJob(
    job_id='job-1',
    run_count=1,
    total_cloud_cost=None,
    total_databricks_cost=12.5,
    runs=[],
  )

  assert run.total_cost == 12.5
  assert run.cloud_percentage == 0.0
  assert job.total_cost == 12.5


@pytest.mark.asyncio
async def test_job_runs_collapse_multi_cluster_run():
  """One run spanning clusters must remain one API run."""
  service, statements = _service_with_capture(
    [
      [
        'run-1',
        'cluster-a,cluster-b',
        '2026-08-01',
        '2026-08-02',
        None,
        '7.50',
        None,
        None,
        None,
        None,
        'false',
      ]
    ]
  )

  runs = await service.get_job_runs(
    'job-1',
    date(2026, 8, 1),
    date(2026, 8, 31),
  )

  assert len(runs) == 1
  assert runs[0].cluster_ids == ['cluster-a', 'cluster-b']
  assert runs[0].cloud_cost is None
  assert runs[0].total_cost == 7.5
  assert 'GROUP BY run_id, cluster_id' not in statements[0]
  assert 'GROUP BY run_id' in statements[0]


@pytest.mark.asyncio
async def test_breakdown_uses_selected_window_and_all_clusters():
  """Drill-down SQL must retain the selected window and all clusters."""
  service, statements = _service_with_capture(
    [
      [
        'job-1',
        'run-1',
        'cluster-a,cluster-b',
        '2026-08-05',
        '2026-08-06',
        None,
        '4.25',
        None,
        None,
        None,
        None,
        '0.0',
        '4.25',
        '0.0',
        '0.0',
      ]
    ]
  )

  breakdown = await service.get_job_cost_breakdown(
    'job-1',
    'run-1',
    start_date=date(2026, 8, 5),
    end_date=date(2026, 8, 6),
  )

  assert breakdown is not None
  assert breakdown.cluster_ids == ['cluster-a', 'cluster-b']
  assert breakdown.total_cost == 4.25
  assert "usage_date >= '2026-08-05'" in statements[0]
  assert "usage_date <= '2026-08-06'" in statements[0]


@pytest.mark.asyncio
async def test_date_presets_are_inclusive_day_counts():
  """Preset labels must equal their inclusive calendar-day counts."""
  presets = await get_date_presets()

  assert (presets['last_7_days']['end_date'] - presets['last_7_days']['start_date']).days + 1 == 7
  assert (
    presets['last_30_days']['end_date'] - presets['last_30_days']['start_date']
  ).days + 1 == 30
  assert (
    presets['last_90_days']['end_date'] - presets['last_90_days']['start_date']
  ).days + 1 == 90


@pytest.mark.asyncio
async def test_summary_includes_dbu_from_noncovered_workspaces():
  """KPI SQL must include known DBU while reporting excluded cloud scope."""
  service, statements = _service_with_capture(
    [
      [
        1,
        '16.0',
        '16.0',
        '16.0',
        '16.0',
        '1.0',
        '15.0',
        None,
        None,
        None,
        None,
        '5.0',
        '0.8',
        '10.0',
        '0.2',
      ]
    ]
  )

  metrics = await service.get_summary_metrics(
    date(2026, 8, 1),
    date(2026, 8, 1),
  )

  assert metrics.total_spend == 16.0
  assert metrics.total_databricks_cost == 15.0
  assert metrics.dbu_in_non_covered_workspaces == 5.0
  assert metrics.covered_cloud_cost == 0.8
  assert metrics.covered_databricks_cost == 10.0
  assert metrics.uncovered_cloud_cost == 0.2
  assert (
    metrics.covered_cloud_cost
    + metrics.covered_databricks_cost
    + metrics.dbu_in_non_covered_workspaces
    + metrics.uncovered_cloud_cost
    == metrics.total_spend
  )
  assert 'SUM(COALESCE(cloud_cost, 0) + COALESCE(databricks_cost, 0))' in statements[0]


@pytest.mark.asyncio
async def test_job_breakdown_splits_mixed_workspace_coverage():
  service, statements = _service_with_capture(
    [
      [
        'job-1',
        'run-1',
        'cluster-a,cluster-b',
        '2026-08-01',
        '2026-08-02',
        '11.0',
        '50.0',
        '8.0',
        '2.0',
        '1.0',
        '0.0',
        '9.0',
        '20.0',
        '2.0',
        '30.0',
      ]
    ]
  )

  breakdown = await service.get_job_cost_breakdown(
    'job-1', 'run-1', date(2026, 8, 1), date(2026, 8, 2)
  )

  assert breakdown is not None
  assert breakdown.covered_cloud_cost == 9.0
  assert breakdown.covered_databricks_cost == 20.0
  assert breakdown.uncovered_cloud_cost == 2.0
  assert breakdown.dbu_in_non_covered_workspaces == 30.0
  assert (
    breakdown.covered_cloud_cost
    + breakdown.covered_databricks_cost
    + breakdown.uncovered_cloud_cost
    + breakdown.dbu_in_non_covered_workspaces
    == breakdown.total_cost
  )
  assert 'CASE WHEN COALESCE(workspace_covered, true)' in statements[0]


def test_job_rollup_join_is_currency_safe():
  """Job rollup must join cloud and DBU rows on their currency grain."""
  notebook_path = (
    Path(__file__).parents[1] / 'jobs' / 'notebooks' / 'databricks_job_spends_app.ipynb'
  )
  notebook = json.loads(notebook_path.read_text())
  source = '\n'.join(line for cell in notebook['cells'] for line in cell.get('source', []))

  assert 'dbu_df["currency"] == cloud_df["currency"]' in source
  assert 'Job spend rollup contains duplicate natural keys' in source

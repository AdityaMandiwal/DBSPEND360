"""Regression coverage for Pipeline Compute ETL, API, and job wiring."""

import inspect
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.databricks_service import DatabricksService
from server.services.llm_service import LLMService

ROOT = Path(__file__).parents[1]
SERVICE_PATH = ROOT / 'server' / 'services' / 'databricks_service.py'


def _notebook_source(name: str) -> str:
  notebook = json.loads((ROOT / 'jobs' / 'notebooks' / name).read_text())
  return '\n'.join(
    line
    for cell in notebook['cells']
    for line in cell.get('source', [])
  )


def _method_source(name: str) -> str:
  return inspect.getsource(getattr(DatabricksService, name))


def _task_block(yaml_text: str, task_key: str) -> str:
  marker = f'        - task_key: {task_key}\n'
  start = yaml_text.index(marker)
  following = yaml_text[start + len(marker) :].splitlines(keepends=True)
  end = start + len(marker)
  for line in following:
    if line.startswith('        - task_key:'):
      break
    end += len(line)
  return yaml_text[start:] if end == -1 else yaml_text[start:end]


def test_pipeline_price_join_cardinality_mismatch_raises():
  """Both dropped and fanned-out price joins must abort before aggregation."""
  source = _notebook_source('dbspend360_pipeline_dbu_cost_app.ipynb')
  mismatch = source[source.index('if join_cnt != left_cnt:') :]
  mismatch = mismatch[: mismatch.index('# All columns are already clean')]

  assert 'direction = "DROP" if join_cnt < left_cnt else "FAN_OUT"' in mismatch
  assert 'self.logger.warning(' in mismatch
  assert mismatch.index('self.logger.warning(') < mismatch.index(
    'raise DataQualityError('
  )
  assert 'expected exactly one list-price row per usage row' in mismatch


def test_pipeline_compute_mode_uses_all_serverless_signals():
  """Non-null synthetic cluster IDs must not force managed compute to classic."""
  source = _notebook_source('dbspend360_pipeline_dbu_cost_app.ipynb')

  assert 'F.col("cluster_id").isNull()' in source
  assert 'F.upper(F.col("sku_name")).like("%SERVERLESS%")' in source
  assert (
    '["MODEL_SERVING", "VECTOR_SEARCH", "AI_FUNCTIONS"]'
    in source
  )
  assert (
    'F.max(F.col("is_serverless_row").cast("int"))'
    in source
  )


def test_pipeline_dab_has_explicit_ddl_dependencies_and_paths():
  """Pipeline ETL tasks must not race their target-table creation."""
  yaml_text = (ROOT / 'jobs' / 'resource_templates' / 'DBSPEND360.yaml').read_text()
  root = (
    '/Workspace/Users/aditya.mandiwal@databricks.com/'
    'deployed from cursor/jobs/ddls/'
  )

  create_dbu = _task_block(yaml_text, 'create_pipeline_dbu_cost_table')
  create_rollup = _task_block(yaml_text, 'create_total_pipeline_spends_table')
  dbu = _task_block(yaml_text, 'Dbspend360_pipeline_dbu_costs')
  rollup = _task_block(yaml_text, 'pipeline_spends')

  assert f'{root}dbspend360_pipeline_dbu_cost\n' in create_dbu
  assert f'{root}dbspend360_total_pipeline_spends\n' in create_rollup
  assert '.ipynb' not in create_dbu + create_rollup
  assert '- task_key: create_pipeline_dbu_cost_table' in dbu
  assert '- task_key: covered_workspaces' in dbu
  assert '- task_key: create_total_pipeline_spends_table' in rollup
  assert '- task_key: Dbspend360_pipeline_dbu_costs' in rollup
  assert '- task_key: cloud_cost_explorer' in rollup


def test_pipeline_summary_uses_all_workspace_totals_and_denominator():
  """Coverage is disclosure; it must not remove known spend from KPIs."""
  source = _method_source('get_pipeline_summary_metrics')
  summary_sql = source[source.index('query = f"""') : source.index('response =')]
  breakdown_sql = source[
    source.index('breakdown_query = f"""') : source.index(
      'breakdown_response ='
    )
  ]

  assert 'SUM(p.pipe_cost)' in summary_sql
  assert 'SUM(p.pipe_databricks_cost)' in summary_sql
  assert 'SUM(p.pipe_cloud_cost)' in summary_sql
  assert 'CASE WHEN p.workspace_covered THEN p.pipe_cost' not in summary_sql
  assert (
    'CASE WHEN p.workspace_covered THEN p.pipe_databricks_cost'
    not in summary_sql
  )
  assert 'SUM(total_cost) AS wl_cost' in breakdown_sql
  assert 'workspace_covered' not in breakdown_sql


def test_pipeline_mixed_bucket_owns_entire_mixed_pipeline_spend():
  """A mode-switching pipeline belongs wholly to the mixed dollar bucket."""
  source = _method_source('get_pipeline_summary_metrics')

  assert "COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'" in source
  assert (
    "SUM(CASE WHEN p.compute_mode='serverless' THEN p.pipe_cost ELSE 0 END)"
    in source
  )
  assert (
    "SUM(CASE WHEN p.compute_mode='classic' THEN p.pipe_cost ELSE 0 END)"
    in source
  )
  assert (
    "SUM(CASE WHEN p.compute_mode='mixed' THEN p.pipe_cost ELSE 0 END)"
    in source
  )


def test_pipeline_top_n_projects_workspace_coverage():
  """Top-N rows need the same coverage disclosure as grouped rows."""
  source = _method_source('get_top_pipelines')

  assert '_workspace_covered_agg_sql' in source
  assert '{wsc_agg}' in source
  assert 'pl.workspace_covered' in source
  assert 'workspace_covered=' in source


@pytest.mark.asyncio
async def test_pipeline_workload_filter_is_forwarded_to_day_breakdown():
  """A workload-filtered row and its nested day query must share scope."""
  rows = [
    [
      'ws-1',
      'pipeline-1',
      'Pipeline 1',
      'WORKSPACE',
      'owner@example.com',
      'runner@example.com',
      'mixed',
      'partial',
      False,
      None,
      1,
      '6.0',
      '4.0',
      '10.0',
      True,
      'DLT Pipeline',
      1,
    ]
  ]
  statements = []

  def execute(statement, **_kwargs):
    statements.append(statement)
    return SimpleNamespace(result=SimpleNamespace(data_array=rows))

  service = object.__new__(DatabricksService)
  service.pipeline_table_name = 'catalog.schema.total_pipeline_spends'
  service.warehouse_id = 'warehouse'
  service._execute_statement = execute
  service.client = SimpleNamespace(
    statement_execution=SimpleNamespace(
      execute_statement=lambda **kwargs: execute(kwargs['statement'])
    )
  )
  service._workspace_covered_agg_sql = lambda _table: (
    'BOOL_AND(COALESCE(workspace_covered, true)) AS workspace_covered'
  )
  captured = {}

  async def days(id_pairs, start_date, end_date, workload_type=None):
    captured.update(
      id_pairs=id_pairs,
      start_date=start_date,
      end_date=end_date,
      workload_type=workload_type,
    )
    return {('ws-1', 'pipeline-1'): []}

  service._get_batch_pipeline_days = days
  result = await service.get_pipelines_grouped(
    date(2026, 8, 1),
    date(2026, 8, 7),
    workload_type=['DLT Pipeline'],
  )

  assert result.data[0].total_cost == 10.0
  assert "workload_type IN ('DLT Pipeline')" in statements[0]
  assert captured['workload_type'] == ['DLT Pipeline']
  assert captured['start_date'] == date(2026, 8, 1)
  assert captured['end_date'] == date(2026, 8, 7)


def test_pipeline_llm_cost_copy_is_cloud_aware():
  """Pipeline analysis must describe the DBU-plus-cloud total it receives."""
  source = (
    inspect.getsource(LLMService._build_pipeline_user_message)
    + inspect.getsource(LLMService._build_pipeline_fallback)
  )

  assert "cost_summary.get('total_cloud_cost')" in source
  assert 'Cloud Cost' in source
  assert 'Cloud Coverage Complete' in source
  assert 'Total Spend (DBU)' not in source


def test_pipeline_methods_use_statement_wrapper():
  """Pipeline reads must inherit timeout and terminal-state handling."""
  service = SERVICE_PATH.read_text()
  start = service.index('  # Pipeline Compute')
  end = service.index('  async def get_sql_warehouse_summary_metrics', start)
  pipeline_region = service[start:end]

  assert 'self.client.statement_execution.execute_statement(' not in pipeline_region
  assert 'self._execute_statement(' in pipeline_region


def test_pipeline_ui_default_is_30_days_inclusive():
  """The default range includes today plus the preceding 29 calendar days."""
  dashboard = (
    ROOT / 'client' / 'src' / 'components' / 'PipelineDashboard.tsx'
  ).read_text()
  summary = (
    ROOT / 'client' / 'src' / 'components' / 'PipelineSummaryCards.tsx'
  ).read_text()

  assert 'subDays(new Date(), 29)' in dashboard
  assert 'subDays(new Date(), 30)' not in dashboard
  assert 'metrics.total_spend / Math.max(metrics.data_days, 1)' in summary


def test_pipeline_cost_caveat_uses_observed_cloud_completeness():
  """Classic/mixed totals are complete when a covered cloud value is present."""
  display = (
    ROOT / 'client' / 'src' / 'lib' / 'pipeline-display.ts'
  ).read_text()
  table = (
    ROOT / 'client' / 'src' / 'components' / 'PipelinesTable.tsx'
  ).read_text()

  assert 'if (workspaceCovered && cloudCost != null) return null;' in display
  assert 'pipeline.total_cloud_cost,' in table
  assert 'pipeline.workspace_covered,' in table


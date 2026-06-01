"""Extend `aws_cloud_cost_explorer_app.ipynb` with a parallel pool-tag query path.

Edits:
  * `AWSCostClient.get_cluster_costs_daily` — after building the DataFrame,
    route the tag-value column to either `cluster_id` (default) or
    `instance_pool_id` (when called with `tag_key='DatabricksInstancePoolId'`),
    and add the other column as NULL so both call shapes produce the same
    schema. Update the docstring to reflect the dual call signature.
  * `AWSCostReporterApp.run` — fetch costs twice (once per tag) and
    `unionByName` the results before classification + merge. Audit-log
    quality_msg now records that both passes ran.

Idempotent: each edit checks for a marker substring before applying.
"""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path('jobs/notebooks/aws_cloud_cost_explorer_app.ipynb')


def find_cell(nb, signature_prefix):
  for i, cell in enumerate(nb['cells']):
    src = ''.join(cell.get('source', []))
    if signature_prefix in src:
      return i, cell, src
  raise SystemExit(f'Cell with {signature_prefix!r} not found')


def edit_get_cluster_costs_daily(nb):
  idx, cell, src = find_cell(nb, 'def get_cluster_costs_daily(')
  if 'DatabricksInstancePoolId' in src and 'instance_pool_id' in src:
    print(f'[skip] cell {idx} get_cluster_costs_daily already dual-tag aware')
    return

  old = (
    '  def get_cluster_costs_daily(\n'
    '    self,\n'
    '    start_date: date,\n'
    '    end_date: date,\n'
    "    tag_key: str = 'ClusterId',\n"
    '    services: Optional[List[str]] = None,\n'
    "    metric: str = 'AmortizedCost',\n"
    '  ):\n'
    '    """Query CE for per-cluster daily costs with per-service detail.\n'
    '\n'
    '    Uses dual GroupBy (TAG + SERVICE dimension) to get cost segmentation\n'
    '    in a single API call. Returns per-service rows that the caller\n'
    '    aggregates into compute/storage/network categories.\n'
    '\n'
    '    Returns:\n'
    '        Spark DataFrame with columns: cluster_id, service_name, cost,\n'
    '        currency, cost_incurred_date — or None if no cost data found.\n'
    '    """\n'
    '    if services is None:\n'
    '      services = self.DEFAULT_SERVICES\n'
    '\n'
    '    chunks = self._build_chunks(start_date, end_date)\n'
    '    all_rows: List[Dict[str, Any]] = []\n'
    '\n'
    '    for i, (chunk_start, chunk_end) in enumerate(chunks):\n'
    "      logger.info(f'Querying CE chunk {i + 1}/{len(chunks)}: {chunk_start} → {chunk_end}')\n"
    '      rows = self._query_with_retries(chunk_start, chunk_end, tag_key, services, metric)\n'
    '      all_rows.extend(rows)\n'
    '      if len(chunks) > 1:\n'
    '        time.sleep(1)\n'
    '\n'
    '    if not all_rows:\n'
    '      return None\n'
    '\n'
    '    return self._rows_to_spark_df(all_rows)\n'
  )
  new = (
    '  def get_cluster_costs_daily(\n'
    '    self,\n'
    '    start_date: date,\n'
    '    end_date: date,\n'
    "    tag_key: str = 'ClusterId',\n"
    '    services: Optional[List[str]] = None,\n'
    "    metric: str = 'AmortizedCost',\n"
    '  ):\n'
    '    """Query CE for per-tag daily costs with per-service detail.\n'
    '\n'
    '    Uses dual GroupBy (TAG + SERVICE dimension) to get cost segmentation\n'
    '    in a single API call. Returns per-service rows that the caller\n'
    '    aggregates into compute/storage/network categories.\n'
    '\n'
    '    `tag_key` selects which Databricks resource tag to group on:\n'
    "      * 'ClusterId' (default) — per-cluster cost; output rows have\n"
    '        `cluster_id` populated and `instance_pool_id` NULL.\n'
    "      * 'DatabricksInstancePoolId' — per-pool cost; output rows have\n"
    '        `instance_pool_id` populated and `cluster_id` NULL.\n'
    '\n'
    '    Both shapes have identical columns so the two passes can be unioned\n'
    '    by the caller. CE allows only 2 GroupBy keys per request, so the\n'
    '    cluster and pool dimensions cannot be captured in a single call —\n'
    '    see `docs/plans/shared_clusters_and_pools/05-slice-3-instance-pools.md`.\n'
    '\n'
    '    Returns:\n'
    '        Spark DataFrame with columns:\n'
    '          cluster_id, instance_pool_id, service_name, cost, currency,\n'
    '          cost_incurred_date\n'
    '        — or None if no cost data found.\n'
    '    """\n'
    '    if services is None:\n'
    '      services = self.DEFAULT_SERVICES\n'
    '\n'
    '    chunks = self._build_chunks(start_date, end_date)\n'
    '    all_rows: List[Dict[str, Any]] = []\n'
    '\n'
    '    for i, (chunk_start, chunk_end) in enumerate(chunks):\n'
    '      logger.info(\n'
    "        f'Querying CE chunk {i + 1}/{len(chunks)} '\n"
    "        f'[tag={tag_key}]: {chunk_start} → {chunk_end}'\n"
    '      )\n'
    '      rows = self._query_with_retries(chunk_start, chunk_end, tag_key, services, metric)\n'
    '      all_rows.extend(rows)\n'
    '      if len(chunks) > 1:\n'
    '        time.sleep(1)\n'
    '\n'
    '    if not all_rows:\n'
    '      return None\n'
    '\n'
    '    spark_df = self._rows_to_spark_df(all_rows)\n'
    '    return self._route_tag_value_column(spark_df, tag_key)\n'
    '\n'
    '  def _route_tag_value_column(self, spark_df, tag_key: str):\n'
    '    """Rename the parsed tag-value column based on which tag was queried.\n'
    '\n'
    '    `_parse_response` always emits the tag value as `cluster_id`. This\n'
    '    method preserves that for the cluster-tag pass and renames to\n'
    '    `instance_pool_id` for the pool-tag pass, adding the other column\n'
    '    as NULL so both call shapes share an identical schema.\n'
    '    """\n'
    "    if tag_key == 'ClusterId':\n"
    "      return spark_df.withColumn('instance_pool_id', F.lit(None).cast('string'))\n"
    "    if tag_key == 'DatabricksInstancePoolId':\n"
    '      return (\n'
    "        spark_df.withColumnRenamed('cluster_id', 'instance_pool_id')\n"
    "        .withColumn('cluster_id', F.lit(None).cast('string'))\n"
    '      )\n'
    '    raise ValueError(\n'
    "      f'Unsupported tag_key {tag_key!r}; expected ClusterId or DatabricksInstancePoolId.'\n"
    '    )\n'
  )
  if old not in src:
    raise SystemExit(f'get_cluster_costs_daily: old block not found in cell {idx}')
  cell['source'] = (src.replace(old, new, 1)).splitlines(keepends=True)
  print(f'[ok]   cell {idx} get_cluster_costs_daily extended with dual-tag support')


def edit_run_method(nb):
  idx, cell, src = find_cell(nb, 'class AWSCostReporterApp:')
  if 'DatabricksInstancePoolId' in src:
    print(f'[skip] cell {idx} AWSCostReporterApp.run already dual-tag aware')
    return

  old = (
    '      ensure_cost_columns(self.target_table, logger=self.logger)\n'
    '\n'
    '      spark_df = self.client.get_cluster_costs_daily(\n'
    '        start_date=start_dt,\n'
    '        end_date=end_dt,\n'
    '      )\n'
    '\n'
    "      quality_msg = f'overlap_days={self.overlap_days}'\n"
  )
  new = (
    '      ensure_cost_columns(self.target_table, logger=self.logger)\n'
    '\n'
    '      # Two parallel CE queries — the cluster-tag pass populates cluster_id\n'
    '      # rows; the pool-tag pass populates instance_pool_id rows. CE caps\n'
    '      # GroupBy at 2 keys (TAG + SERVICE), so both dimensions cannot be\n'
    '      # collected in a single call. Doubles per-run CE quota use; existing\n'
    '      # LimitExceededException backoff handles throttling.\n'
    '      cluster_df = self.client.get_cluster_costs_daily(\n'
    '        start_date=start_dt,\n'
    '        end_date=end_dt,\n'
    "        tag_key='ClusterId',\n"
    '      )\n'
    '      pool_df = self.client.get_cluster_costs_daily(\n'
    '        start_date=start_dt,\n'
    '        end_date=end_dt,\n'
    "        tag_key='DatabricksInstancePoolId',\n"
    '      )\n'
    '\n'
    '      if cluster_df is None and pool_df is None:\n'
    '        spark_df = None\n'
    '      elif pool_df is None:\n'
    '        spark_df = cluster_df\n'
    '      elif cluster_df is None:\n'
    '        spark_df = pool_df\n'
    '      else:\n'
    '        spark_df = cluster_df.unionByName(pool_df)\n'
    '\n'
    '      quality_msg = (\n'
    "        f'overlap_days={self.overlap_days}, tag_passes=[ClusterId,DatabricksInstancePoolId]'\n"
    '      )\n'
  )
  if old not in src:
    raise SystemExit(f'AWSCostReporterApp.run: old block not found in cell {idx}')
  cell['source'] = (src.replace(old, new, 1)).splitlines(keepends=True)
  print(f'[ok]   cell {idx} AWSCostReporterApp.run extended with dual-tag pass')


def main():
  with NOTEBOOK.open() as f:
    nb = json.load(f)

  edit_get_cluster_costs_daily(nb)
  edit_run_method(nb)

  with NOTEBOOK.open('w') as f:
    json.dump(nb, f, indent=1)
    f.write('\n')

  print('Wrote', NOTEBOOK)


if __name__ == '__main__':
  main()

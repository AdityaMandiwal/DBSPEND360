"""Extend `azure_cloud_cost_explorer_app.ipynb` with a parallel pool-tag query path.

Edits:
  * Add `_AZURE_POOL_TAG_VALUE_CANDIDATES` and generalize the resolver to
    `_resolve_tag_value_column(df, target_col, candidates, logger)`. Keep
    `_resolve_cluster_id_column` as a thin wrapper for backward compat.
  * Refactor `AzureCostReporterApp.run` to fetch one CM query per tag,
    rename the tag-value column to the appropriate target, add the other
    column as NULL, `unionByName` the two DataFrames, and continue with
    classification + merge. The MeterCategory-missing fallback also picks
    up `instance_pool_id`. Audit-log quality_msg records both passes ran.

Idempotent: each edit checks for a marker substring before applying.
"""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path('jobs/notebooks/azure_cloud_cost_explorer_app.ipynb')


def find_cell(nb, signature_prefix):
  for i, cell in enumerate(nb['cells']):
    src = ''.join(cell.get('source', []))
    if signature_prefix in src:
      return i, cell, src
  raise SystemExit(f'Cell with {signature_prefix!r} not found')


def edit_tag_resolver(nb):
  idx, cell, src = find_cell(nb, '_AZURE_TAG_VALUE_CANDIDATES =')
  if '_AZURE_POOL_TAG_VALUE_CANDIDATES' in src:
    print(f'[skip] cell {idx} pool tag candidates already added')
    return

  old = (
    '# Known column names the Azure Cost API may use for the tag-value field\n'
    '_AZURE_TAG_VALUE_CANDIDATES = {"clusterid", "clusteridvalue", "tagvalue"}\n'
    '\n'
    '\n'
    'def _resolve_cluster_id_column(spark_df, date_col, logger):\n'
    '    """Rename the Azure tag-value column to ``cluster_id`` if needed.\n'
    '\n'
    '    Uses only the known candidate column names from _AZURE_TAG_VALUE_CANDIDATES.\n'
    '    Raises SchemaValidationError if no candidate matches.\n'
    '    """\n'
    '    if "cluster_id" in spark_df.columns:\n'
    '        return spark_df\n'
    '\n'
    '    tag_value_col = next(\n'
    '        (c for c in spark_df.columns if c.lower() in _AZURE_TAG_VALUE_CANDIDATES),\n'
    '        None,\n'
    '    )\n'
    '\n'
    '    if tag_value_col is None:\n'
    '        raise SchemaValidationError(\n'
    '            f"Cannot resolve cluster_id column from API response. "\n'
    '            f"Columns present: {spark_df.columns}. "\n'
    '            f"Expected one of: {sorted(_AZURE_TAG_VALUE_CANDIDATES)}"\n'
    '        )\n'
    '\n'
    '    logger.info(f"Resolved cluster_id column from \'{tag_value_col}\'")\n'
    '    return spark_df.withColumnRenamed(tag_value_col, "cluster_id")\n'
  )
  new = (
    '# Known column names the Azure Cost API may use for the tag-value field\n'
    '_AZURE_TAG_VALUE_CANDIDATES = {"clusterid", "clusteridvalue", "tagvalue"}\n'
    '# Pool-tag flavour. "tagvalue" is shared with the cluster set because\n'
    '# Azure may use a generic column name regardless of the queried tag.\n'
    '_AZURE_POOL_TAG_VALUE_CANDIDATES = {"databricksinstancepoolid", "tagvalue"}\n'
    '\n'
    '\n'
    'def _resolve_tag_value_column(spark_df, target_col, candidates, logger):\n'
    '    """Rename the Azure tag-value column to ``target_col`` if needed.\n'
    '\n'
    '    Generic version of _resolve_cluster_id_column. Looks for a column\n'
    '    whose lower-cased name is in ``candidates`` and renames it to\n'
    '    ``target_col``. Raises SchemaValidationError if no candidate matches.\n'
    '    """\n'
    '    if target_col in spark_df.columns:\n'
    '        return spark_df\n'
    '\n'
    '    tag_value_col = next(\n'
    '        (c for c in spark_df.columns if c.lower() in candidates),\n'
    '        None,\n'
    '    )\n'
    '\n'
    '    if tag_value_col is None:\n'
    '        raise SchemaValidationError(\n'
    '            f"Cannot resolve {target_col} column from API response. "\n'
    '            f"Columns present: {spark_df.columns}. "\n'
    '            f"Expected one of: {sorted(candidates)}"\n'
    '        )\n'
    '\n'
    '    logger.info(f"Resolved {target_col} column from \'{tag_value_col}\'")\n'
    '    return spark_df.withColumnRenamed(tag_value_col, target_col)\n'
    '\n'
    '\n'
    'def _resolve_cluster_id_column(spark_df, date_col, logger):\n'
    '    """Backward-compat wrapper for the cluster-tag pass.\n'
    '\n'
    '    Retained so existing callers continue to work; new dual-tag code\n'
    '    should call ``_resolve_tag_value_column`` directly with the desired\n'
    '    target column and candidate set.\n'
    '    """\n'
    '    return _resolve_tag_value_column(\n'
    '        spark_df, "cluster_id", _AZURE_TAG_VALUE_CANDIDATES, logger\n'
    '    )\n'
  )
  if old not in src:
    raise SystemExit(f'tag resolver: old block not found in cell {idx}')
  cell['source'] = (src.replace(old, new, 1)).splitlines(keepends=True)
  print(f'[ok]   cell {idx} tag resolver generalized')


def edit_run_method(nb):
  idx, cell, src = find_cell(nb, 'class AzureCostReporterApp:')
  # Scope the idempotency check to the run() body — the cells already
  # mention "databricksinstancepoolid" in _AZURE_POOL_TAG_VALUE_CANDIDATES
  # after `edit_tag_resolver` runs.
  run_start = src.find('    def run(self):\n')
  if run_start == -1:
    raise SystemExit('Could not locate run() to check idempotency')
  if 'cluster_df = self._fetch_one_tag_pass(' in src[run_start:]:
    print(f'[skip] cell {idx} AzureCostReporterApp.run already dual-tag aware')
    return

  old = (
    '            ensure_cost_columns(self.target_table, logger=self.logger)\n'
    '\n'
    '            spark_df = self.client.group_by_job_clusterid_daily(\n'
    '                start_date=datetime.combine(start_dt, datetime.min.time(), tzinfo=timezone.utc),\n'
    '                end_date=datetime.combine(end_dt, datetime.max.time(), tzinfo=timezone.utc),\n'
    '                tag_name="clusterid",\n'
    '            )\n'
    '\n'
    '            quality_msg = f"overlap_days={self.overlap_days}"\n'
    '\n'
    '            if spark_df is None or spark_df.limit(1).count() == 0:\n'
    '                self.logger.info("No Azure cost data returned by API for the requested range.")\n'
    '                merged_row_count = 0\n'
    '            else:\n'
    '                date_col = (\n'
    '                    "usagedate"\n'
    '                    if "usagedate" in [c.lower() for c in spark_df.columns]\n'
    '                    else "date_key"\n'
    '                )\n'
    '                spark_df = spark_df.withColumn(\n'
    '                    "cost_incurred_date",\n'
    '                    F.to_date(F.col(date_col).cast("string"), "yyyyMMdd"),\n'
    '                )\n'
    '\n'
    '                spark_df = _resolve_cluster_id_column(spark_df, date_col, self.logger)\n'
    '\n'
    '                inc_df = filter_valid_cost_rows(spark_df)\n'
  )
  new = (
    '            ensure_cost_columns(self.target_table, logger=self.logger)\n'
    '\n'
    '            # Two parallel CM queries — the cluster-tag pass populates cluster_id\n'
    '            # rows; the pool-tag pass populates instance_pool_id rows. Azure CM\n'
    '            # only allows 2 GroupBy keys (TagKey + MeterCategory), so the two\n'
    '            # dimensions cannot be captured in a single query. Doubles per-run\n'
    '            # CM quota use; the existing 429 retry/backoff handles throttling.\n'
    '            start_utc = datetime.combine(start_dt, datetime.min.time(), tzinfo=timezone.utc)\n'
    '            end_utc = datetime.combine(end_dt, datetime.max.time(), tzinfo=timezone.utc)\n'
    '\n'
    '            cluster_df = self._fetch_one_tag_pass(\n'
    '                start_utc, end_utc, "clusterid", "cluster_id", _AZURE_TAG_VALUE_CANDIDATES,\n'
    '            )\n'
    '            pool_df = self._fetch_one_tag_pass(\n'
    '                start_utc, end_utc, "databricksinstancepoolid",\n'
    '                "instance_pool_id", _AZURE_POOL_TAG_VALUE_CANDIDATES,\n'
    '            )\n'
    '\n'
    '            if cluster_df is None and pool_df is None:\n'
    '                spark_df = None\n'
    '            elif pool_df is None:\n'
    '                spark_df = cluster_df\n'
    '            elif cluster_df is None:\n'
    '                spark_df = pool_df\n'
    '            else:\n'
    '                spark_df = cluster_df.unionByName(pool_df, allowMissingColumns=True)\n'
    '\n'
    '            quality_msg = (\n'
    '                f"overlap_days={self.overlap_days}, "\n'
    '                f"tag_passes=[clusterid,databricksinstancepoolid]"\n'
    '            )\n'
    '\n'
    '            if spark_df is None or spark_df.limit(1).count() == 0:\n'
    '                self.logger.info("No Azure cost data returned by API for the requested range.")\n'
    '                merged_row_count = 0\n'
    '            else:\n'
    '                inc_df = filter_valid_cost_rows(spark_df)\n'
  )
  if old not in src:
    raise SystemExit(f'AzureCostReporterApp.run: old block not found in cell {idx}')
  new_src = src.replace(old, new, 1)
  cell['source'] = new_src.splitlines(keepends=True)
  print(f'[ok]   cell {idx} AzureCostReporterApp.run extended with dual-tag pass')


def edit_meter_missing_fallback(nb):
  """The has_meter-False branch did `groupBy(cluster_id, ...)` only. Pool rows
  (cluster_id NULL) would collapse into one bucket. Include instance_pool_id
  in the groupBy when present so pool rows aggregate per pool.
  """
  idx, cell, src = find_cell(nb, 'class AzureCostReporterApp:')
  old = (
    '                        agg_df = (\n'
    '                            inc_df\n'
    '                            .groupBy("cluster_id", "currency", "cost_incurred_date")\n'
    '                            .agg(F.sum("cost").alias("cloud_cost"))\n'
    '                            .withColumn("compute_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("storage_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("network_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("other_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("created_at", F.current_timestamp())\n'
    '                            .withColumn("updated_at", F.current_timestamp())\n'
    '                        )\n'
  )
  new = (
    '                        # MeterCategory missing: skip cost classification but\n'
    '                        # still carry instance_pool_id through the groupBy when\n'
    '                        # the column is present, so pool rows aggregate per pool.\n'
    '                        meter_missing_group_cols = ["cluster_id", "currency", "cost_incurred_date"]\n'
    '                        if "instance_pool_id" in inc_df.columns:\n'
    '                            meter_missing_group_cols.insert(1, "instance_pool_id")\n'
    '                        agg_df = (\n'
    '                            inc_df\n'
    '                            .groupBy(*meter_missing_group_cols)\n'
    '                            .agg(F.sum("cost").alias("cloud_cost"))\n'
    '                            .withColumn("compute_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("storage_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("network_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("other_cost", F.lit(None).cast("double"))\n'
    '                            .withColumn("created_at", F.current_timestamp())\n'
    '                            .withColumn("updated_at", F.current_timestamp())\n'
    '                        )\n'
  )
  if 'meter_missing_group_cols' in src:
    print(f'[skip] cell {idx} meter-missing fallback already updated')
    return
  if old not in src:
    raise SystemExit('meter-missing fallback: old block not found')
  cell['source'] = src.replace(old, new, 1).splitlines(keepends=True)
  print(f'[ok]   cell {idx} meter-missing fallback updated to carry instance_pool_id')


def add_fetch_one_tag_pass(nb):
  """Insert the `_fetch_one_tag_pass` helper as a new method on the App class.

  Goes right after `__init__` and right before `def run(self):` for readability.
  """
  idx, cell, src = find_cell(nb, 'class AzureCostReporterApp:')
  if '_fetch_one_tag_pass' in src:
    print(f'[skip] cell {idx} _fetch_one_tag_pass already present')
    return

  marker = '    def run(self):\n'
  helper = (
    '    def _fetch_one_tag_pass(self, start_utc, end_utc, tag_name, target_col, candidates):\n'
    '        """Run one CM query for a single tag dimension and normalize its schema.\n'
    '\n'
    '        Calls ``group_by_job_clusterid_daily`` for ``tag_name``, converts the\n'
    '        date column, renames the tag-value column to ``target_col`` using\n'
    '        ``candidates`` for case-insensitive matching, and adds the\n'
    '        complementary tag column as NULL so the cluster and pool passes\n'
    '        share an identical schema and can be unioned by the caller.\n'
    '\n'
    '        Returns None if the API call yields no rows.\n'
    '        """\n'
    '        df = self.client.group_by_job_clusterid_daily(\n'
    '            start_date=start_utc,\n'
    '            end_date=end_utc,\n'
    '            tag_name=tag_name,\n'
    '        )\n'
    '        if df is None or df.limit(1).count() == 0:\n'
    '            self.logger.info(f"No Azure cost rows for tag_name={tag_name!r}.")\n'
    '            return None\n'
    '\n'
    '        date_col = (\n'
    '            "usagedate"\n'
    '            if "usagedate" in [c.lower() for c in df.columns]\n'
    '            else "date_key"\n'
    '        )\n'
    '        df = df.withColumn(\n'
    '            "cost_incurred_date",\n'
    '            F.to_date(F.col(date_col).cast("string"), "yyyyMMdd"),\n'
    '        )\n'
    '\n'
    '        df = _resolve_tag_value_column(df, target_col, candidates, self.logger)\n'
    '\n'
    '        other_col = "instance_pool_id" if target_col == "cluster_id" else "cluster_id"\n'
    '        if other_col not in df.columns:\n'
    '            df = df.withColumn(other_col, F.lit(None).cast("string"))\n'
    '\n'
    '        return df\n'
    '\n'
  )
  if marker not in src:
    raise SystemExit('Could not locate `def run(self):` marker to insert helper before.')
  cell['source'] = src.replace(marker, helper + marker, 1).splitlines(keepends=True)
  print(f'[ok]   cell {idx} _fetch_one_tag_pass helper inserted')


def main():
  with NOTEBOOK.open() as f:
    nb = json.load(f)

  edit_tag_resolver(nb)
  add_fetch_one_tag_pass(nb)
  edit_run_method(nb)
  edit_meter_missing_fallback(nb)

  with NOTEBOOK.open('w') as f:
    json.dump(nb, f, indent=1)
    f.write('\n')

  print('Wrote', NOTEBOOK)


if __name__ == '__main__':
  main()

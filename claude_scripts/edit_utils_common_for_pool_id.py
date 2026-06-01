"""One-shot script: extend utils_common helpers so they carry instance_pool_id through.

Edits four helpers in `jobs/notebooks/utils_common.ipynb`:
  * `filter_valid_cost_rows` — accept rows where cluster_id OR instance_pool_id is set
  * `aggregate_costs_by_category` — include instance_pool_id in groupBy when present
  * `merge_cloud_cost_explorer` — null-safe `<=>` merge key, includes instance_pool_id
  * `write_other_cost_breakdown` — pre-filter to cluster_id IS NOT NULL (pool rows excluded)

Idempotent: each edit checks for a marker substring before applying.
"""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path('jobs/notebooks/utils_common.ipynb')


def find_cell(nb, signature_prefix):
  for i, cell in enumerate(nb['cells']):
    src = ''.join(cell.get('source', []))
    if signature_prefix in src:
      return i, cell, src
  raise SystemExit(f'Cell with {signature_prefix!r} not found')


def replace_in_cell(cell, old, new):
  src = ''.join(cell.get('source', []))
  if old not in src:
    return False, src
  new_src = src.replace(old, new, 1)
  cell['source'] = [line + '\n' for line in new_src.split('\n')]
  if cell['source'] and cell['source'][-1] == '\n':
    cell['source'][-1] = ''
    cell['source'] = [s for s in cell['source'] if s != '']
  if new_src.endswith('\n'):
    cell['source'][-1] = cell['source'][-1].rstrip('\n') + '\n'
  return True, new_src


def normalize_source(cell):
  """Round-trip source through splitlines(keepends=True) so the JSON list
  matches Jupyter's canonical format (one entry per line including the
  trailing newline)."""
  src = ''.join(cell.get('source', []))
  cell['source'] = src.splitlines(keepends=True)


def edit_aggregate_costs_by_category(nb):
  idx, cell, _ = find_cell(nb, 'def aggregate_costs_by_category(')
  src = ''.join(cell.get('source', []))
  if 'instance_pool_id' in src:
    print(f'[skip] cell {idx} aggregate_costs_by_category already has instance_pool_id')
    return

  old = (
    '  Expects input DataFrame to have columns:\n'
    '      cluster_id, currency, cost_incurred_date, category, {cost_col}\n'
    '\n'
    "  The 'category' column must contain values from: compute, storage, network, other.\n"
    '  Invariant enforced: cloud_cost = compute_cost + storage_cost + network_cost + other_cost\n'
    '  """\n'
    '  return (\n'
    "    classified_df.groupBy('cluster_id', 'currency', 'cost_incurred_date')\n"
    '    .agg(\n'
  )
  new = (
    '  Expects input DataFrame to have columns:\n'
    '      cluster_id, currency, cost_incurred_date, category, {cost_col}\n'
    '  May also contain `instance_pool_id` (cluster-tagged rows have it NULL;\n'
    '  pool-tagged rows have `cluster_id` NULL instead). When present, it is\n'
    '  carried through the groupBy so both row classes round-trip cleanly.\n'
    '\n'
    "  The 'category' column must contain values from: compute, storage, network, other.\n"
    '  Invariant enforced: cloud_cost = compute_cost + storage_cost + network_cost + other_cost\n'
    '  """\n'
    "  group_cols = ['cluster_id', 'currency', 'cost_incurred_date']\n"
    "  if 'instance_pool_id' in classified_df.columns:\n"
    "    group_cols.insert(1, 'instance_pool_id')\n"
    '\n'
    '  return (\n'
    '    classified_df.groupBy(*group_cols)\n'
    '    .agg(\n'
  )
  if old not in src:
    raise SystemExit(f'aggregate_costs_by_category: old block not found in cell {idx}')
  cell['source'] = (src.replace(old, new, 1)).splitlines(keepends=True)
  print(f'[ok]   cell {idx} aggregate_costs_by_category extended')


def edit_merge_cloud_cost_explorer(nb):
  idx, cell, _ = find_cell(nb, 'def merge_cloud_cost_explorer(')
  src = ''.join(cell.get('source', []))
  if 'instance_pool_id' in src:
    print(f'[skip] cell {idx} merge_cloud_cost_explorer already has instance_pool_id')
    return

  old = (
    'def merge_cloud_cost_explorer(target_table, source_df):\n'
    '  """MERGE incremental cloud cost data into the cloud cost explorer table.\n'
    '\n'
    '  Precondition: target_table must already exist (created via DDL in jobs/ddls/).\n'
    '  Matches on (cluster_id, currency, cost_incurred_date).\n'
    '  Updates cost columns on match; inserts new rows otherwise.\n'
    '  Uses DeltaTable API for DataFrame-native merge without temp views.\n'
    '  """\n'
    '  target = DeltaTable.forName(spark, target_table)\n'
    '  (\n'
    "    target.alias('t')\n"
    '    .merge(\n'
    "      source_df.alias('s'),\n"
    "      't.cluster_id = s.cluster_id AND t.currency = s.currency '\n"
    "      'AND t.cost_incurred_date = s.cost_incurred_date',\n"
    '    )\n'
    '    .whenMatchedUpdate(\n'
    '      set={\n'
    "        'cloud_cost': 's.cloud_cost',\n"
    "        'compute_cost': 's.compute_cost',\n"
    "        'storage_cost': 's.storage_cost',\n"
    "        'network_cost': 's.network_cost',\n"
    "        'other_cost': 's.other_cost',\n"
    "        'updated_at': 'current_timestamp()',\n"
    '      }\n'
    '    )\n'
    '    .whenNotMatchedInsert(\n'
    '      values={\n'
    "        'cluster_id': 's.cluster_id',\n"
    "        'cloud_cost': 's.cloud_cost',\n"
    "        'compute_cost': 's.compute_cost',\n"
    "        'storage_cost': 's.storage_cost',\n"
    "        'network_cost': 's.network_cost',\n"
    "        'other_cost': 's.other_cost',\n"
    "        'currency': 's.currency',\n"
    "        'cost_incurred_date': 's.cost_incurred_date',\n"
    "        'created_at': 'current_timestamp()',\n"
    "        'updated_at': 'current_timestamp()',\n"
    '      }\n'
    '    )\n'
    '    .execute()\n'
    '  )\n'
  )
  new = (
    'def merge_cloud_cost_explorer(target_table, source_df):\n'
    '  """MERGE incremental cloud cost data into the cloud cost explorer table.\n'
    '\n'
    '  Precondition: target_table must already exist (created via DDL in jobs/ddls/).\n'
    '  Matches null-safely on (cluster_id, instance_pool_id, currency, cost_incurred_date).\n'
    '  `cluster_id` and `instance_pool_id` are mutually exclusive — cluster-tagged rows\n'
    '  carry the former with the latter NULL; pool-tagged rows are the reverse. Null-safe\n'
    '  `<=>` equality lets both row classes round-trip through the same MERGE statement.\n'
    '  Updates cost columns on match; inserts new rows otherwise.\n'
    '  Uses DeltaTable API for DataFrame-native merge without temp views.\n'
    '\n'
    '  Backward compat: if `source_df` lacks the `instance_pool_id` column (older callers\n'
    '  that only emit cluster-tagged rows), it is auto-filled with NULL so the MERGE\n'
    '  condition still resolves.\n'
    '  """\n'
    "  if 'instance_pool_id' not in source_df.columns:\n"
    "    source_df = source_df.withColumn('instance_pool_id', F.lit(None).cast('string'))\n"
    '\n'
    '  target = DeltaTable.forName(spark, target_table)\n'
    '  (\n'
    "    target.alias('t')\n"
    '    .merge(\n'
    "      source_df.alias('s'),\n"
    "      't.cluster_id <=> s.cluster_id '\n"
    "      'AND t.instance_pool_id <=> s.instance_pool_id '\n"
    "      'AND t.currency = s.currency '\n"
    "      'AND t.cost_incurred_date = s.cost_incurred_date',\n"
    '    )\n'
    '    .whenMatchedUpdate(\n'
    '      set={\n'
    "        'cloud_cost': 's.cloud_cost',\n"
    "        'compute_cost': 's.compute_cost',\n"
    "        'storage_cost': 's.storage_cost',\n"
    "        'network_cost': 's.network_cost',\n"
    "        'other_cost': 's.other_cost',\n"
    "        'updated_at': 'current_timestamp()',\n"
    '      }\n'
    '    )\n'
    '    .whenNotMatchedInsert(\n'
    '      values={\n'
    "        'cluster_id': 's.cluster_id',\n"
    "        'instance_pool_id': 's.instance_pool_id',\n"
    "        'cloud_cost': 's.cloud_cost',\n"
    "        'compute_cost': 's.compute_cost',\n"
    "        'storage_cost': 's.storage_cost',\n"
    "        'network_cost': 's.network_cost',\n"
    "        'other_cost': 's.other_cost',\n"
    "        'currency': 's.currency',\n"
    "        'cost_incurred_date': 's.cost_incurred_date',\n"
    "        'created_at': 'current_timestamp()',\n"
    "        'updated_at': 'current_timestamp()',\n"
    '      }\n'
    '    )\n'
    '    .execute()\n'
    '  )\n'
  )
  if old not in src:
    raise SystemExit(f'merge_cloud_cost_explorer: old block not found in cell {idx}')
  cell['source'] = (src.replace(old, new, 1)).splitlines(keepends=True)
  print(f'[ok]   cell {idx} merge_cloud_cost_explorer extended')


def edit_filter_valid_cost_rows(nb):
  idx, cell, _ = find_cell(nb, 'def filter_valid_cost_rows(')
  src = ''.join(cell.get('source', []))
  if 'instance_pool_id' in src:
    print(f'[skip] cell {idx} filter_valid_cost_rows already has instance_pool_id')
    return

  old = (
    "def filter_valid_cost_rows(df, cluster_col='cluster_id', date_col='cost_incurred_date'):\n"
    '  """Filter out rows with null/empty cluster ID or null cost date."""\n'
    "  return df.filter((F.col(cluster_col).isNotNull()) & (F.col(cluster_col) != '')).filter(\n"
    '    F.col(date_col).isNotNull()\n'
    '  )'
  )
  new = (
    "def filter_valid_cost_rows(df, cluster_col='cluster_id', date_col='cost_incurred_date'):\n"
    '  """Filter out rows with no usable tag and no usage date.\n'
    '\n'
    '  Cluster-tagged rows have `cluster_id` populated; pool-tagged rows have\n'
    '  `instance_pool_id` populated (when the column exists on the input). A row\n'
    '  is kept when at least one of the two is non-null and non-empty.\n'
    '  """\n'
    "  cluster_valid = F.col(cluster_col).isNotNull() & (F.col(cluster_col) != '')\n"
    "  if 'instance_pool_id' in df.columns:\n"
    "    pool_valid = F.col('instance_pool_id').isNotNull() & (F.col('instance_pool_id') != '')\n"
    '    keep = cluster_valid | pool_valid\n'
    '  else:\n'
    '    keep = cluster_valid\n'
    '  return df.filter(keep).filter(F.col(date_col).isNotNull())'
  )
  if old not in src:
    raise SystemExit(f'filter_valid_cost_rows: old block not found in cell {idx}')
  cell['source'] = (src.replace(old, new, 1)).splitlines(keepends=True)
  print(f'[ok]   cell {idx} filter_valid_cost_rows extended')


def edit_write_other_cost_breakdown(nb):
  idx, cell, _ = find_cell(nb, 'def write_other_cost_breakdown(')
  src = ''.join(cell.get('source', []))
  # Scope idempotency check to the function body, not the whole cell — other
  # functions in this cell may legitimately mention `instance_pool_id` now.
  fn_start = src.find('def write_other_cost_breakdown(')
  fn_end = src.find('\ndef ', fn_start + 1)
  fn_body = src[fn_start : fn_end if fn_end != -1 else len(src)]
  if 'cluster_rows' in fn_body:
    print(f'[skip] cell {idx} write_other_cost_breakdown already pre-filters cluster rows')
    return

  old = (
    '  other_df = (\n'
    "    classified_df.filter(F.col('category') == 'other')\n"
    "    .groupBy('cluster_id', service_col, 'currency', 'cost_incurred_date')\n"
    "    .agg(F.sum('cost').alias('cost'))\n"
    "    .withColumnRenamed(service_col, 'service_name')\n"
    "    .withColumn('source_system', F.lit(source_system))\n"
    "    .withColumn('created_at', F.current_timestamp())\n"
    "    .withColumn('updated_at', F.current_timestamp())\n"
    '  )\n'
  )
  new = (
    '  # The breakdown table is keyed on cluster_id; pool-tagged rows (where\n'
    '  # cluster_id IS NULL and instance_pool_id IS NOT NULL) are skipped here.\n'
    '  # Pool VMs are pure compute by construction (see plan slice 3), so they\n'
    "  # produce no 'other' rows that need a per-service breakdown anyway.\n"
    "  cluster_rows = classified_df.filter(F.col('cluster_id').isNotNull())\n"
    '  other_df = (\n'
    "    cluster_rows.filter(F.col('category') == 'other')\n"
    "    .groupBy('cluster_id', service_col, 'currency', 'cost_incurred_date')\n"
    "    .agg(F.sum('cost').alias('cost'))\n"
    "    .withColumnRenamed(service_col, 'service_name')\n"
    "    .withColumn('source_system', F.lit(source_system))\n"
    "    .withColumn('created_at', F.current_timestamp())\n"
    "    .withColumn('updated_at', F.current_timestamp())\n"
    '  )\n'
  )
  if old not in src:
    raise SystemExit(f'write_other_cost_breakdown: old block not found in cell {idx}')
  cell['source'] = (src.replace(old, new, 1)).splitlines(keepends=True)
  print(f'[ok]   cell {idx} write_other_cost_breakdown extended')


def main():
  with NOTEBOOK.open() as f:
    nb = json.load(f)

  edit_filter_valid_cost_rows(nb)
  edit_aggregate_costs_by_category(nb)
  edit_merge_cloud_cost_explorer(nb)
  edit_write_other_cost_breakdown(nb)

  with NOTEBOOK.open('w') as f:
    json.dump(nb, f, indent=1)
    f.write('\n')

  print('Wrote', NOTEBOOK)


if __name__ == '__main__':
  main()

# Slice 0 — Azure check 3
#
# Paste this entire file into a Databricks notebook cell in the same workspace
# (and on the same compute) used by jobs/notebooks/azure_cloud_cost_explorer_app.ipynb.
# It expects two widgets `scope` and `subscription_id` and the same SP-credentials
# secret structure (`tenant_id`, `client_id`, `client_secret`) the production
# notebook already relies on. No code merged from this file.
#
# Purpose: confirm Azure Cost Management returns a non-empty `databricksinstancepoolid`
# tag value column for the trailing 7 days. Prints a Markdown block ready to paste
# into docs/plans/shared_clusters_and_pools/01-verification-spike.md under
# "## Verification results -> 3. Azure CM ...".

import json
from datetime import datetime, timedelta, timezone

from azure.identity import ClientSecretCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
  ExportType,
  QueryAggregation,
  QueryDataset,
  QueryDefinition,
  QueryGrouping,
  QueryTimePeriod,
  TimeframeType,
)

# Widgets — set defaults so the cell is also runnable interactively.
try:
  dbutils.widgets.text('scope', '')
  dbutils.widgets.text('subscription_id', '')
except Exception:  # noqa: BLE001 — outside Databricks runtime
  raise SystemExit('This snippet must be run inside a Databricks notebook.')

scope = dbutils.widgets.get('scope')
subscription_id = dbutils.widgets.get('subscription_id')
if not scope or not subscription_id:
  raise ValueError(
    'Set the `scope` and `subscription_id` widgets to the same values '
    'used by azure_cloud_cost_explorer_app.ipynb.'
  )

tenant_id = dbutils.secrets.get(scope, 'tenant_id')
client_id = dbutils.secrets.get(scope, 'client_id')
client_secret = dbutils.secrets.get(scope, 'client_secret')

credential = ClientSecretCredential(tenant_id, client_id, client_secret)
cm_client = CostManagementClient(credential)
cm_scope = f'/subscriptions/{subscription_id}'

now_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
start_utc = now_utc - timedelta(days=7)
end_utc = now_utc - timedelta(days=1)


def query_tag(tag_name: str):
  body = {
    'type': 'ActualCost',
    'timeframe': 'Custom',
    'timePeriod': {'from': start_utc.isoformat(), 'to': end_utc.isoformat()},
    'dataset': {
      'granularity': 'Daily',
      'aggregation': {'totalCost': {'name': 'Cost', 'function': 'Sum'}},
      'grouping': [
        {'type': 'TagKey', 'name': tag_name},
        {'type': 'Dimension', 'name': 'MeterCategory'},
      ],
    },
  }
  dataset = QueryDataset(
    granularity='Daily',
    aggregation={'totalCost': QueryAggregation(name='Cost', function='Sum')},
    grouping=[
      QueryGrouping(type='TagKey', name=tag_name),
      QueryGrouping(type='Dimension', name='MeterCategory'),
    ],
  )
  qdef = QueryDefinition(
    type=ExportType.ACTUAL_COST,
    timeframe=TimeframeType.CUSTOM,
    time_period=QueryTimePeriod(from_property=start_utc, to=end_utc),
    dataset=dataset,
  )
  try:
    response = cm_client.query.usage(scope=cm_scope, parameters=qdef)
  except Exception:
    from azure.core.rest import HttpRequest

    token = credential.get_token('https://management.azure.com/.default').token
    req = HttpRequest(
      method='POST',
      url=f'https://management.azure.com{cm_scope}/providers/Microsoft.CostManagement/query?api-version=2021-10-01',
      headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
      },
      content=json.dumps(body),
    )
    raw = cm_client._client._pipeline.run(req).http_response  # noqa: SLF001 — fallback path
    raw.raise_for_status()
    payload = raw.json()
    columns = [c['name'] for c in payload['properties']['columns']]
    rows = payload['properties'].get('rows', [])
    return columns, rows
  columns = [c.name for c in response.columns]
  rows = response.rows or []
  return columns, rows


def summarize(tag_name: str):
  columns, rows = query_tag(tag_name)
  tag_idx = next(
    (i for i, c in enumerate(columns) if c.lower() in {tag_name, tag_name + 'value', 'tagvalue'}),
    None,
  )
  cost_idx = next(
    (i for i, c in enumerate(columns) if c.lower() in {'cost', 'pretaxcost'}),
    None,
  )
  distinct_values = set()
  non_null_rows = 0
  total_cost = 0.0
  for r in rows:
    value = r[tag_idx] if tag_idx is not None else None
    if value:
      distinct_values.add(value)
      non_null_rows += 1
      if cost_idx is not None and r[cost_idx] is not None:
        total_cost += float(r[cost_idx])
  return {
    'columns': columns,
    'row_count': len(rows),
    'non_null_tag_rows': non_null_rows,
    'distinct_tag_values': len(distinct_values),
    'total_cost_on_tag': total_cost,
    'sample_values': sorted(distinct_values)[:5],
  }


pool_summary = summarize('databricksinstancepoolid')
cluster_summary = summarize('clusterid')

pool_passed = pool_summary['non_null_tag_rows'] > 0

md = [
  '### 3. Azure CM `databricksinstancepoolid` tag presence — '
  + ('PASS' if pool_passed else 'FAIL'),
  '',
  f'_Window: {start_utc.date()} → {end_utc.date()} (UTC), subscription `{subscription_id}`._',
  '',
  '| Tag queried | Row count | Non-null tag rows | Distinct tag values | Total cost on tag |',
  '| --- | --- | --- | --- | --- |',
  '| `databricksinstancepoolid` | {row_count} | {non_null_tag_rows} | {distinct_tag_values} | {total_cost_on_tag:.4f} |'.format(
    **pool_summary
  ),
  '| `clusterid` (control)      | {row_count} | {non_null_tag_rows} | {distinct_tag_values} | {total_cost_on_tag:.4f} |'.format(
    **cluster_summary
  ),
  '',
  'Sample pool tag values: ' + (', '.join(pool_summary['sample_values']) or '_none_'),
  '',
  'Decision-gate impact:',
]
if pool_passed:
  md.append(
    '- Tag is populated. Slice 3 can proceed with the parallel CE/Azure-CM '
    'query path keyed on `DatabricksInstancePoolId` (see '
    '[`02-architectural-decisions.md`](02-architectural-decisions.md) #2).'
  )
else:
  md.append(
    '- Tag is absent. Downgrade Instance Pools tab to DBU-only attribution '
    'and document the gap (see §4 decision gate).'
  )

print('\n'.join(md))

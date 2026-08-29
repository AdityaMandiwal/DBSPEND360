"""Ad-hoc verification of the Pipeline Compute tab numbers against the live app.

Checks the tiles/invariants the UI relies on:
  - total_spend == total_databricks_cost + COALESCE(total_cloud_cost, 0)
  - serverless_spend + classic_spend + mixed_spend == total_spend (KPI #12)
  - serverless_pipelines + classic_pipelines + mixed_pipelines == total_pipelines
  - sum(workload_breakdown) == total_spend (exact, all-workspace split)
  - per-row: sum(days[].total_cost) == row.total_cost (drill-down invariant #11)
  - the same, but with an active workload_type chip filter (the suspected bug)
  - the landed-day average rendered by the Total Spend tile
"""

import datetime as dt

from dba_client import DatabricksAppClient

# Resolve the current app from DATABRICKS_APP_NAME and the active Databricks
# CLI profile/host. This avoids pinning verification to a retired deployment
# URL (and works for the current Azure app without embedding its hostname).
client = DatabricksAppClient()

end = dt.date.today()
start = end - dt.timedelta(days=29)
S, E = start.isoformat(), end.isoformat()
print(f'app {client.app_url}')
print(f'window {S}..{E} (30 days inclusive)\n')


def g(path):
    """GET one authenticated endpoint from the discovered app."""
    return client.get(path)


summary = g(f'/api/pipelines/summary?start_date={S}&end_date={E}')
print('=== SUMMARY ===')
for k in (
    'total_pipelines', 'serverless_pipelines', 'classic_pipelines',
    'mixed_pipelines', 'metadata_unavailable', 'total_spend',
    'serverless_spend', 'classic_spend', 'mixed_spend',
    'total_databricks_cost', 'total_cloud_cost', 'date_range_days',
    'dbu_in_non_covered_workspaces',
):
    print(f'  {k}: {summary.get(k)}')
wb = summary.get('workload_breakdown', {})
print(f'  workload_breakdown: {wb}')

ts = summary['total_spend']
tdc = summary['total_databricks_cost']
tcc = summary.get('total_cloud_cost') or 0.0
print('\n=== SUMMARY INVARIANTS ===')
print(
    '  total_spend == total_databricks_cost + COALESCE(total_cloud_cost, 0)? '
    f'{abs(ts - (tdc + tcc)) < 0.01}  ({ts} vs {tdc} + {tcc})'
)
split = summary['serverless_spend'] + summary['classic_spend'] + summary['mixed_spend']
print(f'  serverless+classic+mixed == total_spend? {abs(split - ts) < 0.01}  ({split} vs {ts})')
pc = summary['serverless_pipelines'] + summary['classic_pipelines'] + summary['mixed_pipelines']
print(
    '  pipeline-count split == total_pipelines? '
    f"{pc == summary['total_pipelines']}  "
    f"({pc} vs {summary['total_pipelines']})"
)
wbsum = sum(wb.values())
print(
    '  sum(workload_breakdown, all workspaces) == total_spend? '
    f'{abs(wbsum - ts) < 0.01}  ({wbsum} vs {ts})'
)

# The tile divides by landed data days so an incomplete newest billing day
# does not dilute the visible run rate.
fe_avg = ts / max(summary.get('data_days', 0), 1)
print('\n=== AVG TILE ===')
print(f'  FE landed-day avg = total_spend / data_days = {fe_avg:.2f}')

# Drill-down invariant, unfiltered.
print('\n=== DRILL-DOWN (unfiltered) ===')
grouped = g(f'/api/pipelines/grouped?start_date={S}&end_date={E}&page=1&per_page=25')
rows = grouped['data']
print(f"  rows: {len(rows)} / total {grouped['total_count']}")
sum_active_days = 0
bad = 0
for r in rows:
    days_sum = sum(d['total_cost'] for d in r['days'])
    sum_active_days += r['active_days']
    if abs(days_sum - r['total_cost']) > 0.01:
        bad += 1
        print(f"    MISMATCH {r['pipeline_id']}: days={days_sum:.2f} row={r['total_cost']:.2f}")
print(f'  rows with days!=total: {bad}')
if sum_active_days:
    true_ppd = sum(r['total_cost'] for r in rows) / sum_active_days
    print(
        f'  true per-pipeline-day avg (this page) = {true_ppd:.2f}  '
        f'(sum active_days={sum_active_days})'
    )

# Drill-down invariant WITH a workload chip filter (the suspected bug).
# Pick the dominant workload from the breakdown.
if wb:
    top_wl = max(wb, key=wb.get)
    print(f'\n=== DRILL-DOWN (workload_type={top_wl!r}) ===')
    gf = g(
        f"/api/pipelines/grouped?start_date={S}&end_date={E}&page=1&per_page=25"
        f"&workload_type={top_wl.replace(' ', '%20')}"
    )
    frows = gf['data']
    print(f"  rows: {len(frows)} / total {gf['total_count']}")
    bad = 0
    for r in frows:
        days_sum = sum(d['total_cost'] for d in r['days'])
        if abs(days_sum - r['total_cost']) > 0.01:
            bad += 1
            print(
                f"    MISMATCH {r['pipeline_id']} ({r['workload_type']}): "
                f"days_sum={days_sum:.2f} row_total={r['total_cost']:.2f} "
                f"active_days={r['active_days']} n_days={len(r['days'])}"
            )
    print(f'  rows with days!=total under filter: {bad}')

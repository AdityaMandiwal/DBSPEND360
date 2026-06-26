"""Ad-hoc verification of the Pipeline Compute tab numbers against the live app.

Checks the tiles/invariants the UI relies on:
  - total_spend == total_databricks_cost (v1 DBU-only invariant)
  - serverless_spend + classic_spend + mixed_spend == total_spend (KPI #12)
  - serverless_pipelines + classic_pipelines + mixed_pipelines == total_pipelines
  - sum(workload_breakdown) == total_spend (exact split)
  - per-row: sum(days[].total_cost) == row.total_cost (drill-down invariant #11)
  - the same, but with an active workload_type chip filter (the suspected bug)
  - the "Avg per Pipeline-Day" tile math the FE renders vs a true per-pipeline-day avg
"""

import datetime as dt

from dba_client import DatabricksAppClient

APP = "https://dbspend360-aditya-1444828305810485.aws.databricksapps.com"
client = DatabricksAppClient(APP)

end = dt.date.today()
start = end - dt.timedelta(days=30)
S, E = start.isoformat(), end.isoformat()
print(f"window {S}..{E}\n")


def g(path):
    return client.get(path)


summary = g(f"/api/pipelines/summary?start_date={S}&end_date={E}")
print("=== SUMMARY ===")
for k in (
    "total_pipelines", "serverless_pipelines", "classic_pipelines",
    "mixed_pipelines", "metadata_unavailable", "total_spend",
    "serverless_spend", "classic_spend", "mixed_spend",
    "total_databricks_cost", "date_range_days",
):
    print(f"  {k}: {summary.get(k)}")
wb = summary.get("workload_breakdown", {})
print(f"  workload_breakdown: {wb}")

ts = summary["total_spend"]
tdc = summary["total_databricks_cost"]
print("\n=== SUMMARY INVARIANTS ===")
print(f"  total_spend == total_databricks_cost? {abs(ts - tdc) < 0.01}  ({ts} vs {tdc})")
split = summary["serverless_spend"] + summary["classic_spend"] + summary["mixed_spend"]
print(f"  serverless+classic+mixed == total_spend? {abs(split - ts) < 0.01}  ({split} vs {ts})")
pc = summary["serverless_pipelines"] + summary["classic_pipelines"] + summary["mixed_pipelines"]
print(f"  pipeline-count split == total_pipelines? {pc == summary['total_pipelines']}  ({pc} vs {summary['total_pipelines']})")
wbsum = sum(wb.values())
print(f"  sum(workload_breakdown) == total_spend? {abs(wbsum - ts) < 0.01}  ({wbsum} vs {ts})")

# "Avg per Pipeline-Day" tile (FE math) vs a true per-pipeline-day average.
fe_avg = ts / max(summary["date_range_days"], 1)
print("\n=== AVG TILE ===")
print(f"  FE 'Avg per Pipeline-Day' = total_spend / date_range_days = {fe_avg:.2f}")

# Drill-down invariant, unfiltered.
print("\n=== DRILL-DOWN (unfiltered) ===")
grouped = g(f"/api/pipelines/grouped?start_date={S}&end_date={E}&page=1&per_page=25")
rows = grouped["data"]
print(f"  rows: {len(rows)} / total {grouped['total_count']}")
sum_active_days = 0
bad = 0
for r in rows:
    days_sum = sum(d["total_cost"] for d in r["days"])
    sum_active_days += r["active_days"]
    if abs(days_sum - r["total_cost"]) > 0.01:
        bad += 1
        print(f"    MISMATCH {r['pipeline_id']}: days={days_sum:.2f} row={r['total_cost']:.2f}")
print(f"  rows with days!=total: {bad}")
if sum_active_days:
    true_ppd = sum(r["total_cost"] for r in rows) / sum_active_days
    print(f"  true per-pipeline-day avg (this page) = {true_ppd:.2f}  (sum active_days={sum_active_days})")

# Drill-down invariant WITH a workload chip filter (the suspected bug).
# Pick the dominant workload from the breakdown.
if wb:
    top_wl = max(wb, key=wb.get)
    print(f"\n=== DRILL-DOWN (workload_type={top_wl!r}) ===")
    gf = g(
        f"/api/pipelines/grouped?start_date={S}&end_date={E}&page=1&per_page=25"
        f"&workload_type={top_wl.replace(' ', '%20')}"
    )
    frows = gf["data"]
    print(f"  rows: {len(frows)} / total {gf['total_count']}")
    bad = 0
    for r in frows:
        days_sum = sum(d["total_cost"] for d in r["days"])
        if abs(days_sum - r["total_cost"]) > 0.01:
            bad += 1
            print(
                f"    MISMATCH {r['pipeline_id']} ({r['workload_type']}): "
                f"days_sum={days_sum:.2f} row_total={r['total_cost']:.2f} "
                f"active_days={r['active_days']} n_days={len(r['days'])}"
            )
    print(f"  rows with days!=total under filter: {bad}")

"""Verify the new cached-name-map path latency.

Simulates: build job_id->name map once (cached), then run the aggregation-only
list query and a name-search aggregation (IN-list of name-matched ids).
"""
import json
import subprocess
import time
from datetime import date, timedelta
from databricks.sdk import WorkspaceClient

PROFILE = "e2-demo-field-eng"
HOST = "https://e2-demo-field-eng.cloud.databricks.com"
WAREHOUSE_ID = "8baced1ff014912d"
TABLE = "dbspend360.04june.dbspend360_total_job_spends"

end = date.today()
start = end - timedelta(days=30)
S, E = start.isoformat(), end.isoformat()

_tok = json.loads(subprocess.run(
    ["databricks", "auth", "token", "--profile", PROFILE],
    capture_output=True, text=True, check=True).stdout)["access_token"]
w = WorkspaceClient(host=HOST, token=_tok)


def run(label, sql):
    t0 = time.perf_counter()
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="50s")
    dt = (time.perf_counter() - t0) * 1000
    rows = resp.result.data_array if resp.result else []
    print(f"{label:42s} {dt:8.0f} ms   rows={len(rows or [])}")
    return resp


def agg_query(search_filter=""):
    return f"""
WITH filtered AS (
  SELECT job_id, run_id, cloud_cost, databricks_cost, compute_cost, storage_cost, network_cost, other_cost
  FROM {TABLE} WHERE usage_date >= '{S}' AND usage_date <= '{E}' {search_filter}
),
run_level AS (
  SELECT job_id, run_id, SUM(cloud_cost) cloud_cost, SUM(databricks_cost) databricks_cost,
         SUM(compute_cost) cc, SUM(storage_cost) sc, SUM(network_cost) nc, SUM(other_cost) oc
  FROM filtered GROUP BY job_id, run_id
),
job_level AS (
  SELECT job_id, SUM(cloud_cost) tc, SUM(databricks_cost) td, SUM(cc) tcc, SUM(sc) tsc,
         SUM(nc) tnc, SUM(oc) toc, COUNT(*) rc FROM run_level GROUP BY job_id
)
SELECT job_id, tc, td, rc, COUNT(*) OVER() tm, tcc, tsc, tnc, toc
FROM job_level ORDER BY (tc+td) DESC LIMIT 50 OFFSET 0
"""


print(f"date range: {S} .. {E}\n")

# 1) Build the name map once (this is the cached ~5s cost, paid per TTL).
t0 = time.perf_counter()
resp = w.statement_execution.execute_statement(
    warehouse_id=WAREHOUSE_ID,
    statement="SELECT job_id, MAX_BY(name, change_time) AS name FROM system.lakeflow.jobs GROUP BY job_id",
    wait_timeout="50s")
name_map = {str(r[0]): r[1] for r in (resp.result.data_array or []) if r[0] is not None and r[1] is not None}
print(f"{'0. build name map (cached per TTL)':42s} {(time.perf_counter()-t0)*1000:8.0f} ms   jobs={len(name_map)}")

# 2) List query (warm path): aggregation only.
run("1. LIST (aggregation only)", agg_query())

# 3) Search 'feip-rtm' (warm path): name-matched ids from map -> IN-list.
term = "feip-rtm"
matched = [j for j, n in name_map.items() if n and term in n.lower()]
esc = [j.replace("'", "''") for j in matched[:5000]]
in_list = ", ".join(f"'{j}'" for j in esc)
preds = [f"job_id LIKE '%{term}%'"]
if in_list:
    preds.append(f"job_id IN ({in_list})")
sf = "AND (" + " OR ".join(preds) + ")"
print(f"   '{term}' matched {len(matched)} job_ids in map")
run(f"2. SEARCH '{term}' (aggregation only)", agg_query(sf))

print("\ndone.")

"""Ad-hoc timing probe for the Job Clusters search path.

Measures each component of the grouped-job-spends query independently so we can
see where the 5-10s actually goes (raw scan vs SCD join vs aggregation vs runs).

Run: uv run python claude_scripts/time_job_search.py
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

# Two profiles match this host, so let the CLI resolve the token explicitly
# with --profile, then hand the SDK a plain host+token.
_tok = json.loads(
    subprocess.run(
        ["databricks", "auth", "token", "--profile", PROFILE],
        capture_output=True, text=True, check=True,
    ).stdout
)["access_token"]
w = WorkspaceClient(host=HOST, token=_tok)


def run(label, sql):
    t0 = time.perf_counter()
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="50s"
    )
    dt = time.perf_counter() - t0
    rows = resp.result.data_array if resp.result else None
    n = len(rows) if rows else 0
    state = resp.status.state.value if resp.status else "?"
    print(f"{label:38s} {dt*1000:8.0f} ms   state={state} rows={n}")
    return resp, dt


print(f"date range: {S} .. {E}  warehouse={WAREHOUSE_ID}\n")

# 1) Raw scan cost + row count for the window (no job filter).
run("1. raw scan COUNT(*) [date range]", f"""
SELECT COUNT(*) FROM {TABLE}
WHERE usage_date >= '{S}' AND usage_date <= '{E}'
""")

# 2) Distinct jobs in the window.
run("2. distinct job_id in window", f"""
SELECT COUNT(DISTINCT job_id) FROM {TABLE}
WHERE usage_date >= '{S}' AND usage_date <= '{E}'
""")

# 3) SCD collapse on system.lakeflow.jobs (used by name join + name_matches).
run("3. SCD jobs MAX_BY group-by", """
SELECT COUNT(*) FROM (
  SELECT job_id, MAX_BY(name, change_time) AS name
  FROM system.lakeflow.jobs GROUP BY job_id
)
""")

# 4) Full grouped query, NO search (current production shape).
grouped_nosearch = f"""
WITH filtered AS (
  SELECT job_id, run_id, cloud_cost, databricks_cost, compute_cost, storage_cost, network_cost, other_cost
  FROM {TABLE}
  WHERE usage_date >= '{S}' AND usage_date <= '{E}'
),
run_level AS (
  SELECT job_id, run_id, SUM(cloud_cost) cloud_cost, SUM(databricks_cost) databricks_cost,
         SUM(compute_cost) compute_cost, SUM(storage_cost) storage_cost,
         SUM(network_cost) network_cost, SUM(other_cost) other_cost
  FROM filtered GROUP BY job_id, run_id
),
job_level AS (
  SELECT job_id, SUM(cloud_cost) total_cloud_cost, SUM(databricks_cost) total_databricks_cost,
         SUM(compute_cost) tcc, SUM(storage_cost) tsc, SUM(network_cost) tnc, SUM(other_cost) toc,
         COUNT(*) run_count
  FROM run_level GROUP BY job_id
)
SELECT j.job_id, j.total_cloud_cost, j.total_databricks_cost, j.run_count, lj.name,
       COUNT(*) OVER() total_matching, j.tcc, j.tsc, j.tnc, j.toc
FROM job_level j
LEFT JOIN (SELECT job_id, MAX_BY(name, change_time) AS name FROM system.lakeflow.jobs GROUP BY job_id) lj
ON j.job_id = lj.job_id
ORDER BY (j.total_cloud_cost + j.total_databricks_cost) DESC
LIMIT 50 OFFSET 0
"""
resp4, _ = run("4. grouped query (no search)", grouped_nosearch)

# Grab a real job_id + a name token to drive the search test.
sample_job_id = None
sample_token = None
if resp4.result and resp4.result.data_array:
    sample_job_id = resp4.result.data_array[0][0]
    nm = resp4.result.data_array[0][4]
    if nm:
        sample_token = nm.split()[0][:8]
print(f"   sample job_id={sample_job_id}  name token={sample_token!r}")

# 5) Grouped query WITH pushdown search (the new shape) using a name token.
if sample_token:
    tok = sample_token.replace("'", "''")
    grouped_search = f"""
WITH name_matches AS (
  SELECT job_id FROM (
    SELECT job_id, MAX_BY(name, change_time) AS name FROM system.lakeflow.jobs GROUP BY job_id
  ) WHERE LOWER(COALESCE(name,'')) LIKE LOWER('%{tok}%')
),
filtered AS (
  SELECT job_id, run_id, cloud_cost, databricks_cost, compute_cost, storage_cost, network_cost, other_cost
  FROM {TABLE}
  WHERE usage_date >= '{S}' AND usage_date <= '{E}'
  AND (job_id LIKE '%{tok}%' OR job_id IN (SELECT job_id FROM name_matches))
),
run_level AS (
  SELECT job_id, run_id, SUM(cloud_cost) cloud_cost, SUM(databricks_cost) databricks_cost,
         SUM(compute_cost) compute_cost, SUM(storage_cost) storage_cost,
         SUM(network_cost) network_cost, SUM(other_cost) other_cost
  FROM filtered GROUP BY job_id, run_id
),
job_level AS (
  SELECT job_id, SUM(cloud_cost) total_cloud_cost, SUM(databricks_cost) total_databricks_cost,
         SUM(compute_cost) tcc, SUM(storage_cost) tsc, SUM(network_cost) tnc, SUM(other_cost) toc,
         COUNT(*) run_count
  FROM run_level GROUP BY job_id
)
SELECT j.job_id, j.total_cloud_cost, j.total_databricks_cost, j.run_count, lj.name,
       COUNT(*) OVER() total_matching, j.tcc, j.tsc, j.tnc, j.toc
FROM job_level j
LEFT JOIN (SELECT job_id, MAX_BY(name, change_time) AS name FROM system.lakeflow.jobs GROUP BY job_id) lj
ON j.job_id = lj.job_id
ORDER BY (j.total_cloud_cost + j.total_databricks_cost) DESC
LIMIT 50 OFFSET 0
"""
    run(f"5. grouped query (search {sample_token!r})", grouped_search)

# 6) Single-job runs query (lazy-load on expand).
if sample_job_id:
    jid = sample_job_id.replace("'", "''")
    run("6. runs for one job", f"""
SELECT run_id, cluster_id, MIN(usage_date) s, MAX(usage_date) e,
       SUM(cloud_cost), SUM(databricks_cost), SUM(compute_cost), SUM(storage_cost), SUM(network_cost), SUM(other_cost)
FROM {TABLE}
WHERE job_id = '{jid}' AND usage_date >= '{S}' AND usage_date <= '{E}'
GROUP BY run_id, cluster_id ORDER BY e DESC, run_id DESC LIMIT 10
""")

print("\n--- ALTERNATIVE NAME-RESOLUTION STRATEGIES ---")

# Collect the page's 50 job_ids from query 4.
page_ids = [r[0] for r in resp4.result.data_array] if resp4.result and resp4.result.data_array else []
in_list = ", ".join(f"'{j}'" for j in page_ids)

# 7) Aggregation only, NO name join at all.
run("7. aggregation only (no name join)", f"""
WITH filtered AS (
  SELECT job_id, run_id, cloud_cost, databricks_cost, compute_cost, storage_cost, network_cost, other_cost
  FROM {TABLE} WHERE usage_date >= '{S}' AND usage_date <= '{E}'
),
run_level AS (
  SELECT job_id, run_id, SUM(cloud_cost) c, SUM(databricks_cost) d
  FROM filtered GROUP BY job_id, run_id
),
job_level AS (
  SELECT job_id, SUM(c) tc, SUM(d) td, COUNT(*) rc FROM run_level GROUP BY job_id
)
SELECT job_id, tc, td, rc, COUNT(*) OVER() FROM job_level
ORDER BY (tc+td) DESC LIMIT 50 OFFSET 0
""")

# 8) Name resolution for the 50 page job_ids via IN-list (literal).
if in_list:
    run("8. names for 50 ids (IN literal)", f"""
SELECT job_id, MAX_BY(name, change_time) AS name
FROM system.lakeflow.jobs
WHERE job_id IN ({in_list})
GROUP BY job_id
""")

# 9) Name search via filtered DISTINCT scan (no MAX_BY group-by over all jobs).
if sample_token:
    tok = sample_token.replace("'", "''")
    run("9. name search DISTINCT (filtered)", f"""
SELECT DISTINCT job_id FROM system.lakeflow.jobs
WHERE LOWER(COALESCE(name,'')) LIKE LOWER('%{tok}%')
""")

# 10) Optimized single query: aggregate, page, then resolve names only for the
#     page's job_ids via a semi-joined subquery (no full SCD group-by).
run("10. optimized single (semi-join names)", f"""
WITH filtered AS (
  SELECT job_id, run_id, cloud_cost, databricks_cost, compute_cost, storage_cost, network_cost, other_cost
  FROM {TABLE} WHERE usage_date >= '{S}' AND usage_date <= '{E}'
),
run_level AS (
  SELECT job_id, run_id, SUM(cloud_cost) c, SUM(databricks_cost) d,
         SUM(compute_cost) cc, SUM(storage_cost) sc, SUM(network_cost) nc, SUM(other_cost) oc
  FROM filtered GROUP BY job_id, run_id
),
job_level AS (
  SELECT job_id, SUM(c) tc, SUM(d) td, SUM(cc) tcc, SUM(sc) tsc, SUM(nc) tnc, SUM(oc) toc, COUNT(*) rc
  FROM run_level GROUP BY job_id
),
counted AS (SELECT COUNT(*) AS total_matching FROM job_level),
page AS (
  SELECT * FROM job_level ORDER BY (tc+td) DESC LIMIT 50 OFFSET 0
)
SELECT p.job_id, p.tc, p.td, p.rc, lj.name, c.total_matching, p.tcc, p.tsc, p.tnc, p.toc
FROM page p
CROSS JOIN counted c
LEFT JOIN (
  SELECT job_id, MAX_BY(name, change_time) AS name
  FROM system.lakeflow.jobs
  WHERE job_id IN (SELECT job_id FROM page)
  GROUP BY job_id
) lj ON p.job_id = lj.job_id
ORDER BY (p.tc+p.td) DESC
""")

print("\ndone.")

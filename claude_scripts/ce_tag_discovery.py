# Databricks notebook source
# Discovery: which AWS Cost Explorer tag carries DLT pipeline EC2 cost?
# Read-only. Uses the same service credential as aws_cloud_cost_explorer_app.
# Findings are accumulated into OUT and returned via dbutils.notebook.exit so
# the orchestrator can read them from the Jobs API (cell stdout is not exposed).
import boto3
from datetime import date, timedelta

dbutils.widgets.text("catalog", "dbspend360", "CATALOG")
dbutils.widgets.text("schema", "04june", "SCHEMA")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

OUT = []


def log(s=""):
    OUT.append(str(s))


session = boto3.Session(
    botocore_session=dbutils.credentials.getServiceCredentialsProvider("dbspend-read-ce"),
    region_name="us-east-1",
)
ce = session.client("ce")

end = date.today()
start = end - timedelta(days=21)
tp = {"Start": start.isoformat(), "End": end.isoformat()}
SERVICES = ["Amazon Elastic Compute Cloud - Compute", "EC2 - Other"]
svc_filter = {"Dimensions": {"Key": "SERVICE", "Values": SERVICES}}
log(f"Window: {tp}")


def grouped_cost_by_tag(tag_key, collect_values=False):
    total_tagged = total_untagged = 0.0
    vals = []
    valset = set()
    params = {
        "TimePeriod": tp, "Granularity": "MONTHLY", "Metrics": ["AmortizedCost"],
        "GroupBy": [{"Type": "TAG", "Key": tag_key}], "Filter": svc_filter,
    }
    while True:
        r = ce.get_cost_and_usage(**params)
        for tb in r["ResultsByTime"]:
            for g in tb["Groups"]:
                key = g["Keys"][0]
                val = key.split("$", 1)[1] if "$" in key else key
                amt = float(g["Metrics"]["AmortizedCost"]["Amount"])
                if amt == 0:
                    continue
                if val.strip() == "":
                    total_untagged += amt
                else:
                    total_tagged += amt
                    vals.append((val, amt))
                    if collect_values:
                        valset.add(val.strip())
        tok = r.get("NextPageToken")
        if not tok:
            break
        params["NextPageToken"] = tok
    vals.sort(key=lambda x: -x[1])
    return total_tagged, total_untagged, len(vals), vals[:8], valset


# 1) All cost-allocation tag keys active in the period
all_keys = ce.get_tags(TimePeriod=tp).get("Tags", [])
log(f"TOTAL TAG KEYS: {len(all_keys)}")
log("ALL KEYS: " + ", ".join(all_keys))

# 2) For each Databricks-ish tag key, EC2-family cost grouped by it
dbx_keys = [
    k for k in all_keys
    if any(s in k.lower() for s in
           ["databricks", "cluster", "pipeline", "job", "vendor",
            "instance", "dlt", "warehouse", "group", "creator"])
]
log("\nDBX-ish keys: " + ", ".join(dbx_keys))
for k in dbx_keys:
    tt, tu, nv, top, _ = grouped_cost_by_tag(k)
    log(f"\n=== TAG {k}: tagged=${tt:,.2f}  blank=${tu:,.2f}  distinct={nv}")
    for v, a in top:
        log(f"     {v[:60]:<60} ${a:,.2f}")

# 3) Cross-check DLT classic cluster_ids (staging) vs CE ClusterId tag values
dlt_clusters = [
    r["cluster_id"] for r in spark.sql(f"""
        SELECT cluster_id, SUM(databricks_cost) dbu
        FROM {catalog}.`{schema}`.dbspend360_pipeline_dbu_cost
        WHERE cluster_id IS NOT NULL
          AND usage_date >= date_sub(current_date(), 21)
        GROUP BY cluster_id ORDER BY dbu DESC LIMIT 10
    """).collect()
]
_, _, _, _, ce_clusterids = grouped_cost_by_tag("ClusterId", collect_values=True)
log(f"\nCE ClusterId distinct values: {len(ce_clusterids)}")
log("Top DLT classic cluster_ids (staging) vs CE presence:")
for c in dlt_clusters:
    base = c.rsplit("-", 1)[0] if c.count("-") >= 3 else c
    log(f"  staging={c}  exact={c in ce_clusterids}  base={base} base_in_CE={base in ce_clusterids}")

# COMMAND ----------
result = "\n".join(OUT)
print(result)
dbutils.notebook.exit(result[:40000])

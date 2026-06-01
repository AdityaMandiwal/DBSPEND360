# Slice 0 — Verification spike (½ day, no code merged)

[← back to plan index](README.md)

Run these read-only queries against the customer workspace and capture results in this doc before starting Slice 2.

## 1. Are interactive cluster rows present in billing?

```sql
SELECT cluster_source, COUNT(*)
FROM system.compute.clusters
WHERE create_time >= current_date() - INTERVAL 30 DAYS
GROUP BY cluster_source;
```

## 2. Is `instance_pool_id` populated in DBU usage?

```sql
SELECT usage_metadata.instance_pool_id, SUM(usage_quantity)
FROM system.billing.usage
WHERE usage_date >= current_date() - INTERVAL 30 DAYS
  AND usage_metadata.instance_pool_id IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

## 3. Do pool VMs carry the `DatabricksInstancePoolId` tag in cloud cost?

Run an executable check, not a manual eyeball pass.

**AWS — via CUR + Athena (preferred, more accurate than CE):**

```sql
SELECT
  resource_tags['user_DatabricksInstancePoolId'] AS pool_tag,
  resource_tags['user_ClusterId']                AS cluster_tag,
  SUM(line_item_unblended_cost)                  AS cost
FROM <cur_database>.<cur_table>
WHERE line_item_usage_start_date >= current_date - INTERVAL '30' DAY
  AND resource_tags['user_DatabricksInstancePoolId'] IS NOT NULL
GROUP BY 1, 2
ORDER BY cost DESC
LIMIT 20;
```

**AWS — via CE direct (if CUR isn't available):** call CE with `GroupBy=[{Type:TAG, Key:DatabricksInstancePoolId}, {Type:DIMENSION, Key:SERVICE}]` for a recent 7-day window and confirm non-empty rows.

**Azure:** invoke `_query_with_retries` from `azure_cloud_cost_explorer_app.ipynb` once with `tag_name="databricksinstancepoolid"` and confirm the response carries the pool-tag-value column.

Capture: count of distinct pool tag values, count of rows where `pool_tag IS NOT NULL AND cluster_tag IS NULL` (the idle case), and rows where both are populated (the active-attached case).

## 4. Can the app SP list pools?

```bash
databricks instance-pools list
```

## 5. Does `system.compute.clusters` expose `worker_instance_pool_id` / `driver_instance_pool_id` columns in this workspace?

Older runtimes occasionally have the column absent. Note: the worker column is named `worker_instance_pool_id`, not `instance_pool_id` — this naming was confirmed by the verification spike and matters for the slice 3 ETL skeleton.

```sql
DESCRIBE TABLE system.compute.clusters;

SELECT cluster_id, worker_instance_pool_id, driver_instance_pool_id
FROM system.compute.clusters
WHERE worker_instance_pool_id IS NOT NULL
   OR driver_instance_pool_id IS NOT NULL
LIMIT 10;
```

## Decision gate

If (2) returns no rows or (3) shows tags are missing in the customer's setup, downgrade the Instance Pools tab scope to "DBU-only attribution" and document the gap. If (5) shows the column is absent, fall back to the SDK-only pool catalog without a pool↔cluster attachment join.

## How to reproduce

For checks 1, 2, 4, 5 (local, against the workspace's SQL warehouse + SDK):

```bash
uv run python claude_scripts/verify_slice_0.py
```

For check 3 (Azure Cost Management — requires the same SP credentials the production Azure notebook uses), paste `claude_scripts/verify_slice_0_azure_check.py` into a Databricks notebook cell in this workspace with widgets `scope` and `subscription_id` set to the values used by `azure_cloud_cost_explorer_app.ipynb`, run it, and append the printed block to the table below.

## Verification results

_Captured 2026-05-30T16:37:06+00:00 against `https://adb-984752964297111.11.azuredatabricks.net` (warehouse `148ccb90800933a1`)._

### 1. cluster source breakdown — PASS

- **Summary:** UI=279, API=281, JOB=6271, interactive_total=560
- **Note:** Interactive clusters present in the last 30 days — Shared Clusters tab has data to render.

| cluster_source | cluster_count |
| --- | --- |
| PIPELINE | 49026 |
| JOB | 6271 |
| API | 281 |
| UI | 279 |
| PIPELINE_MAINTENANCE | 32 |

### 2. `instance_pool_id` in billing usage — PASS

- **Summary:** distinct pools with non-null pool DBU rows in last 30d: 11
- **Note:** Pool-attributed DBU present. As predicted in [§4.5 #1](02-architectural-decisions.md) and the slice 3 plan, the magnitudes are tiny (top pool only ~100 DBUs/30d). The headline pool metric on the new tab must be cloud idle cost, not DBU.

| instance_pool_id | total_dbus (30d) |
| --- | --- |
| 0430-133405-hooky10-pool-qd35fkpb | 99.74 |
| 1017-162820-flaps24-pool-eaxm27j4 | 51.92 |
| 1010-173019-honor44-pool-ksw4stjz | 34.85 |
| 0225-111432-doers18-pool-mxks2nq7 | 24.54 |
| 0324-094341-chain6-pool-nuq65a5n | 6.63 |
| 1113-082032-jazzy13-pool-qwb0q5y7 | 1.61 |
| 0714-190649-pro39-pool-x3rgx6o0 | 0.77 |
| 1114-164230-bung40-pool-ne7msni8 | 0.76 |
| 0511-162911-taker144-pool-l8p4pu3j | 0.72 |
| 0420-143726-tools71-pool-gk5m7k3z | 0.37 |
| 0802-143749-grail729-pool-hPaknFfC | 0.04 |

### 3. Azure CM `databricksinstancepoolid` tag presence — PENDING

Requires the workspace-side Azure CM notebook run. Use `claude_scripts/verify_slice_0_azure_check.py` and paste the printed block here.

### 4. SDK can list instance pools — PASS

- **Summary:** pools visible to app SP: **368**
- **Note:** SP can enumerate pools — backend catalog can use the SDK directly. Top 5 (truncated):

| instance_pool_id | instance_pool_name | node_type_id | state |
| --- | --- | --- | --- |
| 0802-143749-grail729-pool-hPaknFfC | tm_test_pool | Standard_DS3_v2 | ACTIVE |
| 1003-114506-ores60-pool-1qmbIwnN | bireport | Standard_DS3_v2 | ACTIVE |
| 1031-053034-becks761-pool-D8pBk6XN | no-swimming | Standard_DS3_v2 | ACTIVE |
| 1107-152738-tripe968-pool-mAm4ha0I | vj-demo-pool | Standard_DS3_v2 | ACTIVE |
| 1120-005534-gird214-pool-IN8sObvq | suresh-pool-test | Standard_DS3_v2 | ACTIVE |

368 pools is large — the SDK list call returns within a second locally, but it will be worth wiring `list_instance_pools()` behind the process-wide `pool_catalog_cache` from the start (see [slice 3 backend](05-slice-3-instance-pools.md)) rather than hitting the SDK per request.

### 5. pool columns on `system.compute.clusters` — PASS (with schema correction)

- **Summary:** both pool columns present; pool↔cluster attachment join is feasible.
- **Schema correction discovered during this spike:** the worker-side column is `worker_instance_pool_id`, **not** `instance_pool_id` as the original plan draft assumed. The plan files have been updated to match the real schema (`02-architectural-decisions.md` #1, `05-slice-3-instance-pools.md` ETL skeleton and `get_pool_attached_clusters`). Slice 3 ETL must `COALESCE(worker_instance_pool_id, driver_instance_pool_id)` when computing attachment.

| cluster_id | worker_instance_pool_id | driver_instance_pool_id |
| --- | --- | --- |
| 0101-000041-pjccuyaf | 0317-053014-jowls55-pool-c4iccgww | 0317-053014-jowls55-pool-c4iccgww |
| 0101-040041-8slyayqu | 0317-053014-jowls55-pool-c4iccgww | 0317-053014-jowls55-pool-c4iccgww |
| 0102-043054-8kfs8h17 | 1010-173019-honor44-pool-ksw4stjz | 1010-173019-honor44-pool-ksw4stjz |
| 0102-043445-zylljbfr | 1010-173019-honor44-pool-ksw4stjz | 1010-173019-honor44-pool-ksw4stjz |

(Truncated to 4 of 10 sampled rows; in every observed row the worker pool and driver pool are the same value, which is consistent with how pools are usually configured but not something the ETL can assume.)

## Decision-gate outcome

- Locally-runnable checks **all PASS** with one schema correction (now applied to the plan docs).
- Check 3 remains **PENDING** until the Azure CM notebook is run. Slice 3 work can begin on slice 1 / slice 2 tracks in parallel, but the slice 3 cloud-cost ETL extension must not be merged before check 3 confirms the pool tag is populated.
- No fall-back to "DBU-only attribution" is currently warranted: cluster attachment columns exist, SDK pool listing works, and DBU pool rows are present (even if tiny).


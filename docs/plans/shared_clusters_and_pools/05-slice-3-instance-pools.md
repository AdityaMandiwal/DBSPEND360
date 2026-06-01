# Slice 3 — Instance Pools tab (4–6 days)

[← back to plan index](README.md)

## Data layer

This is the slice that requires touching the cloud-cost ETL.

### Cloud-cost ETL changes (the hard part)

**Architectural constraint** (locked in [§4.5 #2](02-architectural-decisions.md)): AWS CE allows exactly 2 `GroupBy` keys, and both slots are already used (`TAG ClusterId` + `DIMENSION SERVICE`). Same constraint on Azure CM (`TagKey + MeterCategory`). We cannot collect both `ClusterId` and `DatabricksInstancePoolId` in one API response. The ETL therefore needs a **second, parallel query path** keyed on the pool tag, unioned with the existing cluster-tag results.

- `dbspend360_cloud_cost_explorer` table: add a nullable column `instance_pool_id STRING`. Backfill with `NULL` for historical rows.
- `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`:
  - Make `tag_key` a list-or-single parameter. Run `get_cluster_costs_daily(tag_key="ClusterId", ...)` AND `get_cluster_costs_daily(tag_key="DatabricksInstancePoolId", ...)` per chunk.
  - The pool-tagged path emits rows with `cluster_id = NULL, instance_pool_id = <pool>`. Tag parsing on line 324 stays as-is — it returns whatever tag value the response carries; the caller knows which tag was queried.
  - `UNION ALL` both result sets before the existing merge.
  - Document the ~2x CE quota impact in the audit-log `quality_msg`. Throttle / backoff already handles `LimitExceededException`.
- `jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`:
  - Parameterize `tag_name` the same way. Add `"databricksinstancepoolid"` to `_AZURE_TAG_VALUE_CANDIDATES` (or pass it explicitly into `_resolve_cluster_id_column`).
  - Same UNION ALL pattern.
- `gcp_cloud_cost_explorer_app.ipynb`: leave as the existing `NotImplementedError` stub.

### DBU ETL extension

- New notebook `jobs/notebooks/dbspend360_pool_spends_app.ipynb`. Does NOT modify the existing DBU notebook.
- Pulls `system.billing.usage` rows where `usage_metadata.instance_pool_id IS NOT NULL`. No `cluster_source = 'JOB'` join filter — pool DBU is owned by the pool, not by a cluster.
- Aggregates by `(instance_pool_id, workspace_id, usage_date)`.
- Expectation: pool-attributed DBU is typically near zero (premium-edition pool surcharge only). Cluster runtime DBU bills to the cluster, not the pool. The headline metric for this tab will be cloud idle cost, not DBU.

### New DDL — `jobs/ddls/dbspend360_pool_spends.ipynb`

```sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_pool_spends (
  instance_pool_id   STRING,
  workspace_id       STRING,
  usage_date         DATE,
  -- attribution split (see §4.5 #1 — computed by subtraction, not row classification):
  idle_cloud_cost    DOUBLE,   -- pool_tag_total − sum(attached_cluster_tag_total)
  active_cloud_cost  DOUBLE,   -- sum(attached_cluster_tag_total) for clusters tied to this pool
  pool_total_cost    DOUBLE,   -- raw pool_tag_total (debug / reconciliation aid)
  databricks_cost    DOUBLE,   -- DBU attributed by usage_metadata.instance_pool_id (typically ~0)
  currency           STRING,
  total_cost         DOUBLE,
  created_at         TIMESTAMP,
  updated_at         TIMESTAMP
)
CLUSTER BY AUTO;
```

- Dropped `compute_cost / storage_cost / network_cost / other_cost`: pool VMs are pure compute, so the split would be ~100% compute and adds no signal. Keep the four-way split on the cluster table where it matters.
- Merge key: `(instance_pool_id, workspace_id, usage_date)`.
- Register in `create_all_tables.ipynb`.

### Pool spends ETL skeleton (for reviewer clarity)

```python
pool_total = (
    cloud_cost.filter(F.col("instance_pool_id").isNotNull())
              .groupBy("instance_pool_id", "cost_incurred_date")
              .agg(F.sum("cloud_cost").alias("pool_total_cost"))
)

cluster_to_pool = (
    spark.table("system.compute.clusters")
         .filter("worker_instance_pool_id IS NOT NULL OR driver_instance_pool_id IS NOT NULL")
         .select(
             F.col("cluster_id"),
             F.coalesce("worker_instance_pool_id", "driver_instance_pool_id").alias("instance_pool_id"),
         )
         # dedup against snapshot fan-out:
         .dropDuplicates(["cluster_id", "instance_pool_id"])
)

attached = (
    cloud_cost.filter(F.col("cluster_id").isNotNull())
              .join(cluster_to_pool, "cluster_id", "inner")
              .groupBy("instance_pool_id", "cost_incurred_date")
              .agg(F.sum("cloud_cost").alias("active_cloud_cost"))
)

result = (
    pool_total.join(attached, ["instance_pool_id", "cost_incurred_date"], "left")
              .withColumn("active_cloud_cost", F.coalesce("active_cloud_cost", F.lit(0.0)))
              .withColumn("idle_cloud_cost",
                          F.greatest(F.col("pool_total_cost") - F.col("active_cloud_cost"), F.lit(0.0)))
)
```

- The `greatest(..., 0)` guard handles tag-collection lag: CE/CM may surface a `ClusterId` row before the corresponding `InstancePoolId` row catches up, briefly producing a negative residual. Log occurrences to the audit log so a persistent skew is visible.

### Job wiring

Add `Dbspend360pool_spends` task in `DBSPEND360.yaml` running after both `cloud_cost_explorer` and `Dbspend360dbu_costs`. It depends on the new `Dbspend360cluster_spends` only if the cluster-spend snapshot is needed for the attachment join; otherwise it can run in parallel with it (the join uses `system.compute.clusters` directly).

## Backend

### Pool catalog (no system table — use SDK)

- New helper in `databricks_service.py`: `list_instance_pools()` calling `self.client.instance_pools.list()`. Cache result process-wide via `self.pool_catalog_cache: Dict[str, PoolConfig] = {}` initialized in `__init__`, matching the existing `job_name_cache` pattern (do NOT introduce request-lifetime caching as a new pattern).
- Surfaced fields: `instance_pool_id`, `instance_pool_name`, `node_type_id`, `min_idle_instances`, `max_capacity`, `idle_instance_autotermination_minutes`, `preloaded_spark_versions`, `state`.
- Multi-workspace caveat: `instance_pools.list()` returns only pools the app SP can see in its home workspace. For multi-workspace deployments, pools in other workspaces will appear in `dbspend360_pool_spends` (because the ETL aggregates across workspaces) but with null catalog fields. Render "Pool name unknown" in that case.

### New service methods

- `get_pool_spends(start_date, end_date, limit, offset)` — joins `dbspend360_pool_spends` with the cached pool catalog. Sorted by `idle_cloud_cost` desc by default (the actionable metric).
- `get_pool_summary(start_date, end_date)` — total spend, total **idle waste**, count of orphan pools (pools in catalog with zero `active_cloud_cost` in window), count of pools with `idle_cloud_cost / pool_total_cost > 0.3`.
- `get_pool_breakdown(instance_pool_id, start_date, end_date)` — daily idle vs active cost and the list of clusters attached.
- `get_pool_attached_clusters(instance_pool_id)` — queries `system.compute.clusters WHERE worker_instance_pool_id = ? OR driver_instance_pool_id = ?`, with the same `QUALIFY ROW_NUMBER()` dedup as Slice 2 (snapshot fan-out).

### New routes

Path naming matches the existing singular-resource convention: `/api/cluster/{id}/...`

- `GET /api/instance-pools` (collection)
- `GET /api/instance-pools/summary` (collection aggregate)
- `GET /api/instance-pool/{pool_id}/breakdown` (per-resource)
- `GET /api/instance-pool/{pool_id}/attached-clusters` (per-resource)
- `GET /api/instance-pool/{pool_id}/analyze` (per-resource, LLM)

### LLM prompt (new) — `server/services/llm_service.py`

Locked in [§4.5 #5](02-architectural-decisions.md): mirror the structure of `CLUSTER_ANALYSIS_SYSTEM_PROMPT`. Concretely:

- New constant `POOL_ANALYSIS_SYSTEM_PROMPT` with strict rules (cite numbers, no fabrication, immutable sections).
- Classification rubric: CRITICAL ISSUES / NEEDS ATTENTION / WELL-OPTIMIZED, evaluated against `min_idle_instances`, `idle_instance_autotermination_minutes`, idle-cost share, and attached-cluster count. No absolute dollar or percent thresholds baked into the prompt body.
- Fixed sections:
  1. Overall Rating [CLASSIFICATION]
  2. Sizing Assessment (min/max idle, capacity)
  3. Idle Waste Risk (idle-cost share, idle timeout)
  4. Attachment Health (orphan check, attached cluster count)
  5. Cost Savings Opportunities (max 3, ranked by $ impact)
- Public method `analyze_instance_pool(pool_config, spend_summary, attached_clusters)`. User message is data-only (numbers, config fields, attached-cluster list); no instructions live there. Mirror the `_build_cluster_user_message` shape.
- Structured fallback `_build_pool_fallback` returning the same section headers — never expose raw exceptions.

### Endpoint verification

```bash
curl -s "http://localhost:8000/api/instance-pools?start_date=2026-04-20&end_date=2026-05-20&page=1&per_page=10" | jq
curl -s "http://localhost:8000/api/instance-pools/summary?start_date=2026-04-20&end_date=2026-05-20" | jq
curl -s "http://localhost:8000/api/instance-pool/{POOL_ID}/breakdown?start_date=2026-04-20&end_date=2026-05-20" | jq
curl -s "http://localhost:8000/api/instance-pool/{POOL_ID}/attached-clusters" | jq
curl -s "http://localhost:8000/api/instance-pool/{POOL_ID}/analyze" | jq
```

## Frontend

- `client/src/components/InstancePoolsTab.tsx` — owns `PoolSummaryCards` with the headline "Idle VM Cost" KPI, plus filters.
- `client/src/components/InstancePoolTable.tsx` — columns: pool name, node type, total cost, **idle cost**, **idle %**, min idle, idle timeout, attached cluster count. Idle % > 30% rendered with a warning chip. Orphan pools (zero attached clusters) highlighted in red.
- `client/src/components/InstancePoolDrilldownModal.tsx`:
  - Stacked bar chart: idle vs active cost per day.
  - Pool config card (from SDK).
  - "Attached clusters" mini-table linking back to the Shared Clusters tab.
  - "Analyze pool" LLM button.
- Regenerate TypeScript client.

## Acceptance criteria

Reconciliation is split because DBU and cloud-cost live in different source systems with different latencies.

- **DBU reconciliation (±1%)** vs `system.billing.usage`:

  ```sql
  SELECT
    usage_metadata.instance_pool_id AS instance_pool_id,
    usage_date,
    SUM(usage_quantity * lp.pricing['default']::DOUBLE) AS dbu_cost
  FROM system.billing.usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.usage_start_time >= lp.price_start_time
    AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
  WHERE usage_metadata.instance_pool_id IS NOT NULL
    AND usage_date BETWEEN '<start>' AND '<end>'
  GROUP BY 1, 2;
  ```

  Compare against `SUM(databricks_cost)` from `dbspend360_pool_spends`. Expect near-zero rows on non-premium editions; that itself is the signal.

- **Cloud-cost reconciliation (±2%)** vs the InstancePoolId-tagged CE / Azure-CM result. Re-run the same Slice 0 step (3) query for the same date window and compare against `SUM(pool_total_cost)` from `dbspend360_pool_spends`. Tolerance is wider than the DBU side because CE/CM data lags ~24h.
- **Idle subtraction sanity**: `idle_cloud_cost >= 0` for every row (the `greatest(..., 0)` floor must not fire more than 1% of the time over a 30-day window; if it does, log a quality warning in the audit log).
- At least one orphan pool (or zero, verified explicitly) is correctly identified — orphan = catalog pool with `active_cloud_cost = 0` across the window.
- Idle cost is non-zero for at least one pool with `min_idle_instances > 0` (sanity check that the subtraction works end-to-end).
- LLM recommendation cites the pool's actual config numbers (no hallucinated values).

## Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Pool VMs not tagged with `DatabricksInstancePoolId` | Idle cost invisible; rolls into untagged-`other_cost` instead | Verified in Slice 0 step 3; downgrade Slice 3 to DBU-only attribution per the decision gate if confirmed |
| `system.billing.usage` grant missing for non-job rows | API returns empty | Pre-flight check in `/api/test-connection`; update README grant section (see [`06-cross-cutting.md`](06-cross-cutting.md)) |
| `instance_pools.list` permission missing for app SP | Pool catalog empty | Fall back to listing pool_ids from `system.compute.clusters` and showing "pool name unknown" |
| Negative `idle_cloud_cost` from CE/CM tag-lag | Misleading totals | Floor at 0 via `greatest(...)`; alert via audit log if frequency > 1% |
| Multi-workspace pools missing from catalog | Some pool rows show "pool name unknown" | Documented; secondary callout in tab footer |
| `system.compute.clusters` lacks `instance_pool_id` column | Cannot compute attachment for subtraction | Detected in Slice 0 step 5; if absent, fall back to `pool_total_cost` only and hide the idle vs active split |
| CE / Azure CM quota exhaustion from doubling tag queries | Slower ETL runs, occasional throttling | Existing retry/backoff handles 429 / LimitExceeded; document the ~2x quota cost in deployment docs |

## Effort

~4–6 days

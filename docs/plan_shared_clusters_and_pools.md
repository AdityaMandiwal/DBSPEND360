# Plan — Shared Clusters & Instance Pools Tabs

Branch: `feat/shared-clusters-and-pools-tabs`

## 1. Goal

Extend DBSPEND360 beyond job-cluster spend by adding two new top-level tabs to the dashboard:

1. **Shared Clusters** — visibility into All-Purpose / interactive clusters (`cluster_source IN ('UI','API')`), their owners, configuration, and total cost (DBU + cloud VM).
2. **Instance Pools** — visibility into Databricks instance pools, including the headline metric **idle VM cost** (pool VMs incurring cloud spend with no cluster attached).

Today the data pipeline filters everything except `cluster_source = 'JOB'` rows with non-null `job_run_id`, so neither dimension is represented in `dbspend360_total_job_spends`. This plan covers the data, backend, and frontend work end-to-end.

## 2. Non-goals

- GCP support for either tab (the GCP cost-explorer notebook is still a stub).
- Per-user chargeback on shared clusters from `system.access.audit` (deferred — large, separate effort).
- Real-time pool utilization (we use daily granularity, same as the rest of the app).
- Modifying the existing Jobs tab behaviour or schema semantics.

## 3. Sequencing & branching strategy

Single feature branch `feat/shared-clusters-and-pools-tabs` off `main`. Internally we ship in three reviewable PR-sized chunks (squash-merge each):

| Order | Slice | Why first |
|---|---|---|
| 0 | Verification spike (read-only queries against workspace) | Confirms `usage_metadata.instance_pool_id` is populated and pool VMs carry `DatabricksInstancePoolId` cloud tags. De-risks Slice 2. |
| 1 | UI tabification refactor (no behaviour change) | Lowest risk, unblocks Slices 2 and 3 to be developed in parallel. |
| 2 | Shared Clusters tab (data + API + UI) | High value, low risk — cloud-cost join already works for `cluster_source IN ('UI','API')`. |
| 3 | Instance Pools tab (ETL extension + API + UI) | Highest risk because it requires extending the AWS / Azure cloud-cost ETL to capture the `DatabricksInstancePoolId` tag. |

## 4. Slice 0 — Verification spike (½ day, no code merged)

Run these read-only queries against the customer workspace and capture results in this doc before starting Slice 2:

1. **Are interactive cluster rows present in billing?**
   ```sql
   SELECT cluster_source, COUNT(*)
   FROM system.compute.clusters
   WHERE create_time >= current_date() - INTERVAL 30 DAYS
   GROUP BY cluster_source;
   ```
2. **Is `instance_pool_id` populated in DBU usage?**
   ```sql
   SELECT usage_metadata.instance_pool_id, SUM(usage_quantity)
   FROM system.billing.usage
   WHERE usage_date >= current_date() - INTERVAL 30 DAYS
     AND usage_metadata.instance_pool_id IS NOT NULL
   GROUP BY 1
   ORDER BY 2 DESC
   LIMIT 20;
   ```
3. **Do pool VMs carry the `DatabricksInstancePoolId` tag in cloud cost?** Use AWS CUR / Azure Cost Management to confirm a sample of pool VMs has the tag without a `ClusterId` tag (this is the idle-pool case).
4. **Can the app SP list pools?**
   ```bash
   databricks instance-pools list
   ```

**Decision gate:** If (2) returns no rows or (3) shows tags are missing in the customer's setup, downgrade the Instance Pools tab scope to "DBU-only attribution" and document the gap.

## 5. Slice 1 — UI tabification (½–1 day)

### Frontend changes
- `client/src/components/Dashboard.tsx`: wrap existing content in a shadcn `Tabs` component with three tabs: **Jobs** (current view), **Shared Clusters** (placeholder), **Instance Pools** (placeholder).
- Lift shared state (`dateRange`, eventually filters) into a small `DashboardContext` co-located with `Dashboard.tsx`. `CloudPlatformContext` stays as-is.
- Add `npx shadcn@latest add tabs` if the component isn't already in `client/src/components/ui`.
- New components scaffold (placeholders, will be filled in by later slices):
  - `client/src/components/SharedClustersTab.tsx`
  - `client/src/components/InstancePoolsTab.tsx`
- Move the current JSX (SummaryCards + FilterControls + GroupedJobTable + JobBreakdownModal) into `client/src/components/JobsTab.tsx`.

### Acceptance criteria
- All existing functionality works identically; no regression in Jobs tab.
- Tabs render with shadcn styling; placeholder tabs show a friendly "Coming soon" card.
- No backend changes in this slice.

### Effort: ~0.5–1 day

## 6. Slice 2 — Shared Clusters tab (3–4 days)

### Data layer

**Decision: add a sibling fact table rather than relaxing the existing one.** Keeps job-table semantics clean; idempotent migration path; smaller blast radius on existing dashboards / consumers.

#### New DDL — `jobs/ddls/dbspend360_cluster_spends.ipynb`
```sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_cluster_spends (
  cluster_id      STRING,
  cluster_source  STRING,        -- 'UI' or 'API'
  usage_date      DATE,
  cloud_cost      DOUBLE,
  compute_cost    DOUBLE,
  storage_cost    DOUBLE,
  network_cost    DOUBLE,
  other_cost      DOUBLE,
  databricks_cost DOUBLE,
  currency        STRING,
  total_cost      DOUBLE,
  created_at      TIMESTAMP,
  updated_at      TIMESTAMP
)
CLUSTER BY AUTO;
```
- Register it in `jobs/ddls/create_all_tables.ipynb` so the existing orchestrator handles creation.

#### ETL — new notebook `jobs/notebooks/dbspend360_cluster_spends_app.ipynb`
Mirrors the structure of `dbspend360_dbu_cost_app.ipynb` but with two filter changes:
- `system.compute.clusters` filter: `cluster_source IN ('UI', 'API')` instead of `'JOB'`.
- `system.billing.usage` filter: `usage_metadata.job_run_id IS NULL AND usage_metadata.cluster_id IS NOT NULL`.
- Cloud-cost join: unchanged — keys on `cluster_id` from `dbspend360_cloud_cost_explorer` (the `ClusterId` tag already covers interactive clusters).
- Reuses `utils_common`, audit log, error log, and the overlap-days idempotency pattern.

#### Job wiring — `jobs/resource_templates/DBSPEND360.yaml`
Add a task `Dbspend360cluster_spends` that runs after `cloud_cost_explorer` and `Dbspend360dbu_costs`, in parallel with `databricks_job_spends`. No upstream dependency on `databricks_job_spends_app`.

### Backend

#### `server/models/job_spend.py` (or split into `cluster_spend.py` if it grows)
New Pydantic models:
- `SharedClusterSpend` — `cluster_id`, `cluster_name`, `owned_by`, `cluster_source`, `cloud_cost`, `databricks_cost`, `total_cost`, breakdown fields, `data_security_mode`, `auto_termination_minutes`, `dbr_version`.
- `SharedClusterSummary` — totals, top-N owners, idle-risk count (clusters with NULL or > X `auto_termination_minutes`).
- `PaginatedSharedClusters`.
- `SharedClusterDailyPoint` — for time-series chart.

#### `server/services/databricks_service.py`
Add (no changes to existing methods):
- `get_shared_cluster_spends(start_date, end_date, owner_filter, limit, offset)` — paginated list ordered by total cost desc, left-joining `system.compute.clusters` for owner / config fields.
- `get_shared_cluster_summary(start_date, end_date)` — KPIs for the summary cards (total spend, top owner, % of spend on clusters with no auto-termination).
- `get_shared_cluster_daily_trend(cluster_id, start_date, end_date)`.
- `get_shared_cluster_breakdown(cluster_id, start_date, end_date)` — same shape as `get_job_cost_breakdown` so the existing pie-chart component is reusable.
- Reuse `get_cluster_details` and `analyze_cluster_configuration` as-is for drill-down.

#### `server/routers/dashboard.py`
New endpoints under existing `/api` prefix:
- `GET /api/shared-clusters` (paginated list)
- `GET /api/shared-clusters/summary`
- `GET /api/cluster/{cluster_id}/daily-trend`
- `GET /api/cluster/{cluster_id}/spend-breakdown`

(`/api/cluster/{cluster_id}/details` and `/analyze` already exist and work without changes.)

#### Mandatory endpoint verification
Per `CLAUDE.md`, after each new endpoint:
```bash
curl -s "http://localhost:8000/api/shared-clusters?start_date=2026-04-20&end_date=2026-05-20&page=1&per_page=10" | jq
curl -s "http://localhost:8000/api/shared-clusters/summary?start_date=2026-04-20&end_date=2026-05-20" | jq
```

### Frontend

- `client/src/components/SharedClustersTab.tsx` — owns its own `SummaryCards`, `FilterControls` (date range + owner search), and table.
- `client/src/components/SharedClusterTable.tsx` — columns: cluster name, owner, source, total cost, DBU vs cloud %, auto-termination, DBR, last seen. Row click opens a drill-down modal.
- `client/src/components/SharedClusterDrilldownModal.tsx` — reuses `JobBreakdownModal` patterns: pie chart of cost split, daily trend line chart, cluster config card, "Analyze configuration" LLM button (calls existing `/api/cluster/{id}/analyze`).
- Regenerate the TypeScript client: `uv run python scripts/make_fastapi_client.py`.

### Acceptance criteria
- Tab shows All-Purpose clusters with non-zero spend in the selected window, sorted by total cost desc.
- Cluster row drill-down shows DBU vs cloud split that reconciles within ±1% to a manual `system.billing.usage` + `dbspend360_cloud_cost_explorer` cross-check on at least one cluster.
- "Idle risk" KPI (clusters without auto-termination) renders correctly and matches a manual query.
- No regression in Jobs tab.

### Effort: ~3–4 days

## 7. Slice 3 — Instance Pools tab (4–6 days)

### Data layer

This is the slice that requires touching the cloud-cost ETL.

#### Cloud-cost ETL changes (the hard part)
- `dbspend360_cloud_cost_explorer` table: add a nullable column `instance_pool_id STRING`. Backfill with `NULL` for historical rows.
- `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`:
  - Extend the tag-parsing logic (currently around line 324: `cluster_id = raw_tag.split("$")[-1] ...`) to also extract `DatabricksInstancePoolId` from resource tags.
  - Emit rows with `cluster_id = NULL, instance_pool_id = <pool>` when only the pool tag is present (idle pool VM case).
  - Emit rows with both populated when both tags are present (a transient case during VM-to-cluster attachment).
- `jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`: equivalent extension. Azure tag name is also `DatabricksInstancePoolId`.
- `gcp_cloud_cost_explorer_app.ipynb`: leave as the existing `NotImplementedError` stub.

#### DBU ETL extension
- `jobs/notebooks/dbspend360_dbu_cost_app.ipynb`: this notebook is currently a single-purpose JOB extractor. We add a parallel extraction path that pulls rows where `usage_metadata.instance_pool_id IS NOT NULL` (regardless of `job_run_id`) and lands them into a new pool-spend table. To keep the file focused, prefer creating a new notebook `jobs/notebooks/dbspend360_pool_spends_app.ipynb` rather than overloading the existing one.

#### New DDL — `jobs/ddls/dbspend360_pool_spends.ipynb`
```sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_pool_spends (
  instance_pool_id   STRING,
  usage_date         DATE,
  -- attribution split:
  idle_cloud_cost    DOUBLE,   -- VM cost where no cluster_id was attached
  active_cloud_cost  DOUBLE,   -- VM cost where a cluster_id was attached
  databricks_cost    DOUBLE,   -- DBU attributed by usage_metadata.instance_pool_id
  compute_cost       DOUBLE,
  storage_cost       DOUBLE,
  network_cost       DOUBLE,
  other_cost         DOUBLE,
  currency           STRING,
  total_cost         DOUBLE,
  created_at         TIMESTAMP,
  updated_at         TIMESTAMP
)
CLUSTER BY AUTO;
```
- Register in `create_all_tables.ipynb`.

#### Job wiring
Add `Dbspend360pool_spends` task in `DBSPEND360.yaml` running after both cost-explorer and DBU tasks.

### Backend

#### Pool catalog (no system table — use SDK)
- New helper in `databricks_service.py`: `list_instance_pools()` calling `self.client.instance_pools.list()`. Cache result for the request lifetime (in-process dict keyed by pool_id) similar to `job_name_cache`.
- Surfaced fields: `instance_pool_id`, `instance_pool_name`, `node_type_id`, `min_idle_instances`, `max_capacity`, `idle_instance_autotermination_minutes`, `preloaded_spark_versions`, `state`.

#### New service methods
- `get_pool_spends(start_date, end_date, limit, offset)` — joins `dbspend360_pool_spends` with cached pool catalog. Sorted by `idle_cloud_cost` desc by default (because that's the actionable metric).
- `get_pool_summary(start_date, end_date)` — total spend, total **idle waste**, count of orphan pools (pools in catalog with zero `active_cloud_cost` in window), count of pools with idle waste > $X.
- `get_pool_breakdown(instance_pool_id, start_date, end_date)` — daily idle vs active cost and the list of clusters attached.
- `get_pool_attached_clusters(instance_pool_id)` — queries `system.compute.clusters WHERE instance_pool_id = ? OR driver_instance_pool_id = ?`.

#### New routes
- `GET /api/instance-pools`
- `GET /api/instance-pools/summary`
- `GET /api/instance-pool/{pool_id}/breakdown`
- `GET /api/instance-pool/{pool_id}/attached-clusters`
- `GET /api/instance-pool/{pool_id}/analyze` — new LLM prompt focused on pool sizing.

#### LLM prompt (new) — `server/services/llm_service.py`
Add `analyze_instance_pool` taking pool config + spend split + utilization. Prompt focuses on three levers:
1. Reduce `min_idle_instances` if `idle_cloud_cost / total_cloud_cost > 0.3`.
2. Shorten `idle_instance_autotermination_minutes` if median active window is shorter than the timeout.
3. Recommend deleting orphan pools (zero attached clusters in window).

#### Endpoint verification
```bash
curl -s "http://localhost:8000/api/instance-pools?start_date=2026-04-20&end_date=2026-05-20&page=1&per_page=10" | jq
curl -s "http://localhost:8000/api/instance-pools/summary?start_date=2026-04-20&end_date=2026-05-20" | jq
curl -s "http://localhost:8000/api/instance-pool/{POOL_ID}/breakdown?start_date=2026-04-20&end_date=2026-05-20" | jq
```

### Frontend

- `client/src/components/InstancePoolsTab.tsx` — owns `PoolSummaryCards` with the headline "Idle VM Cost" KPI, plus filters.
- `client/src/components/InstancePoolTable.tsx` — columns: pool name, node type, total cost, **idle cost**, **idle %**, min idle, idle timeout, attached cluster count. Idle % > 30% rendered with a warning chip. Orphan pools (zero attached clusters) highlighted in red.
- `client/src/components/InstancePoolDrilldownModal.tsx`:
  - Stacked bar chart: idle vs active cost per day.
  - Pool config card (from SDK).
  - "Attached clusters" mini-table linking back to the Shared Clusters tab.
  - "Analyze pool" LLM button.
- Regenerate TypeScript client.

### Acceptance criteria
- Total pool cost across all pools reconciles within ±2% to a manual `system.billing.usage` query filtered on `usage_metadata.instance_pool_id`.
- At least one orphan pool (or zero, verified explicitly) is correctly identified.
- Idle cost is non-zero for at least one pool with `min_idle_instances > 0` (sanity).
- LLM recommendation cites the pool's actual config numbers (no hallucinated values).

### Risk register
| Risk | Impact | Mitigation |
|---|---|---|
| Pool VMs not tagged with `DatabricksInstancePoolId` | Idle cost shows as `other_cost` instead of pool cost | Verified in Slice 0; document gap if confirmed |
| `system.billing.usage` grant missing for non-job rows | API returns empty | Pre-flight check in `/api/test-connection`; update README grant section |
| `instance_pools.list` permission missing for app SP | Pool catalog empty | Fall back to listing pool_ids from `system.compute.clusters` and showing "pool name unknown" |
| Cost double-counting between cluster_id and instance_pool_id rows | Inflated totals | ETL must classify each row exclusively: a VM line item with both tags counts as `active_cloud_cost` only |

### Effort: ~4–6 days

## 8. Cross-cutting work

### Permissions / docs
- Update README §"Required Grants for the App Service Principal":
  - Add `SELECT ON system.billing.usage` (required for both new tabs).
  - Add note about `CAN VIEW` on each instance pool for the SDK call.
- Update `docs/databricks_apis/databricks_sdk.md` with the `instance_pools.list/get` usage pattern.

### Config
- No new config keys expected. Both new tables resolve under the same `catalog.schema` as `dbspend360_total_job_spends`.

### Testing
- New tests under `claude_scripts/` to:
  - Verify endpoint shapes for shared-cluster and pool endpoints.
  - Reconcile pool total cost against a direct `system.billing.usage` query.
- After deploy, follow the post-deployment monitoring workflow from `CLAUDE.md` (60-second `dba_logz.py` watch + `dba_client.py` smoke tests on the new endpoints).

### Format / lint
- Run `./fix.sh` before each slice's commit.
- Run `ReadLints` on touched files.

## 9. Out-of-scope follow-ups (capture for backlog)

- Per-user attribution on shared mode clusters via `system.access.audit.commandSubmit`.
- Continuous pool utilization (hourly granularity using `system.compute.warehouse_events` if available).
- GCP support for both tabs (blocked on the existing `gcp_cloud_cost_explorer_app` implementation).
- SQL warehouse spend tab (logical next addition — `usage_metadata.warehouse_id`).

## 10. Definition of done

- All three slices merged into `feat/shared-clusters-and-pools-tabs`.
- README updated with new tabs, new grants, screenshots in `release/readme_images/`.
- Deployed to Databricks Apps and `dba_logz.py` shows clean `Uvicorn running` with no exceptions.
- Reconciliation queries documented in this file (Slice 0 section) re-run against production data, results pasted into a final "Verification results" section appended at the bottom of this doc before PR review.

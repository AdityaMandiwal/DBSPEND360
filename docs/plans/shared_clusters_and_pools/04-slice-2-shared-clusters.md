# Slice 2 — Shared Clusters tab (3–4 days)

[← back to plan index](README.md)

## Data layer

**Decision: add a sibling fact table rather than relaxing the existing one.** Keeps job-table semantics clean; idempotent migration path; smaller blast radius on existing dashboards / consumers.

### New DDL — `jobs/ddls/dbspend360_cluster_spends.ipynb`

```sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_cluster_spends (
  cluster_id          STRING,
  workspace_id        STRING,
  cluster_source      STRING,        -- 'UI' or 'API'
  cluster_name        STRING,        -- snapshotted at ETL time
  owned_by            STRING,        -- snapshotted at ETL time
  data_security_mode  STRING,        -- snapshotted at ETL time
  usage_date          DATE,
  cloud_cost          DOUBLE,
  compute_cost        DOUBLE,
  storage_cost        DOUBLE,
  network_cost        DOUBLE,
  other_cost          DOUBLE,
  databricks_cost     DOUBLE,
  currency            STRING,
  total_cost          DOUBLE,
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP
)
CLUSTER BY AUTO;
```

- `workspace_id` matches the pattern in `dbspend360_dbu_cost`.
- `cluster_name`, `owned_by`, `data_security_mode` are denormalized at ETL time so historical rows survive later config changes on `system.compute.clusters` (e.g. ownership transfer).
- Merge key: `(cluster_id, workspace_id, usage_date)`. No `job_id` / `run_id` because shared cluster DBU rows have both NULL.
- Register it in `jobs/ddls/create_all_tables.ipynb` so the existing orchestrator handles creation.

### ETL — new notebook `jobs/notebooks/dbspend360_cluster_spends_app.ipynb`

Mirrors the structure of `dbspend360_dbu_cost_app.ipynb` but with the following changes:

- `system.compute.clusters` filter: `cluster_source IN ('UI', 'API')` instead of `'JOB'`.
- Because `system.compute.clusters` is a slowly-changing snapshot (one row per config change), de-dupe before the join: `QUALIFY ROW_NUMBER() OVER (PARTITION BY cluster_id ORDER BY change_time DESC) = 1`. Joining the raw table fans out costs by N history rows.
- `system.billing.usage` filter: `usage_metadata.cluster_id IS NOT NULL AND usage_metadata.job_run_id IS NULL`.
- Cloud-cost join: unchanged — keys on `cluster_id` from `dbspend360_cloud_cost_explorer` (the `ClusterId` tag already covers interactive clusters).
- Snapshot `cluster_name`, `owned_by`, `data_security_mode` into the fact row at write time.
- Respect the `workspace_ids` widget for multi-workspace filtering (same code path as the DBU notebook).
- Reuses `utils_common`, audit log, error log, and the overlap-days idempotency pattern.

### Job wiring — `jobs/resource_templates/DBSPEND360.yaml`

Add a task `Dbspend360cluster_spends` that runs after `cloud_cost_explorer` and `Dbspend360dbu_costs`, in parallel with `databricks_job_spends`. No upstream dependency on `databricks_job_spends_app`.

## Backend

### `server/models/job_spend.py` (or split into `cluster_spend.py` if it grows)

New Pydantic models:

- `SharedClusterSpend` — `cluster_id`, `cluster_name`, `owned_by`, `cluster_source`, `cloud_cost`, `databricks_cost`, `total_cost`, breakdown fields, `data_security_mode`, `auto_termination_minutes`, `dbr_version`.
- `SharedClusterSummary` — totals, top-N owners, idle-risk count (clusters with NULL or > X `auto_termination_minutes`).
- `PaginatedSharedClusters`.
- `SharedClusterDailyPoint` — for time-series chart.

### `server/services/databricks_service.py`

Add (no changes to existing methods):

- `get_shared_cluster_spends(start_date, end_date, owner_filter, limit, offset)` — paginated list ordered by total cost desc. Owner / security-mode / cluster-name come from the denormalized fact-table columns (snapshotted at ETL time), not a live join, so this method does not need `system.compute.clusters`.
- `get_shared_cluster_summary(start_date, end_date)` — KPIs for the summary cards (total spend, top owner, % of spend on clusters with no auto-termination).
- `get_shared_cluster_daily_trend(cluster_id, start_date, end_date)`.
- `get_shared_cluster_breakdown(cluster_id, start_date, end_date)` — same shape as `get_job_cost_breakdown` so the existing pie-chart component is reusable.
- Reuse `get_cluster_details` and `get_cluster_cost_summary` for drill-down. The `/api/cluster/{id}/analyze` route (backed by `llm_service.analyze_cluster_configuration`) already works and needs no changes.

### `server/routers/dashboard.py`

New endpoints under existing `/api` prefix:

- `GET /api/shared-clusters` (paginated list)
- `GET /api/shared-clusters/summary`
- `GET /api/cluster/{cluster_id}/daily-trend`
- `GET /api/cluster/{cluster_id}/spend-breakdown`

(`/api/cluster/{cluster_id}/details` and `/analyze` already exist and work without changes.)

### Mandatory endpoint verification

Per `CLAUDE.md`, after each new endpoint:

```bash
curl -s "http://localhost:8000/api/shared-clusters?start_date=2026-04-20&end_date=2026-05-20&page=1&per_page=10" | jq
curl -s "http://localhost:8000/api/shared-clusters/summary?start_date=2026-04-20&end_date=2026-05-20" | jq
```

## Frontend

- `client/src/components/SharedClustersTab.tsx` — owns its own `SummaryCards`, `FilterControls` (date range + owner search), and table.
- `client/src/components/SharedClusterTable.tsx` — columns: cluster name, owner, source, total cost, DBU vs cloud %, auto-termination, DBR, last seen. Row click opens a drill-down modal.
- `client/src/components/SharedClusterDrilldownModal.tsx` — reuses `JobBreakdownModal` patterns: pie chart of cost split, daily trend line chart, cluster config card, "Analyze configuration" LLM button (calls existing `/api/cluster/{id}/analyze`).
- Regenerate the TypeScript client: `uv run python scripts/make_fastapi_client.py`.

## Acceptance criteria

- Tab shows All-Purpose clusters with non-zero spend in the selected window, sorted by total cost desc.
- Per-cluster reconciliation runs cleanly using the templates below for at least one sampled cluster.
- DBU reconciliation (±1%) vs `system.billing.usage`:

  ```sql
  SELECT
    usage_metadata.cluster_id AS cluster_id,
    usage_date,
    SUM(usage_quantity * lp.pricing['default']::DOUBLE) AS dbu_cost
  FROM system.billing.usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.usage_start_time >= lp.price_start_time
    AND (u.usage_start_time < lp.price_end_time OR lp.price_end_time IS NULL)
  WHERE usage_metadata.cluster_id = '<sample_cluster_id>'
    AND usage_metadata.job_run_id IS NULL
    AND usage_date BETWEEN '<start>' AND '<end>'
  GROUP BY 1, 2
  ORDER BY 2;
  ```

- Cloud-cost reconciliation (±2%) vs `dbspend360_cloud_cost_explorer`:

  ```sql
  SELECT cost_incurred_date AS usage_date, SUM(cloud_cost) AS cloud_cost
  FROM ${catalog}.${schema}.dbspend360_cloud_cost_explorer
  WHERE cluster_id = '<sample_cluster_id>'
    AND cost_incurred_date BETWEEN '<start>' AND '<end>'
  GROUP BY 1
  ORDER BY 1;
  ```

- "Idle risk" KPI (clusters without auto-termination) matches `SELECT COUNT(*) FROM system.compute.clusters WHERE cluster_source IN ('UI','API') AND auto_termination_minutes IS NULL` (after the same dedup as the ETL).
- No regression in Jobs tab.

## Effort

~3–4 days

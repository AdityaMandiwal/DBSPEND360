# Plan — Add an "All-Purpose Clusters" tab alongside today's "Job Clusters" view

Branch (proposed): `feat/all-purpose-clusters-tab`

## 1. Goal

Today the entire DBSpend360 app shows **only job clusters**: the pipeline filters
`system.compute.clusters` to `cluster_source = 'JOB'` and `system.billing.usage`
to rows where `usage_metadata.job_run_id IS NOT NULL`, the backend exposes
`job_id` / `run_id`-keyed endpoints, and the React dashboard is built around the
`GroupedJob → JobRun` model.

Add a parallel **All-Purpose Clusters** experience as a second top-level tab,
with the same depth (summary cards, drill-down table, per-row analyze, cost
breakdown modal, cluster details / LLM analysis), wired to a new sibling data
pipeline so the two flows are independent and the existing flow stays untouched.

The All-Purpose tab itself has two sub-tabs:

- **By Cluster** — one row per all-purpose cluster, expandable to per-day rows. Mirrors today's "Job → Runs" drill-down shape.
- **By User** — one row per cluster owner (`system.compute.clusters.owned_by`), expandable to per-cluster rows. Powers chargeback / "who is spending".

After this change the navigation looks like:

```
Header (DBSpend360 + ThemeToggle)
├─ Tab: Job Clusters       (today's Dashboard contents, untouched)
└─ Tab: All-Purpose Clusters
   ├─ Sub-tab: By Cluster   (new)
   └─ Sub-tab: By User      (new)
```

## 1.5. Confirmed decisions

The architectural forks below are **locked in**. Tradeoff tables and rejected
alternatives are retained in §3 as a historical record, but no further questions
on these need to be answered before implementation.

| Fork | Decision | Detail in |
|---|---|---|
| Cluster source filter | `cluster_source IN ('UI', 'API')` only — excludes `PIPELINE`, `MODELS`, `SQL`, `JOB` | §3.1 |
| User attribution field | `system.compute.clusters.owned_by` (cluster owner). `data_security_mode` surfaced so the UI distinguishes exact attribution (`SINGLE_USER` / Dedicated) from approximate (`USER_ISOLATION` / Shared). **`identity_metadata.run_as` rejected** — Databricks system tables docs confirm it is NULL for classic all-purpose compute. | §3.2 |
| Cloud cost apportionment | **None in v1.** Owner-attribution means each `(cluster_id, usage_date)` resolves to a single `user_id`, so cluster cloud cost flows 1:1 to that user. DBU-proportional apportionment formula preserved in §3.3 for the v2 path. | §3.3 |
| Pipeline scope | New sibling notebooks (`dbspend360_all_purpose_dbu_cost_app` + `all_purpose_spends_app`); existing job-cluster pipeline untouched | §4.1 |
| PR slicing | Single PR on `feat/all-purpose-clusters-tab`, broken into 11 sequential checkpoints (each self-contained, see §8) | §7, §8 |

## 2. Non-goals

- **No changes to existing job-cluster behavior.** The current `dashboard_router`
  endpoints, `DatabricksService` methods that read `dbspend360_total_job_spends`,
  and every existing React component keep their current contract. The
  `Dashboard.tsx` body is extracted verbatim into `JobClustersDashboard.tsx`.
- **No changes to `dbspend360_cloud_cost_explorer`.** It's already
  cluster-source-agnostic (just aggregates cloud VM cost by `cluster_id`) and
  is reused as-is by both pipelines.
- **No changes to existing DDL tables.** All-purpose data lands in two new
  Delta tables. No backfill, no migration of `dbspend360_total_job_spends`.
- **No shared "all clusters" view.** The two tabs stay strictly disjoint —
  job-cluster rows never appear in the All-Purpose tab and vice versa.
- **No LLM endpoint duplication.** `/api/cluster/{id}/details` and
  `/api/cluster/{id}/analyze` are already cluster-source-agnostic (they read
  from `system.compute.clusters` and call `get_cluster_cost_summary`, which
  we'll generalize via a `cluster_kind` parameter — see §4.2). All-purpose
  drill-downs reuse them.
- **No alerts / budgets / scheduled reports** for all-purpose clusters in this
  PR. Captured as follow-up in §13.

## 3. Key data-model decisions

Three design forks govern how the all-purpose tables are shaped. Each is the
kind of thing that's expensive to reverse after data lands in the table, so
the decisions are recorded with their tradeoffs even though all three are now
confirmed (see §1.5).

### 3.1 What counts as an "all-purpose cluster"?

Today's job-cluster filter is `cluster_source = 'JOB'`. The natural inverse is
**not** simply `cluster_source != 'JOB'` because `system.compute.clusters`
also exposes other source values (`PIPELINE`, `MODELS`, `SQL`, etc.) which
have their own billing model and don't belong in either tab.

**Decision (confirmed): filter to `cluster_source IN ('UI', 'API')` explicitly.**

| `cluster_source` | Meaning | This tab? |
|---|---|---|
| `JOB` | Ephemeral job cluster | No — already in the Job Clusters tab |
| `UI` | Created interactively via the workspace UI | **Yes** |
| `API` | Created via the Clusters REST API or Terraform | **Yes** |
| `PIPELINE` | DLT/Lakeflow pipeline compute | No |
| `MODELS` | Model serving compute | No |
| `SQL` | SQL warehouse (different billing path entirely) | No |

The pipeline keeps a `usage_metadata.job_run_id IS NULL` filter as defense in
depth, but it is **functionally redundant given the cluster-source filter**:
per the [`system.billing.usage` reference](https://docs.databricks.com/en/admin/system-tables/billing.html),
`job_run_id` does not populate for jobs run on all-purpose compute, so a
job-on-interactive-cluster usage row will have `cluster_source IN ('UI','API')`
**and** `job_run_id IS NULL` already. (Note: that row also does not appear in
today's Job Clusters tab, because that tab filters `cluster_source = 'JOB'`.
An earlier draft of this plan claimed such usage "stays in the Job Clusters
tab where it already appears"; that was incorrect.)

Rejected alternatives (for the record): a permissive `cluster_source != 'JOB'`
would have mixed PIPELINE/MODELS/SQL billing models into the same tab; an
explicit allow-list keeps each compute type's billing semantics intact.

### 3.2 Per-user attribution — what is "user"?

**Decision (confirmed): attribute by `system.compute.clusters.owned_by`**, the
principal that owns the cluster (defaults to creator, can be re-assigned via
the Clusters API). Surface `data_security_mode` as a sibling column so the UI
can mark which attributions are exact vs approximate.

**Why not `identity_metadata.run_as` (the original choice in this plan).** The
`system.billing.usage` schema reference is unambiguous: `identity_metadata.run_as`
is populated only for Jobs compute, Serverless compute for jobs/notebooks,
Lakeflow Declarative Pipelines, Foundation Model Fine-tuning, Predictive
Optimization, and Data Quality Monitoring. Classic all-purpose compute
(`cluster_source IN ('UI','API')`) is **not** in this list, so `run_as` is
NULL on essentially every row this pipeline picks up. The earlier "NULL →
`__system__`" bucket would have caught ~100% of rows and collapsed the
By-User tab to a single line. This is a hard product blocker, not a tradeoff.

**Attribution-quality table** (rendered in the UI as a badge next to the owner):

| `data_security_mode` | Common name | Attribution quality | UI badge |
|---|---|---|---|
| `SINGLE_USER` | Dedicated | **Exact** — only the owner runs on this cluster | "Dedicated" |
| `USER_ISOLATION` | Standard / Shared | **Approximate** — multiple users on a shared cluster all roll up to the owner | "Shared" |
| `LEGACY_PASSTHROUGH` / `LEGACY_SINGLE_USER` / `LEGACY_TABLE_ACL` / `NONE` | Legacy access modes | Approximate | "Legacy" |
| `NULL` (system-created, some pipelines) | — | Approximate | "Unknown" |

Edge case: when `owned_by` is NULL on the SCD row (a cluster that exists in
billing but whose `system.compute.clusters` snapshot row is missing —
typically deleted before October 2023, see the docs' "known limitations"),
`user_id` is set to the literal `__unknown__` so the row stays visible and
reconcilable rather than being dropped.

Rejected alternatives:

- `identity_metadata.run_as` — NULL for classic all-purpose compute. Hard
  blocker; see above.
- Custom-tag-based attribution via `system.billing.usage.custom_tags` — only
  works in workspaces that enforce a per-user tag policy on cluster creation
  (most don't). Captured as v2 in §13.
- `system.access.audit` join (per-command user attribution) — accurate but
  would need its own pre-aggregation pipeline; too heavy for v1. Captured as
  v2 in §13.

### 3.3 Cloud cost apportionment

**Decision (confirmed): no apportionment in v1.** Under §3.2's owner
attribution, every `(cluster_id, usage_date)` resolves to exactly one
`user_id` (the cluster owner), so the cluster's cloud cost flows 1:1 to that
user. No window functions, no DBU-share math, no `__unattributed__` synthetic
row needed in v1.

The data table is still keyed `(cluster_id, user_id, usage_date)` for
**forward compatibility** — when §13's tag-based or audit-log path lands,
multiple `user_id` rows per `(cluster_id, usage_date)` become legal and
DBU-proportional apportionment of cloud cost is reintroduced. The formula and
rejected alternatives below are preserved for that v2 work.

**Apportionment formula (deferred to v2)**:

```
user_dbu_share = user_dbu_on_day / SUM(user_dbu_on_day) OVER (PARTITION BY cluster_id, usage_date)
user_cloud_cost = cluster_cloud_cost_on_day * user_dbu_share
```

Tradeoffs that were considered for v1 and rejected once owner attribution was
adopted:

| Option | Verdict | Why |
|---|---|---|
| Don't apportion — keep cloud cost per-cluster only | **Adopted as v1 default** under owner attribution: each cluster has one owner per day, so 1:1 flow is correct without any split. |
| Equal split across users-on-cluster-on-day | Rejected | Misleading: a user who attached for 5 minutes would be charged the same as a user who ran a 10-hour notebook. Re-evaluated only if v2 lands. |
| Tag-based attribution from `custom_tags` | Deferred to v2 — see §13 | Requires workspace tag-policy adoption (>90% coverage); not a baseline assumption. |
| **DBU-proportional apportionment** (formula above) | Deferred to v2 | Fair when multiple users genuinely share a cluster, but requires a per-user signal that v1 doesn't have. |

**Reconciliation invariant (v1).** Trivial under owner attribution: for every
`(cluster_id, usage_date)` written to `dbspend360_total_all_purpose_spends`,
the row's `cloud_cost` equals `dbspend360_cloud_cost_explorer.cloud_cost`
for the same `(cluster_id, cost_incurred_date, currency)` ± 0.01 USD.
Asserted in audit log; mismatches above tolerance raise `DataQualityError`.

## 4. New + changed surface area

### 4.1 New files

**Pipeline (Databricks notebooks).** Decision (confirmed): **new sibling
notebooks**; existing `dbspend360_dbu_cost_app.ipynb` and
`databricks_job_spends_app.ipynb` are not touched. Rejected alternatives were
(a) extending the existing notebooks with a `mode = JOB | ALL_PURPOSE` widget
(DRYer but adds a configuration axis to a working pipeline) and (b) refactoring
shared logic into `utils_common.ipynb` so both modes become thin wrappers
(cleanest long-term but biggest blast radius). The sibling approach keeps the
existing job-cluster pipeline byte-identical and reverts cleanly.

- `jobs/ddls/dbspend360_all_purpose_dbu_cost.ipynb` — DDL for the per-user DBU
  table. Keyed on `(cluster_id, user_id, usage_date)`. Columns:
  `cluster_id`, `user_id`, `usage_date`, `databricks_cost`, `currency`,
  `sku_name`, `workspace_id`, `data_security_mode`, `created_at`, `updated_at`.
- `jobs/ddls/dbspend360_total_all_purpose_spends.ipynb` — DDL for the final
  rollup. Same key, adds `cloud_cost`, `compute_cost`, `storage_cost`,
  `network_cost`, `other_cost`, `total_cost`, `data_security_mode`.
- `jobs/notebooks/dbspend360_all_purpose_dbu_cost_app.ipynb` — pipeline app
  (sibling of `dbspend360_dbu_cost_app.ipynb`). Reuses `utils_common.ipynb`.
  Joins `system.billing.usage` (filtered `job_run_id IS NULL`) to
  `system.compute.clusters` (filtered `cluster_source IN ('UI','API')`,
  collapsed via `MAX_BY(owned_by, change_time)` and
  `MAX_BY(data_security_mode, change_time)`) and `system.billing.list_prices`.
  Writes one row per `(cluster_id, usage_date)` with `user_id = owned_by`.
- `jobs/notebooks/all_purpose_spends_app.ipynb` — final rollup app (sibling of
  `databricks_job_spends_app.ipynb`). Joins the new DBU table with
  `dbspend360_cloud_cost_explorer` on
  `(cluster_id, currency, usage_date == cost_incurred_date)`. No apportionment
  in v1 — cloud cost flows directly. Asserts the §3.3 reconciliation invariant.

**Backend (FastAPI):**

- `server/routers/all_purpose.py` — new router mounted under
  `/api/all-purpose/*`. Endpoints listed in §6.
- (No new model file; new Pydantic models live alongside existing ones in
  `server/models/job_spend.py` — see §4.2.)

**Frontend (React):**

- `client/src/components/ui/tabs.tsx` — shadcn-style `Tabs` wrapper around
  `@radix-ui/react-tabs` (already a direct dep in `package.json`). Matches
  the project's existing shadcn "new-york" style from `components.json`.
- `client/src/types/all-purpose.ts` — TypeScript interfaces:
  `AllPurposeClusterSpend`, `AllPurposeUserSpend`, `GroupedAllPurposeCluster`,
  `GroupedAllPurposeUser`, `AllPurposeSummaryMetrics`, paginated wrappers.
- `client/src/hooks/useAllPurposeClusters.ts` — `useAllPurposeClustersByCluster`,
  `useAllPurposeClustersByUser`, `useAllPurposeSummary`,
  `useAllPurposeTopClusters`, `useAllPurposeTopUsers`. Same React Query /
  `keepPreviousData` / prefetch pattern as `useGroupedJobSpends.ts`.
- `client/src/components/JobClustersDashboard.tsx` — **moved**, not new
  logically: the entire current body of `Dashboard.tsx` (everything below the
  `<div className="container ...">` wrapper) is extracted here verbatim so the
  Job Clusters tab keeps rendering identical pixels.
- `client/src/components/AllPurposeDashboard.tsx` — the parallel dashboard,
  with the two sub-tabs (`<Tabs defaultValue="by-cluster">`).
- `client/src/components/AllPurposeSummaryCards.tsx` — KPI strip: total
  all-purpose spend, distinct cluster count, distinct owner count, top-cost
  cluster, top-cost owner. Same `Card` / `Skeleton` styling as `SummaryCards.tsx`.
- `client/src/components/AllPurposeClustersTable.tsx` — By Cluster table:
  `cluster_id`, `cluster_name`, `owner` (with `data_security_mode` badge),
  active days, `compute/storage/network/other/cloud/databricks/total` columns.
  Expand row → per-day rows.
- `client/src/components/AllPurposeUsersTable.tsx` — By User table: `user_id`,
  cluster_count, active_days, cost columns. Expand row → per-cluster rows.
  Render `__unknown__` as italicized "Unknown".
- `client/src/components/AllPurposeClusterFilterControls.tsx` — same date
  presets + search by cluster name / id / owner.

### 4.2 Changed files

- `jobs/ddls/create_all_tables.ipynb` — add the two new DDL notebook names to
  the `DDL_NOTEBOOKS` list so `create_all_tables` provisions them too.
- `jobs/resource_templates/DBSPEND360.yaml` — add two new task entries
  (`Dbspend360_all_purpose_dbu_costs`, `all_purpose_spends`). The first
  depends on `cloud_cost_explorer`; the second depends on the first. The new
  branch runs in parallel with the existing
  (`Dbspend360dbu_costs` → `databricks_job_spends`) branch since they share
  only the `cloud_cost_explorer` upstream.
- `server/models/job_spend.py` — append 7 new models:
  `AllPurposeClusterSpend`, `AllPurposeUserSpend`, `GroupedAllPurposeCluster`
  (with `users: list[AllPurposeUserSpend]`), `GroupedAllPurposeUser` (with
  `clusters: list[AllPurposeClusterSpend]`), `AllPurposeSummaryMetrics`, plus
  `PaginatedAllPurposeClusters` and `PaginatedAllPurposeUsers`. No edits to
  existing models.
- `server/services/databricks_service.py` — add ~6 new async methods
  (`get_all_purpose_grouped_by_cluster`, `get_all_purpose_grouped_by_user`,
  `get_all_purpose_summary_metrics`, `get_all_purpose_top_clusters`,
  `get_all_purpose_top_users`, `_get_batch_cluster_days`). **One generalization:**
  `get_cluster_cost_summary()` today does `GROUP BY job_id, run_id` against
  `dbspend360_total_job_spends`. For all-purpose the natural grain is
  `(user_id, usage_date)` against `dbspend360_total_all_purpose_spends`. Add a
  `cluster_kind: Literal["job", "all_purpose"] = "job"` parameter that
  selects both the source table and the grouping clause; default `"job"`
  preserves every existing call site byte-identically.
- `server/app.py` — `from server.routers.all_purpose import router as all_purpose_router`
  + one `app.include_router(...)` line. **Must be inserted before the
  `StaticFiles` mount at the bottom** — that mount catches all unmatched
  routes and any router added after it is unreachable (existing comment in the
  file calls this out).
- `server/config/config_loader.py` — add one new property
  `all_purpose_table_name` defaulting to `dbspend360_total_all_purpose_spends`
  in the configured schema. Read in `DatabricksService.__init__` and stored
  alongside `self.table_name` as `self.all_purpose_table_name`.
- `config/app.dev.config` (and any sibling env configs) — one new line:
  `all_purpose_table_name = dbspend360.03apr.dbspend360_total_all_purpose_spends`.
  Defaults in `config_loader.py` cover the case where it's omitted; the config
  line is for explicitness.
- `client/src/lib/api-client.ts` — extend the `ApiClient` class with
  `getAllPurposeGroupedByCluster`, `getAllPurposeGroupedByUser`,
  `getAllPurposeSummaryMetrics`, `getAllPurposeTopClusters`,
  `getAllPurposeTopUsers`. Mirrors the existing job-cluster methods.
- `client/src/components/Dashboard.tsx` — **becomes thin shell**: keeps the
  header + `ThemeToggle`, hosts `<Tabs defaultValue="job-clusters">` with the
  two tab panes (`<JobClustersDashboard />` / `<AllPurposeDashboard />`).
  ~30 lines including imports. Reads `?tab=...` from `window.location.search`
  on mount and writes it back via `history.replaceState` on tab change (no
  `react-router-dom` dep).
- `client/src/fastapi_client/` — regenerated by `scripts/make_fastapi_client.py`
  (the watch script does this automatically). No hand edits.

### 4.3 Untouched but worth calling out

Reused as-is by the All-Purpose tab:

- `jobs/notebooks/{aws,azure,gcp}_cloud_cost_explorer_app.ipynb` — already
  cluster-source-agnostic; produces `dbspend360_cloud_cost_explorer` keyed by
  `(cluster_id, cost_incurred_date, currency)` for **all** clusters regardless
  of source.
- `jobs/notebooks/utils_common.ipynb` — all the `get_date_window`,
  `log_audit_run`, `validate_*`, `_safe_append`, `safe_cache` helpers are
  reused by the new pipeline notebooks unchanged.
- `server/routers/dashboard.py` `/cluster/{id}/details`, `/cluster/{id}/analyze`,
  `/other-cost-breakdown` — already cluster-agnostic, called by both tabs.
- `server/services/llm_service.py` — `analyze_cluster_configuration()` takes
  raw cluster details, no changes needed.

## 5. Sample SQL for the new endpoints

### 5.1 `get_all_purpose_grouped_by_cluster()`

One row per cluster in the window, with the owner's `user_id` and
`data_security_mode` denormalized for badge rendering:

```sql
WITH filtered AS (
    SELECT *
    FROM {all_purpose_table_name}
    WHERE usage_date >= '{start_date}'
      AND usage_date <= '{end_date}'
),
cluster_level AS (
    SELECT cluster_id,
           ANY_VALUE(user_id)             AS owner_user_id,
           ANY_VALUE(data_security_mode)  AS data_security_mode,
           COUNT(DISTINCT usage_date)     AS active_days,
           SUM(cloud_cost)                AS total_cloud_cost,
           SUM(databricks_cost)           AS total_databricks_cost,
           SUM(compute_cost)              AS total_compute_cost,
           SUM(storage_cost)              AS total_storage_cost,
           SUM(network_cost)              AS total_network_cost,
           SUM(other_cost)                AS total_other_cost
    FROM filtered
    GROUP BY cluster_id
)
SELECT c.cluster_id,
       c.owner_user_id,
       c.data_security_mode,
       c.active_days,
       c.total_cloud_cost,
       c.total_databricks_cost,
       c.total_compute_cost,
       c.total_storage_cost,
       c.total_network_cost,
       c.total_other_cost,
       cl.cluster_name,
       COUNT(*) OVER() AS total_matching
FROM cluster_level c
LEFT JOIN (
    -- SCD-collapse: system.compute.clusters can have multiple snapshot rows
    -- per cluster_id; MAX_BY picks the most-recent name.
    SELECT cluster_id,
           MAX_BY(cluster_name, change_time) AS cluster_name
    FROM system.compute.clusters
    WHERE cluster_source IN ('UI','API')
    GROUP BY cluster_id
) cl ON c.cluster_id = cl.cluster_id
{search_clause}
ORDER BY (c.total_cloud_cost + c.total_databricks_cost) DESC
LIMIT {limit} OFFSET {offset}
```

(`user_count` is intentionally not selected — under v1 owner attribution every
cluster has exactly one user, so the column would always be 1.)

A second batch query (`_get_batch_cluster_days`) fetches the top-N per-day
rows for the page's `cluster_id`s, parallel to today's `_get_batch_job_runs()`.

### 5.2 `get_all_purpose_grouped_by_user()`

Note the dedicated `user_active_days` CTE that computes distinct active days
from `filtered` directly. Summing `COUNT(DISTINCT usage_date)` across the
per-cluster CTE would **double-count** any day on which a user was active on
multiple clusters; pulling from `filtered` avoids the bug.

```sql
WITH filtered AS (
    SELECT * FROM {all_purpose_table_name}
    WHERE usage_date >= '{start_date}' AND usage_date <= '{end_date}'
),
user_cluster_level AS (
    SELECT user_id, cluster_id,
           SUM(cloud_cost)             AS cloud_cost,
           SUM(databricks_cost)        AS databricks_cost,
           SUM(compute_cost)           AS compute_cost,
           SUM(storage_cost)           AS storage_cost,
           SUM(network_cost)           AS network_cost,
           SUM(other_cost)             AS other_cost,
           COUNT(DISTINCT usage_date)  AS cluster_active_days
    FROM filtered
    GROUP BY user_id, cluster_id
),
user_active_days AS (
    SELECT user_id, COUNT(DISTINCT usage_date) AS active_days
    FROM filtered
    GROUP BY user_id
),
user_level AS (
    SELECT ucl.user_id,
           COUNT(DISTINCT ucl.cluster_id) AS cluster_count,
           uad.active_days                AS user_active_days,
           SUM(ucl.cloud_cost)            AS total_cloud_cost,
           SUM(ucl.databricks_cost)       AS total_databricks_cost,
           SUM(ucl.compute_cost)          AS total_compute_cost,
           SUM(ucl.storage_cost)          AS total_storage_cost,
           SUM(ucl.network_cost)          AS total_network_cost,
           SUM(ucl.other_cost)            AS total_other_cost
    FROM user_cluster_level ucl
    JOIN user_active_days uad USING (user_id)
    GROUP BY ucl.user_id, uad.active_days
)
SELECT user_id, cluster_count, user_active_days,
       total_cloud_cost, total_databricks_cost,
       total_compute_cost, total_storage_cost,
       total_network_cost, total_other_cost,
       COUNT(*) OVER() AS total_matching
FROM user_level
{search_clause}
ORDER BY (total_cloud_cost + total_databricks_cost) DESC
LIMIT {limit} OFFSET {offset}
```

### 5.3 `get_all_purpose_summary_metrics()`

Same CTE chain as `get_summary_metrics()` but parametrized for the all-purpose
table and reports distinct cluster + user counts (not job counts):

```sql
WITH filtered AS (
    SELECT * FROM {all_purpose_table_name}
    WHERE usage_date >= '{start_date}' AND usage_date <= '{end_date}'
),
cluster_day_level AS (
    SELECT cluster_id, user_id, usage_date,
           SUM(cloud_cost)      AS cloud_cost,
           SUM(databricks_cost) AS databricks_cost,
           SUM(compute_cost)    AS compute_cost,
           SUM(storage_cost)    AS storage_cost,
           SUM(network_cost)    AS network_cost,
           SUM(other_cost)      AS other_cost
    FROM filtered
    GROUP BY cluster_id, user_id, usage_date
)
SELECT
    (SELECT COUNT(DISTINCT cluster_id) FROM filtered) AS total_clusters,
    (SELECT COUNT(DISTINCT user_id)    FROM filtered) AS total_users,
    SUM(cloud_cost + databricks_cost) AS total_spend,
    AVG(cloud_cost + databricks_cost) AS avg_cost_per_cluster_day,
    MAX(cloud_cost + databricks_cost) AS max_cost_per_cluster_day,
    MIN(cloud_cost + databricks_cost) AS min_cost_per_cluster_day,
    SUM(cloud_cost)      AS total_cloud_cost,
    SUM(databricks_cost) AS total_databricks_cost,
    SUM(compute_cost)    AS total_compute_cost,
    SUM(storage_cost)    AS total_storage_cost,
    SUM(network_cost)    AS total_network_cost,
    SUM(other_cost)      AS total_other_cost
FROM cluster_day_level
```

### 5.4 Pipeline merge — direct cloud cost flow (v1)

The crux of `all_purpose_spends_app.ipynb`. Under §3.3 there is **no
apportionment**; the cloud cost flows directly through a 1:1 join. The join
condition includes `currency` to guard against multi-currency fan-out (the
existing job-cluster pipeline has the same risk but doesn't enforce this; we
fix it here):

```python
joined = (
    dbu_df.alias("d")
    .join(
        cloud_df.alias("cc"),
        on=(
            (F.col("d.cluster_id") == F.col("cc.cluster_id")) &
            (F.col("d.usage_date") == F.col("cc.cost_incurred_date")) &
            (F.col("d.currency")   == F.col("cc.currency"))
        ),
        how="left",
    )
    .withColumn("cloud_cost",   F.coalesce(F.col("cc.cloud_cost"),   F.lit(0.0)))
    .withColumn("compute_cost", F.col("cc.compute_cost"))
    .withColumn("storage_cost", F.col("cc.storage_cost"))
    .withColumn("network_cost", F.col("cc.network_cost"))
    .withColumn("other_cost",   F.col("cc.other_cost"))
    .withColumn(
        "total_cost",
        F.coalesce(F.col("cloud_cost"), F.lit(0.0)) +
        F.coalesce(F.col("d.databricks_cost"), F.lit(0.0)),
    )
    .withColumn(
        "currency",
        F.coalesce(F.col("d.currency"), F.col("cc.currency")),
    )
)
```

The error-log writes (cloud-only and DBU-only halves) follow the existing
`_log_errors` pattern in `databricks_job_spends_app.ipynb` with `user_id`
denormalized into the `raw_record` JSON column — **no error-log DDL change
needed**.

A reconciliation check is asserted in the audit log after the MERGE: for every
`(cluster_id, usage_date)` in the window,
`cloud_cost in dbspend360_total_all_purpose_spends` for that
`(cluster_id, cost_incurred_date, currency)` equals
`dbspend360_cloud_cost_explorer.cloud_cost` ± 0.01 USD. Mismatches above the
threshold raise `DataQualityError` and write to `dbspend360_error_log`,
matching the existing pipeline pattern.

## 6. New backend endpoints

All under prefix `/api/all-purpose/`, mirroring the existing `dashboard_router`
shape so the frontend layer can be near-symmetric:

| Method | Path | Response | Mirrors |
|---|---|---|---|
| GET | `/grouped-by-cluster` | `PaginatedAllPurposeClusters` | `/grouped-job-spends` |
| GET | `/grouped-by-user`    | `PaginatedAllPurposeUsers`    | (no analogue today) |
| GET | `/summary`            | `AllPurposeSummaryMetrics`    | `/summary` |
| GET | `/top-clusters`       | `list[GroupedAllPurposeCluster]` | `/top-jobs` |
| GET | `/top-users`          | `list[GroupedAllPurposeUser]`    | (new) |

All accept the same `start_date` / `end_date` / `page` / `per_page` / search
query parameters as the existing dashboard endpoints. Errors bubble through
`HTTPException(500)` with the same shape.

Reused cluster-agnostic endpoints (no change, called from both tabs):

- `/api/cluster/{id}/details`
- `/api/cluster/{id}/analyze` (uses generalized `get_cluster_cost_summary`
  with `cluster_kind` parameter)
- `/api/other-cost-breakdown` (accepts `cluster_id` filter — works for any
  cluster regardless of source)
- `/api/cloud-platform`, `/api/databricks-host`, `/api/date-presets`,
  `/api/health`

## 7. Slicing strategy

**Decision (confirmed): single PR on `feat/all-purpose-clusters-tab`** —
pipeline + backend + UI ship together. Two alternatives considered:

| Option | Verdict | Tradeoff |
|---|---|---|
| **Single PR** (chosen) | Single review surface; reviewer sees the full vertical and can sanity-check that the pipeline rows the frontend expects actually exist with those names. No intermediate "tab exists but always shows zero rows" state on `main`. Diff is ~20 files / ~1500 LOC. |
| Three PRs (pipeline → backend → frontend) | Rejected | Smaller reviewable chunks and per-layer revertability, but 3× review overhead, intermediate state on `main` is awkward ("router exists but no UI"), and PR-by-PR model bikeshedding is more likely. |
| Two PRs (pipeline first, then backend + frontend together) | Rejected | Compromise that captures neither full reviewer context nor independent revertability. |

The single PR is internally organized as **11 sequential checkpoints**; see
§8. Each checkpoint is self-contained — it lists the minimum files to read for
context, the files to create/modify, the implementation notes that matter,
and explicit exit criteria. A checkpoint can be picked up cold in a fresh
chat session without re-reading the full plan.

## 8. Implementation checkpoints

Conventions used in this section:

- **Read first** — minimum files to load into the chat context before starting.
  Anything else is best looked up on demand.
- **Create / modify** — the new or edited files for that checkpoint.
- **Implementation notes** — the non-obvious decisions / pitfalls.
- **Exit criteria** — concrete, verifiable conditions. Don't move to the next
  checkpoint until all are met.

Do the checkpoints in order; later ones assume earlier ones are complete.

### CP1 — Provision the two new Delta tables

**Goal.** Create the DDL notebooks and run the bootstrap so the empty tables
exist in the dev catalog.

**Read first.**
- `jobs/ddls/dbspend360_dbu_cost.ipynb`
- `jobs/ddls/dbspend360_total_job_spends.ipynb`
- `jobs/ddls/create_all_tables.ipynb`

**Create / modify.**
- `jobs/ddls/dbspend360_all_purpose_dbu_cost.ipynb` (new) — schema per §4.1.
- `jobs/ddls/dbspend360_total_all_purpose_spends.ipynb` (new) — schema per §4.1.
- `jobs/ddls/create_all_tables.ipynb` — append both notebook names to the
  `DDL_NOTEBOOKS` list.

**Implementation notes.**
- Both DDLs mirror the existing equivalents in style (widgets, `CLUSTER BY
  AUTO`, `dbutils.notebook.exit` returning the FQN).
- Include `data_security_mode STRING` in both new tables.
- No primary-key constraint — uniqueness is enforced by MERGE.

**Exit criteria.**
1. Both notebooks deployed to the dev workspace.
2. Running `create_all_tables` against the dev catalog succeeds and lists both
   new tables as `SUCCESS` in the output.
3. `DESCRIBE TABLE <catalog>.<schema>.dbspend360_all_purpose_dbu_cost` shows
   the expected columns including `data_security_mode`.

### CP2 — All-purpose DBU collection pipeline

**Goal.** Stand up the per-user-per-day DBU table.

**Read first.**
- `jobs/notebooks/dbspend360_dbu_cost_app.ipynb` (template)
- `jobs/notebooks/utils_common.ipynb` (for `get_date_window`, `validate_*`,
  `safe_cache`, `log_audit_run`)
- The DDL created in CP1

**Create.**
- `jobs/notebooks/dbspend360_all_purpose_dbu_cost_app.ipynb`

**Implementation notes.**
Structurally identical to `dbspend360_dbu_cost_app.ipynb` but with these
deltas:

- Cluster filter: `cluster_source IN ('UI','API')` (vs `= 'JOB'`).
- The cluster subquery also pulls `owned_by` and `data_security_mode`,
  collapsed via `MAX_BY(owned_by, change_time)` and
  `MAX_BY(data_security_mode, change_time)` per `cluster_id`.
- Usage filter: `usage_metadata.job_run_id IS NULL`.
- Aggregation key: `(cluster_id, usage_date, workspace_id)`. No `job_id` /
  `run_id` columns.
- Project `user_id = COALESCE(cluster.owned_by, '__unknown__')`.
- Project `data_security_mode` straight through.
- MERGE key: `t.cluster_id = s.cluster_id AND t.user_id = s.user_id AND
  t.usage_date = s.usage_date`.
- `TABLE_NAME = "dbspend360_all_purpose_dbu_cost"`.

**Exit criteria.**
1. Manual notebook run against dev for a known 30-day window completes with
   non-zero `merged_row_count` (or 0 with explanatory INFO log if the
   workspace genuinely has no all-purpose usage in that window).
2. Spot-check: every `cluster_id` in the new table maps to a
   `system.compute.clusters` row with `cluster_source IN ('UI','API')`.
3. Audit log entry written with `SUCCESS`.
4. Zero rows have `user_id IS NULL` (use `__unknown__` instead).

### CP3 — All-purpose total spends rollup pipeline

**Goal.** Join the new DBU table to `dbspend360_cloud_cost_explorer` and
produce the final rollup.

**Read first.**
- `jobs/notebooks/databricks_job_spends_app.ipynb` (template)
- Output of CP2 and existing `dbspend360_cloud_cost_explorer` DDL

**Create.**
- `jobs/notebooks/all_purpose_spends_app.ipynb`

**Implementation notes.**
- Structure mirrors `databricks_job_spends_app.ipynb`.
- Join per §5.4 (includes `currency` in the join condition — explicit
  improvement over the job-cluster pipeline).
- **No apportionment**; pass cloud cost columns through directly.
- `total_cost = COALESCE(cloud_cost, 0) + COALESCE(databricks_cost, 0)`.
- MERGE key: `(cluster_id, user_id, usage_date)`.
- `_log_errors` writes `user_id` inside the `raw_record` JSON column; no
  error-log DDL change is needed.
- After the MERGE, assert the reconciliation invariant from §5.4 with a
  `spark.sql` query and raise `DataQualityError` on mismatch > 0.01.

**Exit criteria.**
1. Manual run against dev completes with `SUCCESS`.
2. Reconciliation query returns 0 mismatched cluster-days.
3. `SELECT COUNT(*) FROM dbspend360_total_all_purpose_spends WHERE usage_date
   BETWEEN <window>` matches `SELECT COUNT(*) FROM
   dbspend360_all_purpose_dbu_cost` for the same window (1:1 join).

### CP4 — DAB wiring

**Goal.** Make the two new notebooks run as part of the scheduled `DBSpend360`
job.

**Read first.**
- `jobs/resource_templates/DBSPEND360.yaml`

**Modify.**
- `jobs/resource_templates/DBSPEND360.yaml` — append two task entries:
  - `Dbspend360_all_purpose_dbu_costs` (depends on `cloud_cost_explorer`)
  - `all_purpose_spends` (depends on `Dbspend360_all_purpose_dbu_costs`)

**Implementation notes.**
- Both tasks reuse the workspace path pattern of the existing tasks.
- The new branch (`Dbspend360_all_purpose_dbu_costs` → `all_purpose_spends`)
  runs in parallel with the existing branch (`Dbspend360dbu_costs` →
  `databricks_job_spends`) since they share only `cloud_cost_explorer`.

**Exit criteria.**
1. `databricks bundle validate` passes.
2. `databricks bundle deploy` updates the dev job.
3. A manual job run from the Workflows UI completes with all four downstream
   tasks `SUCCEEDED`.

### CP5 — Backend models + config

**Goal.** Define the new wire-level types and the all-purpose table name
configuration.

**Read first.**
- `server/models/job_spend.py`
- `server/config/config_loader.py`
- `config/app.dev.config`

**Modify.**
- `server/models/job_spend.py` — append: `AllPurposeClusterSpend`,
  `AllPurposeUserSpend`, `GroupedAllPurposeCluster` (with `users:
  list[AllPurposeUserSpend]`), `GroupedAllPurposeUser` (with `clusters:
  list[AllPurposeClusterSpend]`), `AllPurposeSummaryMetrics`,
  `PaginatedAllPurposeClusters`, `PaginatedAllPurposeUsers`. Don't touch
  existing models.
- `server/config/config_loader.py` — add `all_purpose_table_name` property
  (read from `[databricks]` section; default to
  `dbspend360_total_all_purpose_spends` in the configured schema).
- `config/app.dev.config` — add
  `all_purpose_table_name = dbspend360.03apr.dbspend360_total_all_purpose_spends`.

**Implementation notes.**
- `data_security_mode: Optional[str]` belongs on both `AllPurposeClusterSpend`
  and `GroupedAllPurposeCluster`.
- `user_id: str` (never None at the model boundary — fall back to
  `__unknown__` in the service layer if absent).

**Exit criteria.**
1. `uv run python -c "from server.models.job_spend import
   AllPurposeClusterSpend; print(AllPurposeClusterSpend.model_json_schema())"`
   runs without errors.
2. `uv run python -c "from server.config.config_loader import app_config;
   print(app_config.all_purpose_table_name)"` prints the configured FQN.

### CP6 — Backend service methods

**Goal.** Query the new table from `DatabricksService`.

**Read first.**
- `server/services/databricks_service.py` (esp. `get_grouped_job_spends`,
  `_get_batch_job_runs`, `get_summary_metrics`, `get_top_jobs`,
  `get_cluster_cost_summary`)
- The models from CP5

**Modify.**
- `server/services/databricks_service.py`:
  - In `__init__`: `self.all_purpose_table_name = app_config.all_purpose_table_name`.
  - `get_all_purpose_grouped_by_cluster()` — SQL per §5.1; returns
    `PaginatedAllPurposeClusters`.
  - `get_all_purpose_grouped_by_user()` — SQL per §5.2; returns
    `PaginatedAllPurposeUsers`.
  - `get_all_purpose_summary_metrics()` — SQL per §5.3; returns
    `AllPurposeSummaryMetrics`.
  - `get_all_purpose_top_clusters()` — top-N by total cost; cluster-grain
    analogue of `get_top_jobs`.
  - `get_all_purpose_top_users()` — top-N by total cost, grouped by user.
  - `_get_batch_cluster_days()` — parallel to `_get_batch_job_runs`; fetches
    per-cluster per-day expansion rows for the page's `cluster_id`s.
  - Generalize `get_cluster_cost_summary()` with
    `cluster_kind: Literal["job","all_purpose"] = "job"` parameter — selects
    source table and grouping clause. Default value preserves every existing
    call site byte-identically.

**Exit criteria.**
1. Each new method has at least one happy-path call manually exercised via
   `uv run python -c` against dev data.
2. `get_cluster_cost_summary(<any existing job cluster id>)` returns
   byte-identical output to before the refactor (compare
   `json.dumps(sort_keys=True)`).

### CP7 — Backend router + app wiring

**Goal.** Expose the new endpoints under `/api/all-purpose/*`.

**Read first.**
- `server/routers/dashboard.py` (the patterns to mirror)
- `server/app.py` (esp. the `StaticFiles` mount comment block)

**Create / modify.**
- `server/routers/all_purpose.py` (new) — 5 endpoints per §6, mirroring the
  validation / error-handling style of `dashboard.py`. Router instance:
  `router = APIRouter(prefix="/api/all-purpose", tags=["all-purpose"])`.
- `server/app.py` — import the new router and call `app.include_router(...)`
  **above** the `StaticFiles` mount.

**Implementation notes.**
- Reuse `get_databricks_service()` lazy initializer; do not create a second
  instance.
- Each endpoint validates `start_date <= end_date` and returns
  `HTTPException(500)` on service exceptions.

**Exit criteria.**
1. `nohup ./watch.sh > /tmp/databricks-app-watch.log 2>&1 &` starts cleanly
   (check log for `Application startup complete.`).
2. Per the FastAPI verification protocol in `CLAUDE.md`, all 5 endpoints
   return 200 with the expected JSON shape:
   ```bash
   curl -s "http://localhost:8000/api/all-purpose/summary?start_date=2026-05-01&end_date=2026-05-31" | jq
   curl -s "http://localhost:8000/api/all-purpose/grouped-by-cluster?start_date=...&end_date=...&page=1&per_page=10" | jq
   curl -s "http://localhost:8000/api/all-purpose/grouped-by-user?start_date=...&end_date=...&page=1&per_page=10" | jq
   curl -s "http://localhost:8000/api/all-purpose/top-clusters?start_date=...&end_date=...&limit=5" | jq
   curl -s "http://localhost:8000/api/all-purpose/top-users?start_date=...&end_date=...&limit=5" | jq
   ```
3. `total_count` from paginated endpoints equals `COUNT(*)` from the
   equivalent group-level SQL run directly against the warehouse.

### CP8 — Frontend Tabs primitive + Dashboard extraction

**Goal.** Set up the top-level tab shell without changing any existing
behavior.

**Read first.**
- `client/src/components/Dashboard.tsx`
- `client/src/components/ui/*` (for shadcn style conventions)
- `client/components.json`

**Create / modify.**
- `client/src/components/ui/tabs.tsx` (new) — standard shadcn `Tabs` /
  `TabsList` / `TabsTrigger` / `TabsContent` wrapper around
  `@radix-ui/react-tabs`.
- `client/src/components/JobClustersDashboard.tsx` (new) — the entire current
  body of `Dashboard.tsx` **below** the header `<div className="flex
  items-start justify-between ...">`, lifted verbatim.
- `client/src/components/Dashboard.tsx` — becomes a thin shell: header +
  `<Tabs defaultValue="job-clusters">` with
  `<TabsContent value="job-clusters"><JobClustersDashboard /></TabsContent>`
  and a placeholder `<TabsContent value="all-purpose">Coming next</TabsContent>`.

**Implementation notes.**
- Read `?tab=...` from `window.location.search` once on mount; persist on tab
  change via `history.replaceState`. No `react-router-dom` dep.
- Default tab is `job-clusters`.

**Exit criteria.**
1. Watch script picks up the change with no TS errors.
2. Visual diff (Playwright screenshot before vs after) of the Job Clusters tab
   shows identical pixels.
3. Clicking the (placeholder) All-Purpose tab swaps the panel without a
   network call or page reload.
4. Refresh on `?tab=all-purpose` lands back on the All-Purpose tab.

### CP9 — Frontend types + API client + hooks

**Goal.** Make the new endpoints addressable from React.

**Read first.**
- `client/src/types/job-spend.ts`
- `client/src/lib/api-client.ts`
- `client/src/hooks/useGroupedJobSpends.ts`

**Create / modify.**
- `client/src/types/all-purpose.ts` (new) — TS interfaces mirroring CP5's
  Pydantic models.
- `client/src/lib/api-client.ts` — append `getAllPurposeGroupedByCluster`,
  `getAllPurposeGroupedByUser`, `getAllPurposeSummaryMetrics`,
  `getAllPurposeTopClusters`, `getAllPurposeTopUsers`.
- `client/src/hooks/useAllPurposeClusters.ts` (new) — React Query hooks
  mirroring the job-cluster shapes: `useAllPurposeClustersByCluster`,
  `useAllPurposeClustersByUser`, `useAllPurposeSummary`,
  `useAllPurposeTopClusters`, `useAllPurposeTopUsers`. Use `keepPreviousData` +
  prefetch like the job-cluster hooks.

**Exit criteria.**
1. `tsc --noEmit` (via the watch script) passes with no errors.
2. From the browser console (with the watch server running):
   `await fetch('/api/all-purpose/summary?...').then(r => r.json())` returns
   data that satisfies the new TS interfaces.

### CP10 — Frontend AllPurposeDashboard UI

**Goal.** Render the All-Purpose tab with the two sub-tabs, summary cards, and
both tables.

**Read first.**
- `client/src/components/JobClustersDashboard.tsx` (the parallel structure
  from CP8)
- `client/src/components/SummaryCards.tsx`, `GroupedJobTable.tsx`,
  `FilterControls.tsx`

**Create / modify.**
- `client/src/components/AllPurposeDashboard.tsx` (new) — hosts
  `<Tabs defaultValue="by-cluster">` with both sub-tabs.
- `client/src/components/AllPurposeSummaryCards.tsx` (new) — KPI strip.
- `client/src/components/AllPurposeClustersTable.tsx` (new) — render
  `data_security_mode` as a badge ("Dedicated" / "Shared" / "Legacy" /
  "Unknown") next to the owner column. Expand row → per-day rows. Fallback
  label: `Cluster {cluster_id}` when `cluster_name` is NULL.
- `client/src/components/AllPurposeUsersTable.tsx` (new) — expand row →
  per-cluster rows. Render `__unknown__` as italicized "Unknown".
- `client/src/components/AllPurposeClusterFilterControls.tsx` (new) — date
  presets + search by cluster name / id / owner.
- `client/src/components/Dashboard.tsx` — replace the `all-purpose`
  placeholder with `<AllPurposeDashboard />`.

**Implementation notes.**
- Cluster details modal re-uses the existing `/api/cluster/{id}/details` and
  `/api/cluster/{id}/analyze` endpoints. The cost-summary panel inside the
  modal threads the new `cluster_kind="all_purpose"` parameter from CP6 to
  route to the correct rollup table.

**Exit criteria.**
1. Playwright walk: Open app → click "All-Purpose Clusters" → see summary
   cards with non-zero values → click "By Cluster" → expand first row → see
   daily breakdown → click "By User" → expand first row → see clusters owned.
2. Click a cluster row → cluster details modal opens with LLM analysis
   populated.
3. `data_security_mode` badges render correctly (verify against known
   `SINGLE_USER` and `USER_ISOLATION` clusters in dev).
4. No console errors.

### CP11 — Deploy + post-deploy verification

**Goal.** Ship to Databricks Apps and confirm health per the `CLAUDE.md`
protocol.

**Steps.**

1. `./deploy.sh`.
2. `uv run python dba_logz.py <app-url> --search "Application startup
   complete\|Uvicorn running" --duration 60`.
3. If startup messages don't appear, rerun without the search filter and fix
   any exceptions before proceeding.
4. `uv run python dba_client.py <app-url>
   /api/all-purpose/summary?start_date=...&end_date=...`.
5. `uv run python dba_client.py <app-url>
   /api/all-purpose/grouped-by-cluster?start_date=...&end_date=...&page=1&per_page=10`.

**Exit criteria.**
1. Log stream shows `Application startup complete.` and `Uvicorn running` with
   no exceptions.
2. Live curls return 200 with non-zero data for the workspace's 30-day window.
3. Manual smoke in browser: All-Purpose tab loads and renders end-to-end with
   real production data.

## 9. Acceptance criteria

1. **No regression on Job Clusters tab.** Every URL, endpoint response shape,
   and rendered UI element under the Job Clusters tab is byte-identical to
   before the change (visual diff). `claude_scripts/test_job_spend_dedup.py`
   continues to pass unchanged.
2. **Tab navigation works.** Selecting "All-Purpose Clusters" swaps the panel
   without a full page reload; selecting "Job Clusters" restores the previous
   view. The two sub-tabs (`By Cluster`, `By User`) within All-Purpose swap
   independently. URL state for current tab is preserved on refresh (read
   once from `?tab=...` query param; full router state not in this PR — see
   §13).
3. **Data correctness — source filter.** Every row in
   `dbspend360_total_all_purpose_spends` has a `cluster_id` that, when joined
   to `system.compute.clusters`, has `cluster_source IN ('UI','API')`. Zero
   rows where the cluster's source is `JOB`. Asserted in
   `claude_scripts/test_all_purpose_source_filter.py`.
4. **Data correctness — disjoint with job clusters.** No `(cluster_id,
   usage_date)` pair appears in **both** `dbspend360_total_job_spends` and
   `dbspend360_total_all_purpose_spends`. Asserted in the same test script.
5. **Reconciliation — 1:1 cloud cost (v1).** For every `(cluster_id,
   usage_date)` row in `dbspend360_total_all_purpose_spends`, the row's
   `cloud_cost` equals `dbspend360_cloud_cost_explorer.cloud_cost` for the
   same `(cluster_id, cost_incurred_date, currency)` ± 0.01 USD. Asserted in
   `claude_scripts/test_all_purpose_reconciliation.py` and at pipeline runtime
   via the audit-log invariant from §5.4.
6. **New endpoint contracts.** Each of the 5 new endpoints returns 200 with
   the documented Pydantic shape on a populated window. `total_count` on
   paginated endpoints matches `COUNT(*)` of the underlying group-level CTE.
7. **UI parity within the All-Purpose tab.** The All-Purpose dashboard
   renders: summary cards (with non-zero values), the By-Cluster table with at
   least one expandable cluster showing per-day rows on expand, the By-User
   table with at least one expandable user showing per-cluster rows on expand,
   the cluster details / LLM analysis modal on cluster-row click, and
   `data_security_mode` badges on the By-Cluster table.
8. **Deploy health.** Deployed app log stream shows `Application startup
   complete.` / `Uvicorn running` with no exceptions. Live curl against
   `/api/all-purpose/summary?start_date=...&end_date=...` returns non-zero
   `total_clusters` and `total_users` for the live workspace's 30-day window.

## 10. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `USER_ISOLATION` (shared) clusters get fully attributed to `owned_by` regardless of who actually ran workloads | Medium-High | Surface `data_security_mode` as an explicit badge ("Dedicated" / "Shared") in the By-Cluster table and in the cluster details modal. README "All-Purpose Cluster Attribution" section explains attribution accuracy per mode. Tag-based and audit-log attribution tracked as v2 in §13. |
| `owned_by` is NULL on the cluster snapshot (cluster deleted before October 2023, or other corner cases) → owner can't be resolved | Low | DBU pipeline projects `user_id = COALESCE(owned_by, '__unknown__')`. UI renders `__unknown__` as italicized "Unknown" with a tooltip explaining the cause. No data loss; degraded label only. |
| `system.compute.clusters` snapshot row for an all-purpose cluster may be missing entirely (deletion + retention) → `cluster_name` is NULL | Low | Identical pattern to today's job-cluster path (renamed-job rows render `Job {id}`); replicate fallback `Cluster {cluster_id}` in the table cell. |
| The `StaticFiles` mount in `server/app.py` accidentally swallows `/api/all-purpose/*` | Low — easy to catch | Insert the new `app.include_router(...)` **above** the `StaticFiles` mount, matching the existing comment block. Add a one-line smoke test that does `requests.get("http://localhost:8000/api/all-purpose/health").status_code == 200` to `claude_scripts/`. |
| Multi-currency rows in `dbspend360_cloud_cost_explorer` (rare; historical FX-converted) cause fan-out on the §5.4 join | Low | Join condition now includes `currency` (improvement over the job-cluster pipeline, which has the same latent risk). Reconciliation invariant catches any remaining mismatch. |
| Auto-generated TS client (regenerated from the new OpenAPI spec) shadows or breaks existing types | Low | The generator emits everything under `client/src/fastapi_client/`. Existing components import from `@/types/job-spend` and `@/lib/api-client` rather than the generated client, so additions to the generated dir are additive-only. Verified by visual inspection of the post-watch.sh `fastapi_client/services/` directory in a dev run. |
| Pipeline runs successfully but writes 0 rows in the dev workspace (workspace doesn't actually run all-purpose clusters during the lookback) | Medium | Add an `INFO` log entry at the end of the pipeline if `merged_row_count == 0` with a hint: "No all-purpose cluster usage found in window. Verify there exist clusters with `cluster_source IN ('UI','API')` having SKU-billed usage in the date window." Don't fail the pipeline — `0` is a legitimate state. |

## 11. Rollback

Per-layer rollback, in priority order:

1. **UI bug only** — git revert the frontend commits. Backend + pipeline stay,
   tab disappears, no data harmed.
2. **Backend regression** — git revert the `app.py` `include_router` line; the
   new router becomes 404 but the rest of the app is untouched.
3. **Pipeline data quality** — `dbspend360_total_all_purpose_spends` is a new
   Delta table; can be `DROP TABLE` + rerun after fixing the notebook. No
   migration of existing tables, so worst case is "drop the new table and the
   audit log entries for these two new pipeline names".

No data migration on existing tables. Rollback is fully reversible.

## 12. Effort estimate

~12–14 hours total, broken down per checkpoint:

| Checkpoint | Hours | Notes |
|---|---|---|
| CP1 — DDLs + register | 0.5 | Two small files mirroring existing DDLs |
| CP2 — DBU collection pipeline | 1.5 | Mostly mechanical port of `dbspend360_dbu_cost_app` |
| CP3 — Total spends rollup pipeline | 1.5 | Simpler than job-cluster version (no apportionment) |
| CP4 — DAB wiring + dev end-to-end run | 1 | Pipeline must run end-to-end before backend can be tested with real data |
| CP5 — Models + config | 0.5 | Append-only |
| CP6 — Service methods (incl. `cluster_kind` generalization) | 2 | Bulk of the SQL is mechanical mirroring |
| CP7 — Router + curl verification | 1 | Per CLAUDE.md FastAPI verification protocol |
| CP8 — Tabs primitive + Dashboard extraction | 1 | Visual-diff regression risk on Job Clusters tab; budget for it |
| CP9 — Types + api-client + hooks | 1 | Pattern-following |
| CP10 — All-Purpose UI (summary + 2 tables + filter controls + modal wiring) | 2 | New, but pattern-following |
| CP11 — Deploy + dba_logz monitoring + live curl | 1 | Standard deploy flow |
| Buffer | 1 | Unexpected `cluster_source` enum values, type-error cleanup, etc. |

## 13. Out of scope, captured for follow-up

- **Per-user-runner attribution (v2).** Once a sufficient signal exists,
  multiple `user_id` rows per `(cluster_id, usage_date)` become valid and the
  cloud cost is apportioned in proportion to per-user DBU share (formula
  preserved in §3.3). The reconciliation invariant relaxes from 1:1 to
  `SUM(per-user cloud_cost) per (cluster_id, usage_date) == cluster_cloud_cost
  ± 0.01`. Two candidate signals:
  - **Tag-based** via `system.billing.usage.custom_tags['databricks-user']` —
    feasible where workspaces enforce a per-user tag policy. Probe: query the
    tag's coverage on a sample window; if > 90 %, build the tag-based path as
    an opt-in.
  - **Audit-log-based** via `system.access.audit` (per-command user
    attribution joined on `request_params.clusterId`) — accurate but needs
    its own pre-aggregation pipeline.
- **All-purpose cluster cost analysis (LLM "why is this cluster expensive?")**
  — parallel to today's `analyze_job_costs` flow. Would need a new
  `analyze_all_purpose_cluster_costs` LLM method with prompts tuned for
  interactive-cluster shapes (idle time, oversize for actual workload, etc.).
- **Per-user URL deep-linking** — `?tab=all-purpose&subtab=by-user&user=alice@…`.
  This PR keeps URL state minimal (tab-level only). Going deeper means
  introducing a router (`react-router-dom` is not currently a dep) or
  hand-rolling `useSearchParams`.
- **"All clusters" combined view** — a third tab that sums Job + All-Purpose
  for a workspace-wide bird's-eye number. Trivial after this PR.
- **Cost alerts / budgets per user** — would need a new alerts table + cron
  job + email integration. Independent feature, separate PR.
- **Promote `claude_scripts/test_all_purpose_*` to real pytest** — same
  follow-up as item already noted in the top-jobs plan; CI wiring is the
  blocker, not the test code.

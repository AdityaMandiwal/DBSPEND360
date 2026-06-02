# Plan — Add an "Instance Pools" tab alongside Job Clusters and All-Purpose Clusters

Branch (proposed): `feat/instance-pools-tab`

## 1. Goal

Today DBSpend360 has two top-level tabs — **Job Clusters** (powered by
`dbspend360_total_job_spends`, keyed on `cluster_id × job_id × run_id × usage_date`)
and **All-Purpose Clusters** (powered by `dbspend360_total_all_purpose_spends`,
keyed on `cluster_id × user_id × usage_date`). Neither surfaces **instance
pools**, which are an orthogonal compute primitive: a pool is a pre-warmed set
of cloud instances that clusters (of any kind) can attach to for faster
startup. Pool usage is identifiable in `system.billing.usage` via
`usage_metadata.instance_pool_id`, and the pool itself is described in
`system.compute.instance_pools` (owner, size, idle-instance config, etc.).

Add a parallel **Instance Pools** experience as a **third top-level tab**,
shaped like the existing two but scoped to pool DBU consumption. The pool tab
has a single view (no sub-tabs):

- **By Pool** — one row per instance pool in the window, with two drill-downs:
  expand a pool row to see per-day cost, expand a day to see per-cluster cost
  on the pool that day. Powers "which pools are spending, and which clusters
  are driving each pool's bill".

After this change the navigation looks like:

```
Header (DBSpend360 + ThemeToggle)
├─ Tab: Job Clusters         (today's Dashboard contents, untouched)
├─ Tab: All-Purpose Clusters (untouched)
└─ Tab: Instance Pools       (new — single By-Pool view with nested drill-down)
```

## 1.5. Confirmed decisions

The architectural forks below are **locked in** from the MCQ pass that
preceded this plan. Tradeoff tables and rejected alternatives are retained in
§3 as a historical record, but no further questions on these need to be
answered before implementation.

| Fork | Decision | Detail in |
|---|---|---|
| Pool scope filter | **All pools** — `usage_metadata.instance_pool_id IS NOT NULL`, regardless of which `cluster_source` attached to the pool. Pool-backed Job and All-Purpose clusters both contribute rows. | §3.1 |
| Cost model | **DBU charges only in v1.** No cloud VM cost; no idle-instance cost. Source: `system.billing.usage × system.billing.list_prices`. Cloud cost (active + idle) deferred to v2. | §3.2 |
| Attribution | **No By-User view in v1.** Pools are shared by definition (multiple users / clusters per pool), so cross-pool chargeback is genuinely ambiguous. Per-cluster drill-down within a pool gives an "indirect" attribution lens. | §3.4 |
| Sub-tabs | **None.** Single By-Pool view with row-expansion → per-day, day-expansion → per-cluster. | §3.3 |
| Pipeline scope | **Sibling notebooks** (`dbspend360_pool_dbu_cost_app` + `pool_spends_app`); existing job and all-purpose pipelines untouched. No edits to `dbspend360_cloud_cost_explorer` (consistent with §3.2). | §4.1 |
| Cloud-cost source | **None in v1.** The two cloud-cost explorers (`{aws,azure,gcp}_cloud_cost_explorer_app.ipynb`) are not touched and `dbspend360_cloud_cost_explorer` is not joined into the pool pipeline. Schema reserves a `cloud_cost` column (always NULL in v1) so v2 needs no migration — see §3.2. | §3.2 |
| Pool creator resolution | **REST API only, modal-scoped, no list-view column, no denormalization.** Two upstream constraints govern this: (1) `system.compute.instance_pools` has **no `owned_by` column** (verified against the published schema, see §10); (2) the `system.compute.instance_pools.tags` column is documented as "User-defined tags for the instance pool **does not include default tags**", so the Databricks-auto-applied `DatabricksInstancePoolCreatorId` tag is **not visible from the system table at all** — only via REST API `default_tags`. (3) Independently, the Python SDK's `GetInstancePool` dataclass has no `creator_user_name` field, so the GUID is as far as a single REST call can resolve in v1; mapping GUID → email requires a second hop through the Workspace users API (deferred to v2 per §13). Concretely: no `pool_creator_id` column on the rollup table; no creator column in the list view; the pool details modal resolves the creator GUID per-request via `WorkspaceClient.instance_pools.get(...).default_tags['DatabricksInstancePoolCreatorId']`, cached the same way `get_job_name` caches job names. | §3.4, §4.1, §5.5, CP6 |
| Pool snapshot state | **Three states with distinct badges**, not binary. `delete_time IS NULL` → active (no badge). `delete_time IS NOT NULL` AND snapshot row exists → "Deleted YYYY-MM-DD" badge. Snapshot row entirely absent → "Snapshot missing" badge. Tracked via `pool_snapshot_missing BOOLEAN` and `pool_deleted_at TIMESTAMP` columns. | §3.5 |
| Navigation | **New top-level tab** (3rd) alongside Job Clusters and All-Purpose Clusters. | §4.2 |
| LLM analysis | **New dedicated `analyze_instance_pool_costs` LLM method** with prompts tuned for pool-specific patterns (idle config, oversize, autotermination tuning). Endpoint: `/api/instance-pool/{id}/analyze`. | §4.1, §4.2 |
| PR slicing | Single PR on `feat/instance-pools-tab`, broken into 11 sequential checkpoints (see §8). Mirrors `plan_all_purpose_clusters_tab.md`. | §7, §8 |

## 2. Non-goals

- **No changes to existing tab behavior.** The Job Clusters and All-Purpose
  Clusters tabs render byte-identical output. `dashboard_router`,
  `all_purpose_router`, and every component below them is untouched.
- **No changes to `dbspend360_cloud_cost_explorer`** or the three
  `{aws,azure,gcp}_cloud_cost_explorer_app` notebooks. v1 ships without any
  pool cloud-cost integration; the cloud-cost ETL path keeps its current
  contract.
- **No changes to existing DDL tables.** Pool data lands in two new Delta
  tables. No backfill, no migration of existing tables.
- **No idle-instance cost in v1.** Per §3.2, idle pool capacity (cloud VMs
  warm-but-unattached) is structurally invisible to `system.billing.usage`.
  Capturing it requires cloud-cost-explorer changes and is deferred to v2
  (§13).
- **No By-User chargeback view in v1.** Captured as v2 follow-up in §13.
- **No "all compute" combined view** — the three tabs stay disjoint at the
  navigation level. Per §3.6, double-counting across tabs (a job cluster on a
  pool contributes to BOTH Job Clusters and Instance Pools) is by design and
  documented in the README.
- **No alerts / budgets / scheduled reports for pools** in this PR.

## 3. Key data-model decisions

Five design forks govern the pool tables. Each is expensive to reverse after
data lands, so the decisions are recorded with their tradeoffs even though
all are now confirmed (see §1.5).

### 3.1 What counts as an "instance pool"?

Pool usage in `system.billing.usage` is identifiable in two ways:

1. **`usage_metadata.instance_pool_id IS NOT NULL`** — the authoritative
   field. Populated whenever the billed DBU charge was on a pool-managed
   instance, regardless of which cluster was attached.
2. **`sku_name`** — pool SKUs follow patterns like `..._POOL` /
   `..._PREMIUM_COMPUTE_(POOL_SKU)` etc., but the exact SKU enum is large and
   evolves with new Databricks features. Filtering on it is brittle.

**Decision (confirmed): filter to `instance_pool_id IS NOT NULL`** as the sole
primary filter. SKU-name pattern matching is not used as defense-in-depth
because (per the [`system.billing.usage` reference](https://docs.databricks.com/en/admin/system-tables/billing.html))
the `instance_pool_id` field is the canonical signal — every billed
pool-backed DBU has it populated, regardless of SKU naming.

Important implications of this choice:

- **No `cluster_source` filter.** Pool-backed clusters can have any source
  (`JOB`, `UI`, `API`, `PIPELINE`, etc.). A pool-backed job cluster will
  appear in BOTH the Job Clusters tab (filtered `cluster_source = 'JOB'`) AND
  the new Instance Pools tab (filtered `instance_pool_id IS NOT NULL`). This
  is by design — different lenses on the same compute. Documented in §3.6
  and §9.
- **`cluster_id` is denormalized into the table.** Every pool DBU row in
  `system.billing.usage` has `cluster_id` populated (the cluster that was
  using the pool's instance). We keep it as a non-key column so the
  per-cluster drill-down (under §3.3) is a single SQL query against the same
  table, no extra join.

Rejected alternatives (for the record):

- `LOWER(sku_name) LIKE '%pool%'` as the filter — SKU naming is unstable and
  case-sensitivity is inconsistent across regions/billing accounts. Rejected.
- Scoping to only pool-backed all-purpose clusters (the original q1 option
  `interactive_only`) — would silently exclude job clusters that run on
  pools, which is a significant portion of pool spend in many workspaces.
  Rejected as discussed during MCQ.

### 3.2 Cost model — DBU only in v1, no cloud cost

**Decision (confirmed): v1 ships with `databricks_cost` only.** No `cloud_cost`
is computed in v1.

**Why this is a constraint, not a tradeoff.** Idle instances in a pool
(instances that are warm but not attached to any cluster) generate **zero
rows in `system.billing.usage`** because no DBU is consumed when no cluster
is running. The cloud VM cost for idle capacity is only visible through cloud
cost APIs (AWS Cost Explorer / Azure Cost Management / GCP Billing) filtered
by the `DatabricksInstancePoolId` tag. The MCQ pass surfaced this conflict
explicitly; the resolution was to defer idle (and active) cloud cost to v2
in exchange for shipping the v1 DBU view fast.

**Schema reservation.** The final rollup table includes a `cloud_cost DOUBLE`
column that is **always NULL in v1**. This reserves the slot so that v2
(when the cloud-cost-explorer extension lands) can populate it without a
breaking schema migration. The frontend's `PoolSpend` TypeScript interface
also includes `cloud_cost?: number | null`; the By-Pool table simply hides
the column in v1 (no UI surface for an always-null value).

Tradeoffs that were considered and rejected:

| Option | Verdict | Why |
|---|---|---|
| Include cloud cost in v1 from existing `dbspend360_cloud_cost_explorer` (cluster-tag only) | Rejected | Captures only the cluster-active portion of pool cost. Idle cost (a primary motivation for pool tracking) stays invisible. Half-measure with high schema cost. |
| Extend cloud-cost explorers to also group by `DatabricksInstancePoolId` tag | **Deferred to v2** | Proper fix. Touches `aws_cloud_cost_explorer_app.ipynb`, `azure_cloud_cost_explorer_app.ipynb`, `gcp_cloud_cost_explorer_app.ipynb`, plus the explorer DDL. Roughly 3× the scope of v1. |
| DBU-only in v1, reserve `cloud_cost` slot | **Adopted as v1** | Ships the DBU view fast; zero risk to existing cloud-cost path; no schema migration for v2. |

### 3.3 Per-cluster drill-down inside a pool row (the "By-Pool" grain)

The single By-Pool view supports **two-level nested expansion**:

1. **Pool row → per-day rows.** Click a pool row to see daily DBU on that
   pool over the window.
2. **Day row → per-cluster rows.** Click a day row to see which clusters
   attached to the pool on that day and how much DBU each consumed.

To support both expansions cheaply (1 SQL query each) the rollup table is
keyed at the **finest natural grain**:

```
PRIMARY KEY (instance_pool_id, cluster_id, usage_date)
```

`cluster_id` is denormalized from the same `system.billing.usage` row that
contributed the DBU (every pool DBU row has both `instance_pool_id` and
`cluster_id` populated — see §3.1). Aggregations roll up to whichever grain
the UI needs:

- **By Pool (top level):** `GROUP BY instance_pool_id`
- **Per day inside a pool:** `GROUP BY instance_pool_id, usage_date`
- **Per cluster on a day inside a pool:** raw table, filtered to one
  `(instance_pool_id, usage_date)` pair

**Edge case: cluster_id NULL.** In rare cases a billing row may have
`instance_pool_id` set but `cluster_id` NULL (e.g. a future pool-management
SKU shape, or pool-level bootstrap charges). The pipeline writes
`cluster_id = '__pool_overhead__'` so the row stays accounted for. The UI
labels this row as "Pool overhead" in the per-cluster drill-down.

### 3.4 Why no By-User view in v1

**Decision (confirmed): the Instance Pools tab ships without a By-User
sub-tab.**

The All-Purpose Clusters tab uses `system.compute.clusters.owned_by` to
attribute cluster cost to a single user per (cluster, day). That model breaks
down for pools in two ways:

1. **Pools are inherently multi-tenant.** A pool's purpose is to be shared
   across clusters and users; the only "owner" signal a pool exposes is
   the pool **creator** GUID, not any kind of usage owner. Charging 100%
   of pool spend to the creator is misleading on its face. The creator
   GUID itself is also harder to source than the cluster-owner case:
   unlike `system.compute.clusters`, `system.compute.instance_pools`
   has **no `owned_by` column** (verified against the published schema
   in §10). The Databricks-auto-applied `DatabricksInstancePoolCreatorId`
   tag carries the GUID, but the system table's `tags` column is
   documented as "user-defined tags ... does not include default tags",
   so the auto-tag is **not visible from the system table at all**.
   The Python SDK's `GetInstancePool` dataclass likewise has no
   `creator_user_name` field; the GUID is exposed only as
   `default_tags['DatabricksInstancePoolCreatorId']` on that response.
   v1 therefore surfaces the creator GUID only inside the pool details
   modal (via a per-request `WorkspaceClient.instance_pools.get(...)`),
   not in the list view; GUID → email resolution requires a second hop
   through the Workspace users API and is deferred to v2 (§13).
2. **The cluster-owner-share apportionment that would fix (1)** requires
   summing `system.compute.clusters.owned_by` of each cluster on the pool
   weighted by that cluster's DBU share — which is implementable but
   encodes the same `USER_ISOLATION` approximation we already flag in the
   All-Purpose tab, compounded across the additional cluster-on-pool
   layer.

Both candidate attribution paths (cluster-owner-DBU-share apportionment;
tag/audit-log-based per-runner attribution) are tracked as v2 follow-ups in
§13. v1 ships with the per-cluster drill-down from §3.3 as the closest
"who is using this pool" signal — a user can see which clusters ran on a
pool and (via the existing cluster details modal) who owns each cluster.

### 3.5 Pool snapshot state — three states, not two

`system.compute.instance_pools` is an SCD2 table with both `change_time`
and `delete_time` columns (verified against the
[published schema](https://docs.databricks.com/aws/en/admin/system-tables/compute)).
That gives us three distinguishable states, not two, and each gets a
different UI badge:

| State | `pool_snapshot_missing` | `pool_deleted_at` | UI badge | When it happens |
|---|---|---|---|---|
| Active | `false` | `NULL` | none | Pool currently exists in the snapshot table and `delete_time IS NULL`. Normal path. |
| Deleted (visible) | `false` | populated TIMESTAMP | yellow "Deleted YYYY-MM-DD" | Pool was deleted but its SCD snapshot row is still within retention. Metadata (name, node type, idle config) is still trustworthy as of the delete time. Creator info — fetched separately via REST API in the modal path, see §3.4 — may or may not be resolvable depending on whether the Instance Pools REST API still tracks deleted pools. |
| Snapshot missing | `true` | `NULL` | yellow "Snapshot missing" | DBU rows exist in `system.billing.usage` with this `instance_pool_id` but no row in `system.compute.instance_pools`. Most common causes: (a) deleted before October 23 2023 (same retention bug as `clusters`); (b) multi-region workspace whose pool snapshot lives in another region (see §10). |

**Per-field fallback when `pool_snapshot_missing = true`:**

| Field | Behavior |
|---|---|
| `pool_name` | `'Pool {instance_pool_id}'` |
| `node_type` / `min_idle_instances` / `max_capacity` / `idle_instance_autotermination_minutes` | `NULL` |

(Creator info is not denormalized onto the rollup table at all — see §3.4
and the §1.5 confirmed decision — so there is no creator field to fall
back to here. The pool details modal makes a separate REST API call and
renders "Unknown creator" only when that call itself fails or returns no
`DatabricksInstancePoolCreatorId` in `default_tags`.)

The "Deleted" and "Snapshot missing" tooltips spell out the difference
("Pool deleted on YYYY-MM-DD; metadata as of that date." vs. "Pool
metadata not found in `system.compute.instance_pools` — likely deleted
before retention or located in another region. DBU cost is still
accurate."). This preserves cost visibility (no data drop) while making
the degraded attribution visible. The visual language matches the
All-Purpose tab's `__unknown__` user label.

### 3.6 Double-counting across tabs is by design

A pool-backed job cluster contributes to BOTH:

- `dbspend360_total_job_spends` (under the job-cluster pipeline, filtered
  `cluster_source = 'JOB'`)
- `dbspend360_total_pool_spends` (under the new pool pipeline, filtered
  `instance_pool_id IS NOT NULL`)

A pool-backed UI or API (interactive) cluster goes one step further —
it contributes to **all three** tables:

- `dbspend360_total_all_purpose_spends` (filtered
  `cluster_source IN ('UI','API')`)
- `dbspend360_total_pool_spends` (filtered `instance_pool_id IS NOT NULL`)

(and does NOT contribute to the Job Clusters tab — that one stays
`cluster_source = 'JOB'`-only). Three-way overlap is therefore possible
for pool-backed interactive clusters and two-way overlap is the common
case for pool-backed job clusters.

This is **intentional and not a bug.** The three tabs are different lenses
on overlapping compute:

- Job Clusters tab answers "what does this job cost?"
- All-Purpose Clusters tab answers "what does this user's interactive work
  cost?"
- Instance Pools tab answers "what does this pool cost, and which workloads
  drive it?"

Summing across tabs is meaningless and the UI should not encourage it.
Documented in the README under "Cost model" and re-stated in §9 acceptance
criteria.

## 4. New + changed surface area

### 4.1 New files

**Pipeline (Databricks notebooks).** Sibling notebooks; existing pipelines
not touched.

- `jobs/ddls/dbspend360_pool_dbu_cost.ipynb` — DDL for the per-pool /
  per-cluster / per-day DBU table. Keyed on
  `(instance_pool_id, cluster_id, usage_date)`. Columns:
  `instance_pool_id`, `cluster_id`, `usage_date`, `workspace_id`,
  `databricks_cost`, `currency`, `sku_name`, `created_at`, `updated_at`.
- `jobs/ddls/dbspend360_total_pool_spends.ipynb` — DDL for the final
  denormalized rollup. Same key, adds pool metadata
  (`pool_name`; `node_type` — matches the actual column name in
  `system.compute.instance_pools`; `min_idle_instances`, `max_capacity`,
  `idle_instance_autotermination_minutes`), state flags
  (`pool_snapshot_missing BOOLEAN`, `pool_deleted_at TIMESTAMP` — see
  §3.5 three-state badge), the reserved `cloud_cost DOUBLE` (always
  NULL in v1), and `total_cost DOUBLE` (`= databricks_cost` in v1;
  will be `databricks_cost + cloud_cost` in v2). Creator info — neither
  `pool_creator_id` (GUID) nor `pool_creator_user_name` (email) — is
  stored on the table. The §1.5 rationale: the GUID is only available
  via the REST API's `default_tags['DatabricksInstancePoolCreatorId']`
  (the system table's `tags` column is documented "user-defined tags
  ... does not include default tags"), and resolving GUID → email
  requires a second hop through the users API. The pool details modal
  reads the GUID per-request and caches it via `get_pool_metadata`
  (§4.2 / CP6); the list view does not surface creator info at all.
- `jobs/notebooks/dbspend360_pool_dbu_cost_app.ipynb` — pipeline app
  (sibling of `dbspend360_dbu_cost_app.ipynb` and
  `dbspend360_all_purpose_dbu_cost_app.ipynb`). Reuses
  `utils_common.ipynb`. Filters `system.billing.usage` to
  `usage_metadata.instance_pool_id IS NOT NULL`, joins to
  `system.billing.list_prices` for $ conversion, writes per-row
  `(instance_pool_id, cluster_id, usage_date, workspace_id, databricks_cost,
  currency, sku_name)`. `cluster_id = COALESCE(..., '__pool_overhead__')`.
- `jobs/notebooks/pool_spends_app.ipynb` — final rollup app (sibling of
  `databricks_job_spends_app.ipynb` and `all_purpose_spends_app.ipynb`).
  Joins the new DBU table with `system.compute.instance_pools` (collapsed
  via `max_by(col, change_time)` per `instance_pool_id` — matches the
  pattern in `dbspend360_all_purpose_dbu_cost_app.ipynb`; the docs'
  `QUALIFY ROW_NUMBER() OVER ... = 1` alternative is holistically safer
  on tied `change_time` values but breaks consistency with the existing
  pipeline). Denormalizes pool config (`instance_pool_name`, `node_type`,
  `min_idle_instances`, `max_capacity`,
  `idle_instance_autotermination_minutes`) and `delete_time` →
  `pool_deleted_at` (§3.5). **Creator info is intentionally not
  denormalized** — the system table's `tags` column excludes default
  tags, so `tags['DatabricksInstancePoolCreatorId']` is always NULL
  there; v1 resolves the creator GUID per-request in the modal path
  via the REST API (§4.2 / CP6). **No cloud-cost join in v1** —
  `cloud_cost = CAST(NULL AS DOUBLE)`. The notebook's join slot is
  the v2 extension point.

**Backend (FastAPI):**

- `server/routers/instance_pools.py` — new router mounted under
  `/api/instance-pools/*`. Endpoints listed in §6.
- (No new model file; new Pydantic models live alongside existing ones in
  `server/models/job_spend.py` — see §4.2.)

**LLM service:**

- (No new file.) New `analyze_instance_pool_costs()` method and
  `INSTANCE_POOL_ANALYSIS_PROMPT` constant added to
  `server/services/llm_service.py` — see §4.2.

**Frontend (React):**

- `client/src/types/instance-pool.ts` — TypeScript interfaces:
  `InstancePoolDailySpend`, `InstancePoolClusterSpend`,
  `GroupedInstancePool` (with `days: list[InstancePoolDailySpend]`),
  `InstancePoolSummaryMetrics`, `InstancePoolDetails`,
  `InstancePoolAnalysis`, paginated wrappers.
- `client/src/hooks/useInstancePools.ts` — `useInstancePools`,
  `useInstancePoolSummary`, `useTopInstancePools`, `useInstancePoolDetails`,
  `useInstancePoolAnalysis`. Same React Query / `keepPreviousData` /
  prefetch pattern as `useGroupedJobSpends.ts` and
  `useAllPurposeClusters.ts`.
- `client/src/components/InstancePoolsDashboard.tsx` — the parallel
  dashboard (no inner `<Tabs>`; single view per §3.3).
- `client/src/components/InstancePoolsSummaryCards.tsx` — KPI strip: total
  pool DBU spend, distinct pool count, distinct cluster count, top-cost
  pool, count of pools with `pool_snapshot_missing = true` ("orphaned
  pools"). Same `Card` / `Skeleton` styling as `SummaryCards.tsx`.
- `client/src/components/InstancePoolsTable.tsx` — By-Pool table:
  `instance_pool_id`, `pool_name` (with the §3.5 three-state badge
  driven by `pool_snapshot_missing` and `pool_deleted_at`),
  `cluster_count`, `active_days`, `databricks_cost`, `total_cost`.
  **No creator column** — creator info is modal-only in v1 per §3.4 /
  §1.5 (the rollup table doesn't carry the GUID and adding a per-row
  REST API enrichment at list time would defeat the table's caching
  story). Two-level row expansion per §3.3. Render `__pool_overhead__`
  cluster as italicized "Pool overhead".
- `client/src/components/InstancePoolFilterControls.tsx` — same date
  presets + search by pool name / pool id / cluster id. No creator
  search field (the column it would filter against isn't in the rollup
  table; pre-filtering by REST-API-resolved creator on every keystroke
  would be a fan-out anti-pattern).
- `client/src/components/InstancePoolDetailsModal.tsx` — pool details
  modal (parallel to today's `ClusterDetailsModal`-equivalent inside
  `JobBreakdownModal.tsx` / cluster details flow). Renders pool config
  (`min_idle_instances`, `max_capacity`,
  `idle_instance_autotermination_minutes`, `node_type` — matches the
  actual column name in `system.compute.instance_pools`,
  `preloaded_spark_version` (singular), `custom_tags`), the resolved
  creator GUID (from the per-request REST API call described in §4.2 /
  CP6: `client.instance_pools.get(...).default_tags['DatabricksInstancePoolCreatorId']`).
  Renders the GUID as "Creator ID: `{pool_creator_id}`" with a tooltip
  noting that v1 does not resolve to an email (v2 follow-up — see §13);
  renders italicized "Unknown creator" when the REST API returns no
  creator tag (e.g. workspace-system-created pools). Also renders the
  LLM analysis from `/api/instance-pools/{id}/analyze`.

### 4.2 Changed files

- `jobs/ddls/create_all_tables.ipynb` — add the two new DDL notebook names
  to the `DDL_NOTEBOOKS` list so `create_all_tables` provisions them too.
- `jobs/resource_templates/DBSPEND360.yaml` — add two new task entries
  (`Dbspend360_pool_dbu_costs`, `pool_spends`). The first depends on
  `cloud_cost_explorer` (for ordering symmetry with the other two
  pipelines — pool v1 doesn't actually read cloud cost, but keeping
  the dependency edge makes v2 a zero-config change). The trade-off
  is a ~5–15 min serial wait on each manual rerun even though v1
  doesn't use the upstream output; for the daily scheduled run this is
  invisible. The second task depends on the first. The new branch runs
  in parallel with the existing two branches.
- `server/models/job_spend.py` — append 7 new models:
  `InstancePoolDailySpend`, `InstancePoolClusterSpend`,
  `GroupedInstancePool` (with `days: list[InstancePoolDailySpend]`),
  `InstancePoolSummaryMetrics`, `InstancePoolDetails`,
  `InstancePoolAnalysis`, `PaginatedInstancePools`. No edits to
  existing models. (An earlier draft of this plan listed a flat
  `InstancePoolSpend` model as well — it was a leftover from the
  job-cluster shape and is never referenced anywhere else, so it
  has been removed from the type set.)
- `server/services/databricks_service.py` — add ~5 new async methods
  plus a pool-metadata cache. Methods:
  - `get_instance_pools_grouped`, `get_instance_pool_summary_metrics`,
    `get_top_instance_pools`, `get_instance_pool_details`.
  - `_get_batch_pool_days_and_clusters` — one `execute_statement`
    returning rows at the finest grain `(instance_pool_id, usage_date,
    cluster_id)`; the service layer rolls them up into the nested
    `GroupedInstancePool.days` → `InstancePoolDailySpend.clusters` shape
    in Python (per §5.2). Originally drafted as "two result sets in one
    round-trip" but the Databricks SQL Statement Execution API accepts
    exactly one `statement` per request, so the round-trip framing was
    structurally wrong.
  - `get_pool_metadata(pool_id) -> tuple[str, Optional[str]]` — new
    helper that mirrors `get_job_name`'s shape but returns
    `(pool_name, pool_creator_id)`. Lazy `pool_metadata_cache` keyed
    on `instance_pool_id`, populated via a single
    `client.instance_pools.get(...)` call: reads `instance_pool_name`
    for the name slot and `default_tags['DatabricksInstancePoolCreatorId']`
    for the creator-GUID slot. Falls back to
    `(f"Pool {pool_id}", None)` on any failure. Called only from the
    pool-details endpoint (and transitively from the analyze endpoint
    via the cost-summary helper) — **not** from the list endpoint, so
    list-page latency is unaffected. The `creator_user_name` (email)
    field that the original draft of this plan assumed lives on
    `GetInstancePool` does **not** exist in the SDK dataclass; GUID →
    email resolution requires a second hop through the Workspace
    users API and is deferred to v2 (§13).

  In `__init__`, add `self.pool_table_name = app_config.pool_table_name`
  and `self.pool_metadata_cache: Dict[str, tuple[str, Optional[str]]] = {}`.
- `server/services/llm_service.py` — append the new
  `INSTANCE_POOL_ANALYSIS_PROMPT` constant and `analyze_instance_pool_costs`
  async method. **No edits to existing prompts or methods.** Prompt is
  built on top of `CLUSTER_ANALYSIS_SYSTEM_PROMPT` (the config-analysis
  prompt — Overall Rating / Right-Sizing / Cost Savings / Idle Waste
  Risk / Configuration Gaps), not `COST_ANALYSIS_SYSTEM_PROMPT` (the
  run-cost prompt with historical baselines that powers
  `analyze_job_costs`). Pool analysis is a configuration-shape question
  closer to `analyze_cluster_configuration` than to a per-run trend
  analysis. The pool prompt then layers in pool-specific guidance:
  idle-instance config (`min_idle_instances`,
  `idle_instance_autotermination_minutes`) vs observed peak concurrent
  attachment, pool node-type appropriateness given workload mix, ratio
  of distinct clusters to active days, and explicit caveats that idle
  cloud cost is not visible in v1.
- `server/app.py` — `from server.routers.instance_pools import router as
  instance_pools_router` + one `app.include_router(...)` line. **Must be
  inserted before the `StaticFiles` mount at the bottom** — that mount
  catches all unmatched routes and any router added after it is unreachable
  (existing comment in the file calls this out; the all-purpose router
  follows the same rule).
- `server/config/config_loader.py` — add one new property `pool_table_name`
  defaulting to `<schema_name>.dbspend360_total_pool_spends` (mirrors
  exactly how `all_purpose_table_name` is resolved — including the
  `ConfigurationError` if neither it nor `schema_name` is set).
- `config/app.dev.config` (and any sibling env configs) — one new line:
  `pool_table_name = dbspend360.03apr.dbspend360_total_pool_spends`.
  Defaults in `config_loader.py` cover the omitted case; the config line
  is for explicitness.
- `client/src/lib/api-client.ts` — extend the `ApiClient` class with
  `getInstancePools`, `getInstancePoolSummary`, `getTopInstancePools`,
  `getInstancePoolDetails`, `getInstancePoolAnalysis`. Mirrors the existing
  job-cluster and all-purpose methods.
- `client/src/components/Dashboard.tsx` — extend `VALID_TABS` from
  `['job-clusters', 'all-purpose']` to
  `['job-clusters', 'all-purpose', 'instance-pools']`, add a third
  `<TabsTrigger value="instance-pools">Instance Pools</TabsTrigger>` and
  a third `<TabsContent value="instance-pools"><InstancePoolsDashboard
  /></TabsContent>`. The existing `?tab=...` URL-state machinery is reused
  verbatim. Also retitle the page subtitle from "Databricks Job Cost
  Analytics Dashboard" → "Databricks Cost Analytics Dashboard" (the
  current copy is stale with three tabs; the All-Purpose PR left it
  unchanged but it now mislabels the scope).
- `client/src/fastapi_client/` — regenerated by
  `scripts/make_fastapi_client.py` (the watch script does this
  automatically). No hand edits.

### 4.3 Untouched but worth calling out

Reused as-is by the Instance Pools tab:

- `jobs/notebooks/{aws,azure,gcp}_cloud_cost_explorer_app.ipynb` — **not
  touched in v1.** Pool tab is DBU-only.
- `jobs/notebooks/utils_common.ipynb` — all the `get_date_window`,
  `log_audit_run`, `validate_*`, `_safe_append`, `safe_cache`,
  `build_table_fqn` helpers are reused by the new pipeline notebooks
  unchanged.
- `client/src/components/ui/tabs.tsx` — the shadcn Tabs wrapper added by
  the All-Purpose plan (CP8 there) is reused. Adding a third tab is purely
  additive.
- `server/routers/dashboard.py` — untouched. The `/api/cluster/{id}/details`
  and `/api/cluster/{id}/analyze` endpoints are reused as-is when the user
  drills into a specific cluster row inside a pool's per-day expansion (the
  cluster details modal works regardless of how the user navigated to the
  cluster).

## 5. Sample SQL for the new endpoints

### 5.1 `get_instance_pools_grouped()`

One row per pool in the window. Pool metadata is denormalized in the rollup
table, so no live join to `system.compute.instance_pools` is needed at
query time.

```sql
WITH filtered AS (
    SELECT *
    FROM {pool_table_name}
    WHERE usage_date >= '{start_date}'
      AND usage_date <= '{end_date}'
),
pool_level AS (
    SELECT instance_pool_id,
           ANY_VALUE(pool_name)              AS pool_name,
           ANY_VALUE(node_type)              AS node_type,
           ANY_VALUE(min_idle_instances)     AS min_idle_instances,
           ANY_VALUE(max_capacity)           AS max_capacity,
           ANY_VALUE(idle_instance_autotermination_minutes)
             AS idle_instance_autotermination_minutes,
           ANY_VALUE(pool_snapshot_missing)  AS pool_snapshot_missing,
           ANY_VALUE(pool_deleted_at)        AS pool_deleted_at,
           COUNT(DISTINCT cluster_id)        AS cluster_count,
           COUNT(DISTINCT usage_date)        AS active_days,
           SUM(databricks_cost)              AS total_databricks_cost,
           SUM(COALESCE(cloud_cost, 0))      AS total_cloud_cost,
           SUM(total_cost)                   AS total_cost
    FROM filtered
    GROUP BY instance_pool_id
)
SELECT instance_pool_id, pool_name, node_type,
       min_idle_instances, max_capacity,
       idle_instance_autotermination_minutes,
       pool_snapshot_missing, pool_deleted_at,
       cluster_count, active_days,
       total_databricks_cost, total_cloud_cost, total_cost,
       COUNT(*) OVER() AS total_matching
FROM pool_level
{search_clause}
ORDER BY total_cost DESC
LIMIT {limit} OFFSET {offset}
```

`{search_clause}` is the optional outer `WHERE (...)` predicate. The
non-obvious bit: a user can search by `cluster_id`, but `cluster_id` is
not a column in `pool_level` (it's aggregated into
`COUNT(DISTINCT cluster_id)`). Predicating directly on `cluster_id`
would fail with "column not found", so the cluster-id branch uses a
subquery back into `filtered` to keep the outer projection unchanged:

```sql
WHERE (LOWER(pool_name) LIKE LOWER('%{search}%')
       OR instance_pool_id = '{search}'
       OR instance_pool_id IN (
           SELECT DISTINCT instance_pool_id
           FROM filtered
           WHERE cluster_id = '{search}'
       ))
```

Mirrors the existing all-purpose `WHERE (...)`-style search clause
constructed in `get_all_purpose_grouped_by_cluster()`
(`server/services/databricks_service.py:1830`). No creator-GUID
predicate — the rollup table doesn't carry creator info (§4.1).

A second batch query (`_get_batch_pool_days_and_clusters`) fetches the
per-day + per-cluster expansion for the page's `instance_pool_id`s — see
§5.2 for the single-statement design and the Python rollup that lands the
nested shape on the response model.

### 5.2 `_get_batch_pool_days_and_clusters()` — per-day + per-cluster expansion

The [Statement Execution API](https://docs.databricks.com/api/workspace/statementexecution/executestatement)
accepts exactly one `statement` per request and returns one result set —
the existing `_get_batch_job_runs` / `_get_batch_cluster_days` helpers
all hold to this. We follow the same shape: **one `execute_statement`
returning rows at the finest natural grain `(instance_pool_id,
usage_date, cluster_id)`, and the service layer rolls them up per-day
in Python.**

```sql
-- Single batch query at finest grain. Service layer aggregates to days.
SELECT instance_pool_id,
       usage_date,
       cluster_id,
       SUM(databricks_cost)        AS databricks_cost,
       SUM(COALESCE(cloud_cost,0)) AS cloud_cost,
       SUM(total_cost)             AS total_cost
FROM {pool_table_name}
WHERE instance_pool_id IN ({pool_id_list})
  AND usage_date >= '{start_date}' AND usage_date <= '{end_date}'
GROUP BY instance_pool_id, usage_date, cluster_id
ORDER BY instance_pool_id, usage_date, total_cost DESC
```

**Service-layer rollup (sketch):**

```python
from collections import defaultdict

days_by_pool: dict[str, dict[date, InstancePoolDailySpend]] = defaultdict(dict)
for row in rows:
    pool_id, usage_date, cluster_id, dbx, cloud, total = row
    usage_date = date.fromisoformat(usage_date)
    day = days_by_pool[pool_id].setdefault(
        usage_date,
        InstancePoolDailySpend(
            usage_date=usage_date,
            cluster_count_on_day=0,
            databricks_cost=0.0,
            cloud_cost=None,        # v1 reserved
            total_cost=0.0,
            clusters=[],
        ),
    )
    day.databricks_cost += float(dbx or 0.0)
    day.total_cost += float(total or 0.0)
    day.clusters.append(InstancePoolClusterSpend(
        cluster_id=cluster_id,
        databricks_cost=float(dbx or 0.0),
        cloud_cost=None,            # v1 reserved
        total_cost=float(total or 0.0),
    ))
for pool_days in days_by_pool.values():
    for day in pool_days.values():
        day.cluster_count_on_day = len(day.clusters)
```

**Sizing — plan default.** For a hypothetical typical page of 50 pools ×
30-day window × ~5 clusters per pool-day ≈ 7,500 rows, well under the
25 MiB INLINE payload limit.

**Sizing — real-workspace calibration (measured at CP2).** The "~5
clusters per pool-day" baseline above is conservative for workspaces
that use pools as shared job-cluster substrate (every job-cluster
launch reuses pool VMs but gets a fresh `cluster_id`, so distinct
cluster counts inflate quickly). The first workspace exercised by
this pipeline reports these top-5 pools over a 10-day window:

| Pool (id suffix) | Distinct clusters (10d) | Implied clusters/pool-day |
|---|---|---|
| `pool-ksw4stjz` | 2945 | ~295 |
| `pool-xnklijrz` | 204 | ~20 |
| `pool-zrTmEDTT` | 141 | ~14 |
| `pool-iqyomfmn` | 132 | ~13 |
| `pool-mxks2nq7` | 97 | ~10 |

Implication: a 50-pool / 30-day expansion that *includes*
`pool-ksw4stjz` lands in the ~20–40k row region, not the ~7.5k the
default sizing assumes. Still under the 50k warm-fetch trigger below,
but no longer "low thousands". CP6 should re-measure once `_get_batch_
pool_days_and_clusters` is wired and revisit Python-side aggregation
if a 30-day page actually breaches 50k.

**Why this is better than the original two-CTE design.** The §9
invariant "per-day total equals per-cluster sum" becomes **structural**
(computed from the same rows in Python) rather than an asserted
post-condition that could regress. We also save the warehouse RTT.

**Trade-off accepted.** Cardinality scales with `pools_per_page × days
× clusters_per_day` and the service does the per-day SUM in Python
rather than the warehouse. At plan defaults this is in the low
thousands of rows — fast — but the real-workspace calibration above
shows that workspaces with high cluster fanout on shared pools push
this an order of magnitude higher even before hitting the worst case.
Revisit if a 30-day page warm-fetches > 50k rows in practice; the
calibration above puts that threshold in plausible reach, not
theoretical.

### 5.3 `get_instance_pool_summary_metrics()`

Same CTE chain as `get_summary_metrics()` and
`get_all_purpose_summary_metrics()` but parametrized for the pool table and
reports distinct pool, cluster, and orphan-pool counts:

```sql
WITH filtered AS (
    SELECT * FROM {pool_table_name}
    WHERE usage_date >= '{start_date}' AND usage_date <= '{end_date}'
),
pool_day_level AS (
    SELECT instance_pool_id, usage_date,
           SUM(databricks_cost) AS databricks_cost,
           SUM(total_cost)      AS total_cost
    FROM filtered
    GROUP BY instance_pool_id, usage_date
)
SELECT
    (SELECT COUNT(DISTINCT instance_pool_id) FROM filtered) AS total_pools,
    (SELECT COUNT(DISTINCT cluster_id)       FROM filtered) AS total_clusters,
    (SELECT COUNT(DISTINCT instance_pool_id) FROM filtered
       WHERE pool_snapshot_missing = TRUE)                  AS orphaned_pools,
    SUM(total_cost)                                         AS total_spend,
    AVG(total_cost)                                         AS avg_cost_per_pool_day,
    MAX(total_cost)                                         AS max_cost_per_pool_day,
    MIN(total_cost)                                         AS min_cost_per_pool_day,
    SUM(databricks_cost)                                    AS total_databricks_cost
FROM pool_day_level
```

(`total_cloud_cost` is intentionally omitted from the summary in v1 — every
row in the underlying table has `cloud_cost = NULL`, so `SUM(...)` would
always be 0 and the field would be misleading in the KPI strip. The
frontend's `InstancePoolSummaryMetrics` TS interface includes
`total_cloud_cost?: number | null` for v2 forward-compatibility.)

### 5.4 Pipeline aggregation — DBU collection (`dbspend360_pool_dbu_cost_app`)

The crux of the collection notebook. Structurally a sibling of the
`AllPurposeDBUCostClient` already in
`dbspend360_all_purpose_dbu_cost_app.ipynb`, but filters and grouping shift:

```python
# Pool DBU usage: any billing row with a non-null instance_pool_id.
# No cluster_source filter — pool-backed clusters of any source contribute.
usage_df = (
    spark.table("system.billing.usage").alias("usage")
        .filter(
            (F.col("usage.usage_date") >= F.lit(start_dt)) &
            (F.col("usage.usage_date") <= F.lit(end_dt)) &
            (F.col("usage.usage_metadata")["instance_pool_id"].isNotNull())
        )
)
if self.workspace_ids is not None:
    usage_df = usage_df.filter(
        F.col("usage.workspace_id").isin(self.workspace_ids)
    )

list_prices_df = spark.table("system.billing.list_prices").alias("list_prices")

joined = usage_df.join(
    list_prices_df,
    on=(
        (F.col("usage.sku_name") == F.col("list_prices.sku_name")) &
        (F.col("usage.usage_start_time") >= F.col("list_prices.price_start_time")) &
        (
            (F.col("usage.usage_start_time") < F.col("list_prices.price_end_time")) |
            F.col("list_prices.price_end_time").isNull()
        )
    ),
    how="left",
)

agg_df = (
    joined.groupBy(
        F.col("usage.usage_metadata")["instance_pool_id"].alias("instance_pool_id"),
        # Per §3.3 edge case: pool-overhead rows where cluster_id is NULL
        # bucket to '__pool_overhead__' so the row stays accounted for.
        F.coalesce(
            F.col("usage.usage_metadata")["cluster_id"],
            F.lit("__pool_overhead__"),
        ).alias("cluster_id"),
        F.col("usage.usage_date").alias("usage_date"),
        F.col("usage.workspace_id").alias("workspace_id"),
    ).agg(
        F.sum(
            F.col("usage.usage_quantity") *
            F.col("list_prices.pricing")["default"].cast("double")
        ).alias("databricks_cost"),
        F.concat_ws(
            " + ",
            F.array_sort(F.collect_set(F.col("usage.sku_name"))),
        ).alias("sku_name"),
    )
    .withColumn("currency", F.lit("USD"))
)
```

MERGE key (matches the table PK): `t.instance_pool_id = s.instance_pool_id
AND t.cluster_id = s.cluster_id AND t.usage_date = s.usage_date`.

### 5.5 Pipeline rollup — pool metadata denormalization (`pool_spends_app`)

The crux of the rollup notebook. v1 only adds pool metadata; the
cloud-cost join is a deferred extension point:

```python
# SCD-collapse system.compute.instance_pools: pick most-recent metadata
# per instance_pool_id. max_by(col, change_time) avoids dragging the
# full SCD history into the join — matches the pattern in
# dbspend360_all_purpose_dbu_cost_app.ipynb. The docs' canonical
# alternative is QUALIFY ROW_NUMBER() OVER (PARTITION BY
# instance_pool_id ORDER BY change_time DESC) = 1 — holistically
# safer if change_time has ties, but breaks consistency with the
# existing all-purpose pipeline. We accept the same tradeoff here.
#
# Important per-field notes (verified against
# https://docs.databricks.com/aws/en/admin/system-tables/compute):
#   * system.compute.instance_pools has NO `owned_by` column. The
#     auto-applied `DatabricksInstancePoolCreatorId` tag carries the
#     creator GUID, but the system table's `tags` column is documented
#     "User-defined tags for the instance pool (does not include
#     default tags)" — so the auto-tag is NOT visible from
#     system.compute.instance_pools.tags. Reading
#     `tags['DatabricksInstancePoolCreatorId']` would return NULL on
#     every row, so we don't pull it. Creator info is resolved
#     per-request in the modal path via the REST API (see CP6) and
#     never denormalized onto the rollup table.
#   * The actual column is `node_type`, NOT `node_type_id`.
#   * `delete_time` is non-null iff the pool was deleted; the most-recent
#     SCD row carries the delete timestamp. Carry it through as
#     `pool_deleted_at` so the UI can render the "Deleted YYYY-MM-DD"
#     badge from §3.5.
pools_df = spark.sql("""
    SELECT instance_pool_id,
           max_by(instance_pool_name,                  change_time) AS pool_name,
           max_by(node_type,                           change_time) AS node_type,
           max_by(min_idle_instances,                  change_time) AS min_idle_instances,
           max_by(max_capacity,                        change_time) AS max_capacity,
           max_by(idle_instance_autotermination_minutes, change_time)
                                                                    AS idle_instance_autotermination_minutes,
           max_by(delete_time,                         change_time) AS pool_deleted_at
    FROM system.compute.instance_pools
    GROUP BY instance_pool_id
""")

dbu_df = spark.table(self.source_table)  # dbspend360_pool_dbu_cost

joined = (
    dbu_df.alias("d")
    .join(pools_df.alias("p"),
          on=(F.col("d.instance_pool_id") == F.col("p.instance_pool_id")),
          how="left")
    .withColumn("pool_snapshot_missing", F.col("p.pool_name").isNull())
    .withColumn("pool_name",
        F.coalesce(F.col("p.pool_name"),
                   F.concat(F.lit("Pool "), F.col("d.instance_pool_id"))))
    # Creator info intentionally omitted from the rollup table (see the
    # `system.compute.instance_pools.tags` caveat in the SCD-collapse
    # block above). Resolved per-request in the pool details modal
    # path via `client.instance_pools.get(...).default_tags` in CP6.
    .withColumn("pool_deleted_at", F.col("p.pool_deleted_at"))
    # v1: no cloud_cost. Reserved slot for v2.
    .withColumn("cloud_cost", F.lit(None).cast("double"))
    .withColumn("total_cost",
        F.coalesce(F.col("d.databricks_cost"), F.lit(0.0)) +
        F.coalesce(F.col("cloud_cost"),         F.lit(0.0)))
)
```

MERGE key: `(instance_pool_id, cluster_id, usage_date)`.

**No reconciliation invariant in v1** (because there is no cloud-cost
join to reconcile against). For v2, the invariant will be: per
`(instance_pool_id, usage_date)`, `SUM(cloud_cost across clusters)` equals
`dbspend360_pool_cloud_cost_explorer.cloud_cost` ± 0.01 USD.

## 6. New backend endpoints

All under prefix `/api/instance-pools/`, mirroring the existing
`all_purpose_router` shape so the frontend layer can be near-symmetric:

| Method | Path | Response | Mirrors |
|---|---|---|---|
| GET | `/grouped` | `PaginatedInstancePools` | `/api/all-purpose/grouped-by-cluster` |
| GET | `/summary` | `InstancePoolSummaryMetrics` | `/api/all-purpose/summary` |
| GET | `/top-pools` | `list[GroupedInstancePool]` | `/api/all-purpose/top-clusters` |
| GET | `/{id}/details` | `InstancePoolDetails` | `/api/cluster/{id}/details` |
| GET | `/{id}/analyze` | `InstancePoolAnalysis` | `/api/cluster/{id}/analyze` |
| GET | `/health` | `{status, service}` | `/api/all-purpose/health` (smoke test for StaticFiles ordering) |

All paginated/filtered endpoints accept the same `start_date` / `end_date` /
`page` / `per_page` / `search` query parameters as the existing dashboard
endpoints. `_validate_date_range` is duplicated from `all_purpose.py` (small
helper — duplication is preferred over a shared utility module for one
function).

Reused cluster-agnostic endpoints (no change, called from inside the pool
drill-down when a user clicks a specific cluster row):

- `/api/cluster/{id}/details`
- `/api/cluster/{id}/analyze`
- `/api/other-cost-breakdown` (accepts `cluster_id` filter — works for any
  cluster regardless of source)

## 7. Slicing strategy

**Decision (confirmed): single PR on `feat/instance-pools-tab`** —
pipeline + backend + UI ship together. Three alternatives considered:

| Option | Verdict | Tradeoff |
|---|---|---|
| **Single PR** (chosen) | Single review surface; reviewer sees the full vertical and can sanity-check that the pipeline rows the frontend expects actually exist with those names. No intermediate "tab exists but always shows zero rows" state on `main`. Diff is ~18 files / ~1300 LOC (slightly smaller than the all-purpose PR because no cloud-cost work and no By-User view). |
| Three PRs (pipeline → backend → frontend) | Rejected | 3× review overhead; intermediate state on `main` is awkward; same reasoning as `plan_all_purpose_clusters_tab.md` §7. |
| Stacked branches per checkpoint | Rejected | Tooling overhead exceeds benefit at 11 checkpoints. |

The single PR is internally organized as **11 sequential checkpoints**; see
§8. Each checkpoint is self-contained — it lists the minimum files to read
for context, the files to create/modify, the implementation notes that
matter, and explicit exit criteria. A checkpoint can be picked up cold in a
fresh chat session without re-reading the full plan.

## 8. Implementation checkpoints

Conventions used in this section:

- **Read first** — minimum files to load into the chat context before
  starting. Anything else is best looked up on demand.
- **Create / modify** — the new or edited files for that checkpoint.
- **Implementation notes** — the non-obvious decisions / pitfalls.
- **Exit criteria** — concrete, verifiable conditions. Don't move to the
  next checkpoint until all are met.

Do the checkpoints in order; later ones assume earlier ones are complete.

### CP1 — Provision the two new Delta tables

**Goal.** Create the DDL notebooks and run the bootstrap so the empty tables
exist in the dev catalog.

**Read first.**
- `jobs/ddls/dbspend360_all_purpose_dbu_cost.ipynb`
- `jobs/ddls/dbspend360_total_all_purpose_spends.ipynb`
- `jobs/ddls/create_all_tables.ipynb`

**Create / modify.**
- `jobs/ddls/dbspend360_pool_dbu_cost.ipynb` (new) — schema per §4.1.
- `jobs/ddls/dbspend360_total_pool_spends.ipynb` (new) — schema per §4.1;
  includes the reserved `cloud_cost DOUBLE` column and
  `pool_snapshot_missing BOOLEAN`.
- `jobs/ddls/create_all_tables.ipynb` — append both notebook names to the
  `DDL_NOTEBOOKS` list.

**Implementation notes.**
- Both DDLs mirror the existing equivalents in style (widgets, `CLUSTER BY
  AUTO`, `dbutils.notebook.exit` returning the FQN).
- `dbspend360_total_pool_spends` column list (per the §4.1 / §5.5
  resolution against the published `system.compute.instance_pools`
  schema): `instance_pool_id STRING`, `cluster_id STRING`,
  `usage_date DATE`, `workspace_id STRING`, `pool_name STRING`,
  `node_type STRING` (NOT `node_type_id`),
  `min_idle_instances BIGINT`, `max_capacity BIGINT`,
  `idle_instance_autotermination_minutes BIGINT`,
  `pool_snapshot_missing BOOLEAN`, `pool_deleted_at TIMESTAMP`,
  `databricks_cost DOUBLE`, `cloud_cost DOUBLE`, `total_cost DOUBLE`,
  `currency STRING`, `sku_name STRING`, `created_at TIMESTAMP`,
  `updated_at TIMESTAMP`. **No `pool_creator_id` column** — the
  `system.compute.instance_pools.tags` source excludes default tags,
  so denormalization would be a NULL-only column; creator info is
  modal-only via REST API in v1 (§3.4 / §4.1 / CP6).
- `cloud_cost DOUBLE` is included schema-wise but populated as NULL by
  the v1 pipeline. v2 cloud-cost work needs no schema migration.
- No primary-key constraint — uniqueness is enforced by MERGE.

**Exit criteria.**
1. Both notebooks deployed to the dev workspace.
2. Running `create_all_tables` against the dev catalog succeeds and lists
   both new tables as `SUCCESS` in the output.
3. `DESCRIBE TABLE <catalog>.<schema>.dbspend360_total_pool_spends` shows
   the expected columns including `pool_snapshot_missing`,
   `pool_deleted_at`, `node_type`, and `cloud_cost`. Confirms there is
   **no** `pool_creator_id` column (creator info is modal-only via REST
   API per §3.4 / §4.1).
4. Sanity-check the upstream schema with `DESCRIBE TABLE
   system.compute.instance_pools` in the dev workspace; confirm
   `instance_pool_name`, `node_type`, `tags`, `delete_time`,
   `change_time`, `min_idle_instances`, `max_capacity`, and
   `idle_instance_autotermination_minutes` exist with the expected
   types. If any column name differs from the published schema docs
   (which is rare during Public Preview but possible), update the
   §5.5 SCD-collapse SQL before CP3.

### CP2 — Pool DBU collection pipeline

**Goal.** Stand up the per-pool / per-cluster / per-day DBU table.

**Read first.**
- `jobs/notebooks/dbspend360_all_purpose_dbu_cost_app.ipynb` (closest
  template — same shape, sibling filter)
- `jobs/notebooks/utils_common.ipynb` (for `get_date_window`, `validate_*`,
  `safe_cache`, `log_audit_run`, `build_table_fqn`)
- The DDL created in CP1

**Create.**
- `jobs/notebooks/dbspend360_pool_dbu_cost_app.ipynb`

**Implementation notes.**
Structurally identical to `dbspend360_all_purpose_dbu_cost_app.ipynb` but
with these deltas:

- **No `system.compute.clusters` join.** The pool pipeline does not need to
  filter by cluster source — `instance_pool_id IS NOT NULL` is the sole
  filter. This simplifies the join graph compared to the all-purpose
  pipeline.
- Usage filter: `usage_metadata.instance_pool_id IS NOT NULL`.
- Aggregation key: `(instance_pool_id, cluster_id, usage_date, workspace_id)`.
- Project `cluster_id = COALESCE(usage_metadata.cluster_id,
  '__pool_overhead__')`.
- MERGE key: `t.instance_pool_id = s.instance_pool_id AND t.cluster_id =
  s.cluster_id AND t.usage_date = s.usage_date`.
- `TABLE_NAME = "dbspend360_pool_dbu_cost"`.
- SQL per §5.4.

**Exit criteria.**
1. Manual notebook run against dev for a known 30-day window completes with
   non-zero `merged_row_count` (or 0 with explanatory INFO log if the
   workspace genuinely has no pool usage in that window).
2. Spot-check: at least one row exists where `cluster_id =
   '__pool_overhead__'` if the workspace has any pool-overhead billing; or
   confirm via `SELECT COUNT(*) WHERE cluster_id IS NULL` that no NULL
   `cluster_id` rows leaked through.
3. Audit log entry written with `SUCCESS`.
4. Sanity: `SELECT instance_pool_id, COUNT(DISTINCT cluster_id) FROM
   dbspend360_pool_dbu_cost GROUP BY 1 ORDER BY 2 DESC LIMIT 5` returns
   pools with `> 1` distinct cluster (confirming the multi-tenant nature
   §3.4 leans on).

### CP3 — Pool spends rollup pipeline

**Goal.** Denormalize pool metadata onto the DBU table and write the final
rollup.

**Read first.**
- `jobs/notebooks/all_purpose_spends_app.ipynb` (closest template)
- Output of CP2

**Create.**
- `jobs/notebooks/pool_spends_app.ipynb`

**Implementation notes.**
- Structure mirrors `all_purpose_spends_app.ipynb` but **drops the
  cloud-cost join entirely** in v1. The join slot is preserved as a
  commented-out block with a `# TODO(v2): pool cloud cost join goes here`
  marker so v2 lands cleanly.
- `pool_snapshot_missing = pools_df.pool_name IS NULL` (computed before
  the COALESCE that masks the NULL with the fallback name).
- SCD-collapse SQL per §5.5 — pulls pool name and config columns only;
  does **not** read `tags['DatabricksInstancePoolCreatorId']` because
  the `tags` column on `system.compute.instance_pools` excludes default
  tags (the auto-applied creator tag is one of those). Uses
  `node_type` (not `node_type_id`) and carries `delete_time` through as
  `pool_deleted_at` for the §3.5 three-state badge. Creator info is
  resolved per-request in the modal path via the REST API (CP6).
- `cloud_cost = CAST(NULL AS DOUBLE)`.
- `total_cost = COALESCE(databricks_cost, 0) + COALESCE(cloud_cost, 0)` —
  effectively `= databricks_cost` in v1 but written this way so v2 needs
  no code change.
- MERGE key: `(instance_pool_id, cluster_id, usage_date)`.
- **No reconciliation invariant in v1** (see §5.5). The audit-log entry
  records "v1: cloud cost not yet computed" so the absence is visible.

**Exit criteria.**
1. Manual run against dev completes with `SUCCESS`.
2. Row count matches CP2's table 1:1 (the rollup is a denormalization, no
   row inflation): `SELECT COUNT(*) FROM dbspend360_total_pool_spends`
   equals `SELECT COUNT(*) FROM dbspend360_pool_dbu_cost` for the same
   window.
3. At least one row has `pool_snapshot_missing = TRUE` (if the workspace
   has any pre-Oct-2023 deleted pools or cross-region pools per §10) OR
   confirm with `SELECT COUNT(*) WHERE pool_snapshot_missing IS NULL`
   returns 0 (column is always populated, even if all values are
   `FALSE`).
4. If the workspace has any deleted pools whose snapshot is still in
   retention: `SELECT COUNT(*) FROM dbspend360_total_pool_spends WHERE
   pool_deleted_at IS NOT NULL` is non-zero, and those rows have
   `pool_snapshot_missing = FALSE` (deleted-visible state, not
   snapshot-missing state — see §3.5).
5. `SELECT SUM(cloud_cost) FROM dbspend360_total_pool_spends` returns
   `NULL` (v1 invariant — confirms the column is NULL-reserved).

### CP4 — DAB wiring

**Goal.** Make the two new notebooks run as part of the scheduled
`DBSpend360` job.

**Read first.**
- `jobs/resource_templates/DBSPEND360.yaml`

**Modify.**
- `jobs/resource_templates/DBSPEND360.yaml` — append two task entries:
  - `Dbspend360_pool_dbu_costs` (depends on `cloud_cost_explorer` — see
    §4.2 for why we keep this dependency edge even though v1 doesn't read
    cloud cost)
  - `pool_spends` (depends on `Dbspend360_pool_dbu_costs`)

**Implementation notes.**
- Both tasks reuse the workspace path pattern of the existing tasks.
- The new branch (`Dbspend360_pool_dbu_costs` → `pool_spends`) runs in
  parallel with the existing two branches since they share only
  `cloud_cost_explorer`.

**Exit criteria.**
1. `databricks bundle validate` passes.
2. `databricks bundle deploy` updates the dev job.
3. A manual job run from the Workflows UI completes with all six
   downstream tasks `SUCCEEDED` (after this PR the bundle has 1 root
   task `cloud_cost_explorer` plus 6 downstream tasks: 2 each for
   job-cluster, all-purpose, and pool branches).

### CP5 — Backend models + config

**Goal.** Define the new wire-level types and the pool table name
configuration.

**Read first.**
- `server/models/job_spend.py` (esp. the All-Purpose models for shape
  reference)
- `server/config/config_loader.py` (esp. the `all_purpose_table_name`
  property for the pattern to copy)
- `config/app.dev.config`

**Modify.**
- `server/models/job_spend.py` — append 7 new models:
  `InstancePoolDailySpend` (with `clusters: list[InstancePoolClusterSpend]`),
  `InstancePoolClusterSpend`, `GroupedInstancePool` (with `days:
  list[InstancePoolDailySpend]`), `InstancePoolSummaryMetrics`,
  `InstancePoolDetails`, `InstancePoolAnalysis`, `PaginatedInstancePools`.
  Don't touch existing models. (A flat `InstancePoolSpend` model that
  appeared in earlier drafts of this plan is intentionally not in this
  set — it was never referenced as a field type anywhere.)
- `server/config/config_loader.py` — add `pool_table_name` property
  (mirrors `all_purpose_table_name` exactly — explicit config read with
  schema-name-derived default and `ConfigurationError` if neither is set).
- `config/app.dev.config` — add `pool_table_name =
  dbspend360.03apr.dbspend360_total_pool_spends`.
- (Sibling env configs if present — same line.)

**Implementation notes.**
- `cloud_cost: Optional[float] = None` belongs on both
  `InstancePoolDailySpend` and `InstancePoolClusterSpend`. Always None
  in v1; v2-ready.
- `total_cloud_cost: Optional[float] = None` on
  `InstancePoolSummaryMetrics`.
- **No `pool_creator_id` field on `GroupedInstancePool`.** Creator info
  is not denormalized onto the rollup table (per §3.4 / §4.1), so the
  list-shape model doesn't carry it either. `InstancePoolDetails`
  carries `pool_creator_id: Optional[str]` (resolved per-request via
  the REST API in CP6; `None` is legitimate when the REST API call
  fails or the pool has no `DatabricksInstancePoolCreatorId` in
  `default_tags`).
- `pool_creator_user_name` is **not** in this model set in v1 — the
  Python SDK's `GetInstancePool` dataclass does not expose
  `creator_user_name`, only `default_tags`. GUID → email resolution
  is deferred to v2 (§13).
- Three-state snapshot flags on `GroupedInstancePool` and
  `InstancePoolDetails`: `pool_snapshot_missing: bool` and
  `pool_deleted_at: Optional[datetime]` (see §3.5).
- `InstancePoolDetails` exposes pool config:
  `min_idle_instances: Optional[int]`, `max_capacity: Optional[int]`,
  `idle_instance_autotermination_minutes: Optional[int]`,
  `node_type: Optional[str]` (matches the actual column name in
  `system.compute.instance_pools` — NOT `node_type_id`),
  `custom_tags: Optional[dict[str,str]]`,
  `preloaded_spark_version: Optional[str]` (singular — the column is
  `preloaded_spark_version`, not plural).
- **`total_cost` is a plain field, not a computed_field.** The existing
  all-purpose models (`AllPurposeUserSpend`, `GroupedAllPurposeCluster`,
  etc. in `server/models/job_spend.py:346–504`) declare `total_cost`
  as a `@computed_field` derived from `cloud_cost + databricks_cost`.
  The pool models intentionally diverge: in v1 every row has
  `cloud_cost = None`, so a computed `total_cost = cloud_cost +
  databricks_cost` would be incorrect (NoneType arithmetic), and the
  §5.2 Python rollup needs to set/increment `total_cost` directly
  during day-level aggregation. Declare `total_cost: float = 0.0` as
  a regular field on `InstancePoolDailySpend` and
  `InstancePoolClusterSpend` (and as `total_cost: float` on
  `GroupedInstancePool`); plumb it through from the SQL projection in
  §5.1 / §5.2 verbatim.

**Exit criteria.**
1. `uv run python -c "from server.models.job_spend import
   GroupedInstancePool; print(GroupedInstancePool.model_json_schema())"`
   runs without errors.
2. `uv run python -c "from server.config.config_loader import app_config;
   print(app_config.pool_table_name)"` prints the configured FQN.

### CP6 — Backend service methods

**Goal.** Query the new table from `DatabricksService` and add the
pool-details path.

**Read first.**
- `server/services/databricks_service.py` (esp.
  `get_all_purpose_grouped_by_cluster`, `_get_batch_*`,
  `get_all_purpose_summary_metrics`, `get_cluster_details`)
- The models from CP5

**Modify.**
- `server/services/databricks_service.py`:
  - In `__init__`: `self.pool_table_name = app_config.pool_table_name`
    and `self.pool_metadata_cache: Dict[str, tuple[str, Optional[str]]] = {}`.
  - `get_instance_pools_grouped()` — SQL per §5.1; returns
    `PaginatedInstancePools`. **No creator info** in the projection
    (the rollup table doesn't carry it; the list view doesn't render
    it). No REST API enrichment at list time.
  - `get_instance_pool_summary_metrics()` — SQL per §5.3; returns
    `InstancePoolSummaryMetrics`.
  - `get_top_instance_pools()` — top-N by total cost; pool-grain analogue
    of `get_top_jobs`.
  - `_get_batch_pool_days_and_clusters()` — **single `execute_statement`
    at the finest grain `(instance_pool_id, usage_date, cluster_id)`**
    (per §5.2). Service layer rolls per-day in Python; the per-day
    `total_cost` is computed from the per-cluster rows by construction,
    so the §9 #9 invariant is structural rather than asserted. The
    original "two result sets in one round-trip" framing was wrong —
    the Statement Execution API takes one statement per request.
  - `get_instance_pool_details(pool_id)` — reads pool config from
    `system.compute.instance_pools` (most-recent snapshot via
    `max_by(col, change_time)` per field; uses `node_type` not
    `node_type_id`; intentionally does **not** read `tags` for creator
    info because the system table's `tags` column excludes default
    tags per §10). Then enriches creator GUID by calling
    `await self.get_pool_metadata(pool_id)`, which reads
    `default_tags['DatabricksInstancePoolCreatorId']` from the REST
    API response. Returns a sentinel
    `InstancePoolDetails(instance_pool_id=pool_id,
    pool_snapshot_missing=True, ...)` if no system-table snapshot row
    exists. Even in the sentinel path, attempts the REST API call so
    a deleted pool whose snapshot is missing can still surface a
    creator GUID (and pool name) if Databricks' instance-pools REST
    API still tracks it.
  - `get_pool_metadata(pool_id)` — new helper that mirrors
    `get_job_name`'s caching shape but returns a tuple instead of a
    scalar. Lazy `pool_metadata_cache` keyed on `instance_pool_id`,
    populated via `client.instance_pools.get(...)`. Reads
    `instance_pool_name` for the name slot and
    `default_tags.get('DatabricksInstancePoolCreatorId')` for the
    creator-GUID slot. Returns `(pool_name, pool_creator_id)`. Falls
    back to `(f"Pool {pool_id}", None)` on any failure. Safe to call
    from the request path (cached after first call, including the
    fallback case so a failing pool ID doesn't re-issue the REST API
    on every render). Note: the SDK call
    `self.client.instance_pools.get(...)` is synchronous; this method
    follows the same `async def` / sync-body pattern as `get_job_name`.

**Exit criteria.**
1. Each new method has at least one happy-path call manually exercised via
   `uv run python -c` against dev data.
2. `_get_batch_pool_days_and_clusters` returns days such that, by
   construction (the Python rollup sums the same per-cluster rows),
   `sum(c.total_cost for c in day.clusters) == day.total_cost` for every
   `(pool, day)` pair (± floating-point tolerance).
3. `get_instance_pool_details('made-up-id-12345')` returns a result with
   `pool_snapshot_missing=True` and no exception (sentinel path works).
4. `get_pool_metadata('made-up-id-12345')` returns `('Pool
   made-up-id-12345', None)` and is cached so a second call does not
   re-issue the REST API request. Validate by reading
   `service.pool_metadata_cache` after the call.
5. For a known active pool: `get_pool_metadata(<real_id>)` returns the
   pool name and a non-None creator **GUID** (not email — v1 stops at
   the GUID per §1.5 / §3.4). The GUID should match
   `default_tags['DatabricksInstancePoolCreatorId']` on a direct
   `client.instance_pools.get(<real_id>)` call.

### CP7 — Backend router, LLM analysis method, and app wiring

**Goal.** Expose the new endpoints under `/api/instance-pools/*` and ship
the pool-tuned LLM analysis.

**Read first.**
- `server/routers/all_purpose.py` (the patterns to mirror)
- `server/routers/dashboard.py` (esp. `/api/cluster/{id}/analyze` for the
  LLM endpoint shape)
- `server/services/llm_service.py` (esp.
  `analyze_cluster_configuration` for the method shape)
- `server/app.py` (esp. the `StaticFiles` mount comment block)

**Create / modify.**
- `server/routers/instance_pools.py` (new) — 6 endpoints per §6, mirroring
  the validation / error-handling style of `all_purpose.py`. Router
  instance: `router = APIRouter(prefix="/api/instance-pools",
  tags=["instance-pools"])`.
- `server/services/llm_service.py` — append
  `INSTANCE_POOL_ANALYSIS_PROMPT` and
  `analyze_instance_pool_costs(pool_details: InstancePoolDetails,
  cost_summary: dict) -> InstancePoolAnalysis`. The prompt:
  - Builds on `CLUSTER_ANALYSIS_SYSTEM_PROMPT` (the config-analysis
    prompt at `server/services/llm_service.py:95`), not
    `COST_ANALYSIS_SYSTEM_PROMPT`. Pool analysis is shaped like a
    cluster configuration analysis (right-sizing, idle-waste,
    config-gap framing) rather than a run-cost trend analysis with
    historical baselines.
  - Replaces the per-section guidance with pool-specific guidance: idle
    config (`min_idle_instances` vs observed peak concurrent attached
    clusters), `idle_instance_autotermination_minutes` vs observed
    idle-to-attach time, `node_type` (NOT `node_type_id`)
    appropriateness given the SKU mix of attached clusters, ratio of
    distinct clusters to active days. Render the pool creator as
    "Creator ID: `{pool_creator_id}`" using the GUID from CP6's
    `get_pool_metadata`; render italicized "Unknown creator" when the
    GUID is None. (No email rendering — v1 stops at the GUID per
    §1.5; v2 follow-up adds GUID → email resolution via the users
    API, see §13.)
  - Explicit caveat in the prompt: "cloud VM cost (including idle
    capacity) is not visible to this v1 analysis — your recommendations
    must be qualified accordingly and the dollar-impact estimates must
    use DBU cost only."
  - Output structure identical to existing `analyze_cluster_configuration`
    analysis (5 sections: Overall Rating, Right-Sizing Assessment,
    Cost Savings Opportunities, Idle Waste Risk, Configuration Gaps;
    ≤3 recommendations).
- `server/app.py` — import the new router and call
  `app.include_router(...)` **above** the `StaticFiles` mount. Pattern:
  the existing `all_purpose_router` include line is the model.

**Implementation notes.**
- Reuse `get_databricks_service()` lazy initializer pattern from
  `all_purpose.py`; do not create a third instance.
- Each endpoint validates `start_date <= end_date` and returns
  `HTTPException(500)` on service exceptions. `_validate_date_range` is
  copy-pasted from `all_purpose.py` (one-function duplication is preferred
  over a shared helper module).
- The `/health` endpoint exists for the same reason it does in
  `all_purpose.py` — smoke-test that StaticFiles ordering is correct.

**Exit criteria.**
1. `nohup ./watch.sh > /tmp/databricks-app-watch.log 2>&1 &` starts
   cleanly (check log for `Application startup complete.`).
2. Per the FastAPI verification protocol in `CLAUDE.md`, all 6 endpoints
   return 200 with the expected JSON shape:
   ```bash
   curl -s "http://localhost:8000/api/instance-pools/health" | jq
   curl -s "http://localhost:8000/api/instance-pools/summary?start_date=2026-05-01&end_date=2026-05-31" | jq
   curl -s "http://localhost:8000/api/instance-pools/grouped?start_date=...&end_date=...&page=1&per_page=10" | jq
   curl -s "http://localhost:8000/api/instance-pools/top-pools?start_date=...&end_date=...&limit=5" | jq
   curl -s "http://localhost:8000/api/instance-pools/{pool_id}/details" | jq
   curl -s "http://localhost:8000/api/instance-pools/{pool_id}/analyze" | jq
   ```
3. `total_count` from paginated endpoint equals `COUNT(*)` from the
   equivalent group-level SQL run directly against the warehouse.
4. The `/{pool_id}/analyze` response includes the v1 cloud-cost caveat
   somewhere in the analysis text (smoke test that the prompt's caveat
   instruction is being honored by the model).

### CP8 — Frontend Dashboard tab extension

**Goal.** Add the third top-level tab to `Dashboard.tsx` with a
placeholder, without changing any existing behavior.

**Read first.**
- `client/src/components/Dashboard.tsx`
- `client/src/components/ui/tabs.tsx`

**Modify.**
- `client/src/components/Dashboard.tsx`:
  - Extend `VALID_TABS` to `['job-clusters', 'all-purpose',
    'instance-pools'] as const`.
  - Add a third `<TabsTrigger value="instance-pools">Instance
    Pools</TabsTrigger>`.
  - Add a third `<TabsContent value="instance-pools" className="mt-0">`
    with a placeholder `<div>Coming next</div>`.
  - **No edits to** `readTabFromUrl`, `handleTabChange`, or any other
    machinery — the existing URL state code is generic over the
    `VALID_TABS` set.

**Implementation notes.**
- This is the smallest possible change before CP10 wires the real
  dashboard. Keeps CP8 from breaking the build while CP9/CP10 are still
  in flight.

**Exit criteria.**
1. Watch script picks up the change with no TS errors.
2. Visual diff (Playwright screenshot before vs after) of the Job
   Clusters and All-Purpose Clusters tabs shows identical pixels.
3. Clicking the (placeholder) Instance Pools tab swaps the panel without
   a network call or page reload.
4. Refresh on `?tab=instance-pools` lands back on the Instance Pools tab.

### CP9 — Frontend types + API client + hooks

**Goal.** Make the new endpoints addressable from React.

**Read first.**
- `client/src/types/all-purpose.ts`
- `client/src/lib/api-client.ts`
- `client/src/hooks/useAllPurposeClusters.ts`

**Create / modify.**
- `client/src/types/instance-pool.ts` (new) — TS interfaces mirroring
  CP5's Pydantic models.
- `client/src/lib/api-client.ts` — append `getInstancePools`,
  `getInstancePoolSummary`, `getTopInstancePools`,
  `getInstancePoolDetails`, `getInstancePoolAnalysis`.
- `client/src/hooks/useInstancePools.ts` (new) — React Query hooks
  mirroring the all-purpose shapes: `useInstancePools`,
  `useInstancePoolSummary`, `useTopInstancePools`,
  `useInstancePoolDetails`, `useInstancePoolAnalysis`. Use
  `keepPreviousData` + prefetch like the existing hooks.

**Exit criteria.**
1. `tsc --noEmit` (via the watch script) passes with no errors.
2. From the browser console (with the watch server running):
   `await fetch('/api/instance-pools/summary?...').then(r => r.json())`
   returns data that satisfies the new TS interfaces.

### CP10 — Frontend InstancePoolsDashboard UI

**Goal.** Render the Instance Pools tab with the summary cards, the
By-Pool table with two-level expansion, and the pool details / LLM
analysis modal.

**Read first.**
- `client/src/components/AllPurposeDashboard.tsx` (closest parallel,
  but `<Tabs>` shell is dropped — single view here per §3.3)
- `client/src/components/AllPurposeClustersTable.tsx` (for the
  expandable-row pattern)
- `client/src/components/AllPurposeSummaryCards.tsx`,
  `AllPurposeClusterFilterControls.tsx`
- `client/src/components/JobBreakdownModal.tsx` (for the modal pattern
  and LLM-rendering layout)

**Create / modify.**
- `client/src/components/InstancePoolsDashboard.tsx` (new) — single
  view: filter controls on top, summary cards, By-Pool table. No inner
  `<Tabs>`.
- `client/src/components/InstancePoolsSummaryCards.tsx` (new) — KPI
  strip: total pool DBU spend, distinct pool count, distinct cluster
  count, top-cost pool, count of orphaned pools.
- `client/src/components/InstancePoolsTable.tsx` (new) —
  By-Pool table with **two-level row expansion**:
  - Level 1 (pool row → per-day): clicking expands to show daily
    `databricks_cost` / `cluster_count_on_day` / `total_cost` rows.
  - Level 2 (day row → per-cluster): clicking a day expands to show
    per-cluster rows; each cluster row is clickable and opens the
    existing cluster details modal (reused — `/api/cluster/{id}/details`
    and `/api/cluster/{id}/analyze`).
  - **Per-cluster row cap inside the day expansion.** Render at most
    the **top 25 clusters by `total_cost`** for the expanded day. The
    `InstancePoolDailySpend.clusters` array is already sorted by
    `total_cost DESC` per §5.2 SQL, so the cap is a simple `slice(0,
    25)` plus an "Other clusters (N) — $X total" rollup row when
    `clusters.length > 25`. The rollup row is non-expandable (no
    cluster modal). Justification: the §5.2 real-workspace calibration
    shows a single busy shared pool (e.g. `pool-ksw4stjz`) can attach
    ~295 distinct clusters per day; rendering 295 rows inside a
    nested table expansion is unusable. The top-25 cap covers the
    long-tail-dominated-by-head case that pool-share-of-cost
    typically exhibits, and the rollup row preserves arithmetic
    integrity (sum of visible + Other == day total).
  - Pool name badge per §3.5: no badge when active; yellow
    "Deleted YYYY-MM-DD" badge (formatted from `pool_deleted_at`) when
    set; yellow "Snapshot missing" badge when `pool_snapshot_missing`.
  - Pool name itself is clickable and opens
    `InstancePoolDetailsModal` (the **pool** modal, distinct from the
    cluster modal).
  - **No creator column.** Per §3.4 / §4.1, the rollup table does not
    carry creator info, and per-row REST API enrichment at list time
    would defeat the table's caching story. The pool details modal
    is the only surface that exposes creator info in v1.
  - `__pool_overhead__` cluster → italicized "Pool overhead".
- `client/src/components/InstancePoolFilterControls.tsx` (new) — date
  presets + search by pool name / pool id / cluster id. **No creator
  search field** (the rollup table doesn't carry creator info and the
  list endpoint doesn't enrich per request; see §5.1 search-clause
  notes and §4.1 filter-controls description).
- `client/src/components/InstancePoolDetailsModal.tsx` (new) — modal
  rendering pool config (`min_idle_instances`, `max_capacity`,
  `idle_instance_autotermination_minutes`, `node_type` —
  matches the actual column name, NOT `node_type_id`;
  `preloaded_spark_version` (singular), `custom_tags`) plus the
  resolved creator GUID from `InstancePoolDetails.pool_creator_id`
  (populated server-side via CP6's `get_pool_metadata` →
  `client.instance_pools.get(...).default_tags['DatabricksInstancePoolCreatorId']`).
  Rendered as "Creator ID: `{pool_creator_id}`" with a tooltip
  "Databricks-internal user GUID. Resolving to email is a v2
  follow-up (see README)." Falls back to italicized "Unknown
  creator" when the GUID is None (REST API call failed, or the pool
  has no `DatabricksInstancePoolCreatorId` in `default_tags`).
  Also renders the LLM analysis from
  `/api/instance-pools/{id}/analyze`. Renders a different info banner
  for each §3.5 state at the top: nothing when active; a yellow banner
  "Pool deleted on YYYY-MM-DD. Configuration shown is as of the delete
  time." when `pool_deleted_at` is set; "Pool metadata unavailable.
  Cost figures remain accurate; configuration analysis is disabled."
  when `pool_snapshot_missing`.
- `client/src/components/Dashboard.tsx` — replace the `instance-pools`
  placeholder with `<InstancePoolsDashboard />`.

**Implementation notes.**
- Two-level expansion state is managed in the row component with two
  `Set<string>`-shaped pieces of local state (`expandedPools`,
  `expandedDays`) — same `Set`-keyed pattern as the existing
  `GroupedJobTable.tsx`. Don't pull in a tree-table library.
- The cluster details modal opened from a cluster row inside the pool
  drill-down is the existing modal; do not duplicate it.
- The pool details modal (`InstancePoolDetailsModal`) is **new** and
  separate from the cluster details modal — they have different
  underlying data shapes.

**Exit criteria.**
1. Playwright walk: Open app → click "Instance Pools" → see summary
   cards with non-zero values → expand first pool row → see daily
   breakdown → expand first day → see per-cluster breakdown → click a
   cluster row → cluster details modal opens with existing LLM analysis.
2. Click a pool name → pool details modal opens, shows pool config and
   pool-tuned LLM analysis text (verify the v1 cloud-cost caveat
   appears). The "Creator ID:" field shows a GUID for at least one
   known-active pool (sourced from the REST API's `default_tags`),
   and "Unknown creator" appears in italics for a synthetic
   nonexistent pool ID.
3. "Snapshot missing" badge renders on pool rows where
   `pool_snapshot_missing = true` (verify against known orphaned pools
   in dev, or wait for one to appear).
4. No creator column appears in the table header or rows (regression
   guard against the dropped column).
5. No console errors.

### CP11 — Deploy + post-deploy verification

**Goal.** Ship to Databricks Apps and confirm health per the `CLAUDE.md`
protocol.

**Steps.**

1. `./deploy.sh`.
2. `uv run python dba_logz.py <app-url> --search "Application startup
   complete\|Uvicorn running" --duration 60`.
3. If startup messages don't appear, rerun without the search filter and
   fix any exceptions before proceeding.
4. `uv run python dba_client.py <app-url> /api/instance-pools/health`.
5. `uv run python dba_client.py <app-url>
   /api/instance-pools/summary?start_date=...&end_date=...`.
6. `uv run python dba_client.py <app-url>
   /api/instance-pools/grouped?start_date=...&end_date=...&page=1&per_page=10`.
7. `uv run python dba_client.py <app-url>
   /api/instance-pools/top-pools?start_date=...&end_date=...&limit=5`.
8. Pick one `instance_pool_id` from the previous response and run:
   `uv run python dba_client.py <app-url>
   /api/instance-pools/<pool_id>/details` — verify the
   `pool_creator_id` field is populated (GUID from
   `default_tags['DatabricksInstancePoolCreatorId']`) for at least one
   known-active pool.
9. `uv run python dba_client.py <app-url>
   /api/instance-pools/<pool_id>/analyze` — verify the response
   includes the v1 cloud-cost caveat string (smoke test that the
   prompt rules from CP7 are being honored in production too).

**Exit criteria.**
1. Log stream shows `Application startup complete.` and `Uvicorn
   running` with no exceptions.
2. All 6 endpoints return 200 (`/health`, `/summary`, `/grouped`,
   `/top-pools`, `/{id}/details`, `/{id}/analyze`); paginated/aggregate
   endpoints return non-zero data for the workspace's 30-day window
   (if the workspace has any pool usage in that window — 0 is a
   legitimate state and the pipeline logs an explanatory INFO message).
3. `/{id}/details` returns a populated `pool_creator_id` GUID for at
   least one active pool, confirming the REST API enrichment from CP6
   is wired correctly in the deployed app.
4. Manual smoke in browser: Instance Pools tab loads and renders
   end-to-end with real production data — at least one pool row
   expands to show per-day, at least one day expands to show
   per-cluster, and the pool details modal opens with the Creator ID
   field populated.

## 9. Acceptance criteria

1. **No regression on existing tabs.** Every URL, endpoint response
   shape, and rendered UI element under Job Clusters and All-Purpose
   Clusters is byte-identical to before the change (visual diff). The
   `claude_scripts/` test scripts for the existing tabs continue to pass
   unchanged.
2. **Tab navigation works.** Selecting "Instance Pools" swaps the panel
   without a full page reload; the other two tabs continue to swap
   independently. URL state for current tab is preserved on refresh
   (`?tab=instance-pools`).
3. **Data correctness — pool filter.** Every row in
   `dbspend360_total_pool_spends` has a non-null `instance_pool_id`.
   Asserted in `claude_scripts/test_instance_pools_filter.py`.
4. **Data correctness — overlap with other tabs is expected (§3.6).**
   The test script `claude_scripts/test_instance_pools_overlap.py`
   explicitly confirms that some `(cluster_id, usage_date)` pairs DO
   appear in both `dbspend360_total_pool_spends` and
   `dbspend360_total_job_spends` (or `dbspend360_total_all_purpose_spends`)
   when the workspace runs pool-backed clusters. This is the inverse of
   the All-Purpose tab's "disjoint" assertion and is documented as
   intentional.
5. **Row-count integrity.**
   `COUNT(*) FROM dbspend360_total_pool_spends` equals
   `COUNT(*) FROM dbspend360_pool_dbu_cost` for the same window (the
   rollup is a denormalization, no row inflation).
6. **`cloud_cost` v1 invariant.**
   `SELECT COUNT(*) FROM dbspend360_total_pool_spends WHERE cloud_cost
   IS NOT NULL` returns 0. Asserted in
   `claude_scripts/test_instance_pools_cloud_cost_reserved.py`. (This
   test will need to be updated when v2 lands — explicit guard against
   accidental partial-cloud-cost writes.)
7. **Three-state snapshot handling (per §3.5).** Every row with
   `pool_snapshot_missing = TRUE` has `pool_name LIKE 'Pool %'` (the
   fallback projection from §5.5) AND `pool_deleted_at IS NULL` (when
   the snapshot row is missing, we have no `delete_time` to read).
   Every row with `pool_deleted_at IS NOT NULL` has
   `pool_snapshot_missing = FALSE` (the snapshot is still present,
   just for a deleted pool). `pool_snapshot_missing` is never NULL
   (column is always populated, even if all rows are FALSE). UI renders
   the appropriate badge per the §3.5 state table: no badge when
   active, "Deleted YYYY-MM-DD" when `pool_deleted_at` is set,
   "Snapshot missing" when `pool_snapshot_missing = TRUE`. (The
   pre-rewrite version of this criterion keyed off
   `pool_creator_id IS NULL` — that field no longer exists on the
   rollup table per §4.1, so the invariant has been restated in
   terms of `pool_snapshot_missing` and `pool_name LIKE 'Pool %'`
   only, which is both stricter and more directly tied to the
   §5.5 pipeline projection.)
8. **New endpoint contracts.** Each of the 6 new endpoints returns 200
   with the documented Pydantic shape on a populated window.
   `total_count` on the paginated endpoint matches `COUNT(*)` of the
   underlying group-level CTE.
9. **Two-level drill-down works.** The By-Pool table's `days` array on
   each `GroupedInstancePool` row, when summed, equals the row's
   top-level `total_cost` (± 0.01 USD; subject to multi-day vs
   single-query rounding). Each `InstancePoolDailySpend.clusters`
   array's summed `total_cost` equals that day's `total_cost`
   **structurally** under the §5.2 single-finest-grain rollup design
   (the per-day totals are computed in Python by summing the same rows
   the per-cluster array exposes), not via a separate post-condition.
   The structural invariant is still asserted in
   `claude_scripts/test_instance_pool_drill_down.py` as a guard against
   future drift in the rollup helper.
10. **LLM analysis behavior.** `/api/instance-pools/{id}/analyze` returns
    a 4-section analysis with pool-specific recommendations. The
    response includes an explicit v1 cloud-cost caveat (asserted via
    string contains in `claude_scripts/test_instance_pool_analysis.py`).
11. **Deploy health.** Deployed app log stream shows `Application
    startup complete.` / `Uvicorn running` with no exceptions. Live curl
    against `/api/instance-pools/summary?start_date=...&end_date=...`
    returns non-zero `total_pools` and `total_clusters` for the live
    workspace's 30-day window (provided the workspace uses pools).

## 10. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Workspace genuinely has no instance pools → tab ships with 0 rows everywhere, looks broken | Medium | Pipeline writes an `INFO` log on `merged_row_count == 0` with the hint "No pool usage found. Verify there exists `system.billing.usage` data with `usage_metadata.instance_pool_id IS NOT NULL` in the window." Frontend renders an empty-state message ("No pool usage in this window. Pools may not be in use, or the date range is too narrow."). Don't fail the pipeline — `0` is a legitimate state. |
| Users expect cloud cost (idle and active) on Day 1 and find the always-NULL column confusing | Medium-High | (a) Don't render the column at all in v1 (the TS interface includes it as `cloud_cost?: number \| null`; the table simply omits the column when every value is null). (b) README "Instance Pools — what's tracked" section explicitly states "v1: DBU only. Idle and active cloud VM cost is a v2 follow-up." (c) The LLM analysis prompt includes the same caveat. |
| Double-counting confusion — user sees pool cost in Instance Pools tab AND the same cluster's cost in Job Clusters tab, assumes a bug | Medium | (a) README explicitly documents the "three lenses on overlapping compute" model from §3.6. (b) Each tab's summary card strip has an info icon with hover text: "This view is scoped to {scope}. Costs may overlap with other tabs — see README for details." |
| Pool snapshot missing for most pools (large workspace with churn) → "Unknown" / "Snapshot missing" everywhere | Low-Medium | The fallback IS the behavior — DBU cost is still accurate even when metadata is lost. README calls this out. If proportion of orphaned pools is alarming, the summary KPI card surfaces the orphan count so the user can see at a glance. |
| The `StaticFiles` mount in `server/app.py` accidentally swallows `/api/instance-pools/*` | Low — easy to catch | Insert the new `app.include_router(...)` **above** the `StaticFiles` mount, matching the existing `all_purpose_router` line. The `/api/instance-pools/health` endpoint exists specifically as a smoke test for this. |
| `system.compute.instance_pools` columns mismatch (resolved against authoritative docs) | Resolved at plan time | The [Databricks compute system tables reference](https://docs.databricks.com/aws/en/admin/system-tables/compute) confirms the actual columns: `instance_pool_name`, `node_type` (NOT `node_type_id`), `min_idle_instances`, `max_capacity`, `idle_instance_autotermination_minutes`, `delete_time`, `change_time`, `tags` (map), `preloaded_spark_version` (singular). There is **no `owned_by` column**. Critically, the `tags` column is documented as **"User-defined tags for the instance pool (does not include default tags)"** — so the Databricks-auto-applied `DatabricksInstancePoolCreatorId` tag is **not** visible in this column, even though it is a real tag on the cloud instances. An earlier draft of this plan tried to denormalize `tags['DatabricksInstancePoolCreatorId']` into the rollup as `pool_creator_id`; that projection would have returned NULL on every row. Resolution: drop creator denormalization entirely (no list-view column), resolve the GUID only inside the pool details modal via the REST API's `default_tags` map on `GetInstancePool` (§3.4, §4.1, §4.2, §5.5, CP6). Separately, the Python SDK's `GetInstancePool` dataclass has no `creator_user_name` field — only `default_tags` — so v1 surfaces the GUID without resolving to email; v2 follow-up does the second hop through the Workspace users API (§13). CP3 still runs `DESCRIBE TABLE` as a sanity check before merging, since the schema is Public Preview. |
| `system.compute.instance_pools` is Public Preview, and (like `system.compute.clusters`) the table is regional. Multi-region workspaces will see inflated "Snapshot missing" counts in the §4.1 KPI card because billing rows reference pools whose snapshots live in another region | Medium for multi-region accounts; Low otherwise | (a) Pipeline's `max_by` SCD-collapse only references columns we use, so additive Preview schema changes are no-ops. README "Pool snapshot lookups are scoped to the warehouse's region; cross-region pool snapshots render as 'Snapshot missing' until queried from their home region." (b) Tooltip on the orphaned-pools KPI card calls this out explicitly. (c) If/when multi-region is in scope, v2 follow-up: run the pool pipeline per region and UNION ALL into a single rollup. Captured in §13. |
| Pool DBU rows with NULL `cluster_id` (the `__pool_overhead__` bucket) confuse users in the per-cluster drill-down | Low | UI explicitly renders `__pool_overhead__` as italicized "Pool overhead" with a tooltip explaining "DBU charged at the pool level, not attributable to a specific cluster." |
| Auto-generated TS client (regenerated from the new OpenAPI spec) shadows or breaks existing types | Low | Same as the All-Purpose plan: the generator emits everything under `client/src/fastapi_client/`. Existing components import from `@/types/*` and `@/lib/api-client` rather than the generated client, so additions to the generated dir are additive-only. |
| The pool-tuned LLM analysis ignores the v1 cloud-cost caveat in its output, leading to dollar-impact claims that include phantom idle savings | Low-Medium | Test asserted explicitly in CP7 exit criteria #4 and acceptance criterion #10. If the model regresses, tighten the prompt's caveat language (the prompt already cites it as a "strict rule"). |

## 11. Rollback

Per-layer rollback, in priority order:

1. **UI bug only** — git revert the frontend commits. Backend + pipeline
   stay, tab disappears, no data harmed.
2. **Backend regression** — git revert the `app.py` `include_router`
   line; the new router becomes 404 but the rest of the app is
   untouched.
3. **Pipeline data quality** — `dbspend360_total_pool_spends` and
   `dbspend360_pool_dbu_cost` are new Delta tables; can be `DROP TABLE`
   + rerun after fixing the notebook. No migration of existing tables,
   so worst case is "drop the two new tables and the audit log entries
   for the two new pipeline names".
4. **LLM prompt regression** — git revert the prompt diff in
   `llm_service.py`; the analyze endpoint goes back to its prior
   behavior (or to a 500 if the method itself is reverted). No data
   harmed.

No data migration on existing tables. Rollback is fully reversible.

## 12. Effort estimate

~10–12 hours total, broken down per checkpoint:

| Checkpoint | Hours | Notes |
|---|---|---|
| CP1 — DDLs + register | 0.5 | Two small files mirroring existing DDLs |
| CP2 — DBU collection pipeline | 1 | Simpler than all-purpose (no cluster-source filter / no SCD join in the collection stage) |
| CP3 — Pool spends rollup pipeline | 1 | Simpler than all-purpose (no cloud cost join in v1; just pool-metadata denormalization) |
| CP4 — DAB wiring + dev end-to-end run | 1 | Pipeline must run end-to-end before backend can be tested with real data |
| CP5 — Models + config | 0.5 | Append-only |
| CP6 — Service methods | 1.5 | Two-level batch query (`_get_batch_pool_days_and_clusters`) is the novel piece |
| CP7 — Router + LLM method + curl verification | 1.5 | Includes new LLM prompt; per CLAUDE.md FastAPI verification protocol |
| CP8 — Dashboard tab extension | 0.25 | Single-line change to `VALID_TABS` plus one trigger + one content panel |
| CP9 — Types + api-client + hooks | 0.75 | Pattern-following |
| CP10 — Instance Pools UI (summary + table + filter controls + pool details modal) | 2 | Two-level row expansion is the novel piece; modal pattern is reused |
| CP11 — Deploy + dba_logz monitoring + live curl | 0.75 | Standard deploy flow |
| Buffer | 1 | Pool column-name reconciliation (per §10 risk), unexpected SCD shape, type-error cleanup |

## 13. Out of scope, captured for follow-up

- **Cloud cost integration (v2).** Extend
  `{aws,azure,gcp}_cloud_cost_explorer_app.ipynb` to also group cloud
  costs by the `DatabricksInstancePoolId` tag. New
  `dbspend360_pool_cloud_cost_explorer` table (or extension of the
  existing `dbspend360_cloud_cost_explorer` to a
  `(cluster_id, instance_pool_id)` composite key). The pool rollup
  notebook gains a cloud-cost join (the slot is already commented in
  `pool_spends_app.ipynb` per CP3). Frontend table un-hides the
  `cloud_cost` column. LLM prompt's v1 caveat is removed. Reconciliation
  invariant from §5.5 is asserted.
- **Idle-instance cost as first-class column (v2).** Two candidate
  paths, each independent:
  - **(v2a) Via the cloud-cost explorers** — extend
    `{aws,azure,gcp}_cloud_cost_explorer_app.ipynb` to group by the
    `DatabricksInstancePoolId` tag, then classify pool cloud cost into
    `active_cloud_cost` (a row has a `cluster_id` attributable match in
    `system.billing.usage`) and `idle_cloud_cost` (pool-tagged cloud
    cost with no matching active billing). Same scope as the current
    v2 cloud-cost item above. Most rigorous; biggest blast radius.
  - **(v2b) Via `system.compute.instance_events`** (Public Preview,
    documented in the [compute system tables reference](https://docs.databricks.com/aws/en/admin/system-tables/compute)).
    Computes per-instance `idle_minutes` (state =
    `INSTANCE_READY`) and `active_minutes` (state = `INSTANCE_PLACED`)
    directly from state transitions, with `instance_pool_id` populated
    on every event. Multiply `idle_minutes` × `node_type` cost (from
    `system.compute.node_types` × cloud-provider on-demand list price)
    for an idle-cost approximation that doesn't touch the cloud-cost
    explorers at all. Less rigorous than v2a (uses list price, not
    actual billed cost), but materially smaller scope and works on
    workspaces that don't have the pool tag flowing into cost
    explorer output yet.
  Idle cost ratio (whichever path) becomes the headline "pool waste"
  KPI.
- **By-User chargeback view (v2, depends on attribution signal).** Two
  candidate paths:
  - **Cluster-owner DBU-share apportionment.** For each `(pool, day)`,
    each cluster's owner gets `cluster_owner_share = cluster_dbu_on_pool
    / total_dbu_on_pool`. Idle cloud cost (once v2 lands) goes to the
    pool owner.
  - **Tag-based attribution** via
    `system.billing.usage.custom_tags['databricks-user']` — same
    feasibility gate as the all-purpose v2 path.
- **Pool creator GUID → email resolution (v2).** v1 surfaces the
  creator GUID only inside the pool details modal (the Python SDK's
  `GetInstancePool` exposes the GUID via
  `default_tags['DatabricksInstancePoolCreatorId']` but has no
  `creator_user_name` field). v2 follow-up: extend
  `get_pool_metadata` to do a second hop —
  `client.users.get(<guid>)` (or
  `client.users.list(filter=f"id eq {guid}")`) — to resolve the GUID
  to a human email, cache that result alongside the GUID in
  `pool_metadata_cache`, and surface `pool_creator_user_name` on
  `InstancePoolDetails` (currently absent from the model set per CP5).
  Modal then renders the email instead of "Creator ID: `{guid}`", and
  the LLM prompt in CP7 can drop the GUID-only rendering language.
  The list view stays creator-less in v2 unless we also pre-warm the
  cache at list-endpoint time (separate UX question).
- **Multi-region pool snapshot resolution (v2).** Because
  `system.compute.instance_pools` is regional (§10), a workspace with
  pool usage in multiple regions will see inflated "Snapshot missing"
  counts. v2 follow-up: run the SCD-collapse half of `pool_spends_app`
  in each region's warehouse and UNION ALL the metadata into a
  workspace-wide table; the rollup notebook then joins against that
  union table. Out of scope for v1 because single-region is the common
  case.
- **Pool sizing recommendations** beyond LLM analysis — a rules-based
  panel that suggests `min_idle_instances` tuning from observed peak
  concurrent attached clusters and `idle_instance_autotermination_minutes`
  tuning from observed idle-to-reattach time. Could be a sidebar in the
  pool details modal.
- **"All compute" combined view** — a fourth tab that combines Job +
  All-Purpose + Pool for a workspace-wide bird's-eye number, with
  explicit double-count subtraction (pool-backed cluster DBU appears
  once in this combined view, not twice). Independent feature, separate
  PR.
- **Alerts / budgets per pool** — would need a new alerts table + cron
  job + email integration. Same follow-up as the all-purpose plan's
  equivalent item; not pool-specific.
- **Promote `claude_scripts/test_instance_pools_*` to real pytest** —
  same CI-wiring blocker as the all-purpose and top-jobs plans.

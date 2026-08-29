// Instance Pools wire-level types.
//
// Mirrors the Pydantic models added to `server/models/job_spend.py` in CP5
// (search for "Instance Pool models"). Kept hand-written here in
// `client/src/types/` rather than imported from `@/fastapi_client/models`
// so the UI layer stays decoupled from the auto-generated client (matches
// the precedent set by `client/src/types/job-spend.ts` and
// `client/src/types/all-purpose.ts`).
//
// See plan §3 / §4.1 / §5 (`docs/plan_instance_pools_tab.md`) for the data
// model rationale:
//   - `instance_pool_id IS NOT NULL` is the sole pool filter (§3.1)
//   - `cloud_cost` carries pool EC2/EBS VM cost joined from
//     `dbspend360_pool_cloud_cost_explorer` (CP8 /
//     plan_pool_pipeline_ec2_cost.md §4.4). It is pool-level: it lands on the
//     pool-day total, stays NULL on per-cluster rows (rendered "—"), and is
//     NULL when no pool-tag cloud row landed yet (plan §5 / decision #3).
//   - Two-level drill-down: pool -> per-day -> per-cluster (§3.3 / §5.2)
//   - Three-state snapshot encoding via `pool_snapshot_missing` +
//     `pool_deleted_at` (§3.5)
//   - No creator field in list/day/cluster shapes — modal-only via REST
//     API on `InstancePoolDetails` (§3.4 / §4.1)

// Second-level drill-down inside a day's `clusters` array.
// `cluster_id === '__pool_overhead__'` is the §3.3 edge-case bucket for
// billing rows that have `instance_pool_id` set but no `cluster_id`; the
// UI renders that row as italicized "Pool overhead". `cloud_cost` is null
// on real cluster rows because active pool-backed VM cost stays on the
// cluster lens. The overhead row carries ClusterId-free idle/warm cost.
export interface InstancePoolClusterSpend {
  cluster_id: string;
  databricks_cost: number;
  cloud_cost?: number | null;
  total_cost: number;
}

// First-level drill-down inside a pool's `days` array. `clusters` is the
// nested per-cluster expansion, sorted DESC by `total_cost` per the §5.2
// SQL ORDER BY (the CP10 table caps rendering at the top 25 + an "Other"
// rollup row for pools that fan out across hundreds of clusters / day).
export interface InstancePoolDailySpend {
  usage_date: string; // ISO date string (YYYY-MM-DD)
  cluster_count_on_day: number;
  databricks_cost: number;
  cloud_cost?: number | null;
  total_cost: number;
  clusters: InstancePoolClusterSpend[];
}

// Top-level pool row in the By-Pool table.
//
// `pool_snapshot_missing` + `pool_deleted_at` together encode the §3.5
// three-state badge in the UI:
//   - active            : both falsy
//   - "Deleted YYYY-MM-DD" : `pool_deleted_at` populated, missing flag false
//   - "Snapshot missing"   : missing flag true, `pool_deleted_at` null
//
// No creator field — creator info is intentionally modal-only in v1 per
// §3.4 / §4.1 (the `system.compute.instance_pools.tags` source excludes
// default tags, so resolving the creator GUID requires a per-request
// REST API call which would defeat the table's caching story if done at
// list time).
export interface GroupedInstancePool {
  instance_pool_id: string;
  pool_name?: string | null;
  node_type?: string | null;
  min_idle_instances?: number | null;
  max_capacity?: number | null;
  idle_instance_autotermination_minutes?: number | null;
  pool_snapshot_missing: boolean;
  // ISO datetime string when populated.
  pool_deleted_at?: string | null;
  cluster_count: number;
  active_days: number;
  total_databricks_cost: number;
  total_cloud_cost?: number | null;
  total_cost: number;
  workspace_covered?: boolean;
  // Drill-down expansion: per-day rows for this pool. Populated on the
  // `/grouped` endpoint, empty on `/top-pools` (skipped for cost; mirrors
  // the existing `users: []` / `runs: []` pattern on the other top-N
  // endpoints).
  days: InstancePoolDailySpend[];
}

// KPI strip metrics.
//
// `orphaned_pools` is the count of distinct pools with
// `pool_snapshot_missing = true` — surfaced as a KPI so operators can
// spot lost-metadata churn at a glance (cross-region or pre-Oct-2023
// deleted-pool retention; §10 risks). `total_cloud_cost` is the summed
// ClusterId-free idle/warm pool VM cost; active pool-backed VM cost stays on
// its cluster lens. Freshness fields expose partial source landing.
export interface InstancePoolSummaryMetrics {
  total_pools: number;
  total_clusters: number;
  orphaned_pools: number;
  total_spend: number;
  // Statistics computed at the (instance_pool_id, usage_date) grain per
  // §5.3 — interpretable as "what does a single day on a single pool
  // cost on average".
  avg_cost_per_pool_day: number;
  max_cost_per_pool_day: number;
  min_cost_per_pool_day: number;
  total_databricks_cost: number;
  total_cloud_cost?: number | null;
  date_range_days: number;
  dbu_in_non_covered_workspaces?: number;
  latest_data_date?: string | null;
  latest_dbu_date?: string | null;
  latest_cloud_date?: string | null;
  cloud_data_days: number;
}

// Calendar-day series for the Daily Pool Spend Trend sparkline.
// Zero-filled for days with no covered-workspace pool spend.
export interface InstancePoolDailyTrendPoint {
  usage_date: string; // ISO date string (YYYY-MM-DD)
  total_cost: number;
}

// Pool configuration details for the pool details modal.
//
// Sourced from `system.compute.instance_pools` (most-recent SCD snapshot
// via `max_by(col, change_time)` per field — see §5.5 / CP6).
// `pool_creator_id` carries the GUID resolved per-request by
// `DatabricksService.get_pool_metadata` from the REST API's
// `default_tags['DatabricksInstancePoolCreatorId']`. None when the REST
// API call fails or the pool has no creator tag (e.g.
// workspace-system-created pools); rendered as italicized "Unknown
// creator" in that case. `pool_creator_user_name` (email) is intentionally
// absent in v1 — the SDK's `GetInstancePool` exposes only `default_tags`,
// and GUID -> email resolution requires a second hop through the
// Workspace users API (deferred to v2 per §13).
//
// `node_type` matches the actual `system.compute.instance_pools` column
// name (NOT `node_type_id` — see §10 risks row).
// `preloaded_spark_version` is singular (the column is also singular).
export interface InstancePoolDetails {
  instance_pool_id: string;
  pool_name?: string | null;
  pool_creator_id?: string | null;
  node_type?: string | null;
  min_idle_instances?: number | null;
  max_capacity?: number | null;
  idle_instance_autotermination_minutes?: number | null;
  preloaded_spark_version?: string | null;
  custom_tags?: Record<string, string> | null;
  pool_snapshot_missing: boolean;
  pool_deleted_at?: string | null;
}

// LLM-generated configuration analysis. The input includes ClusterId-free
// idle/warm pool cloud cost and an explicit active-cloud scope disclosure.
export interface InstancePoolAnalysis {
  instance_pool_id: string;
  analysis: string;
  timestamp: string;
}

export interface PaginatedInstancePools {
  data: GroupedInstancePool[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

// Filter shape passed to the paginated `/grouped` endpoint. Parallels
// `AllPurposeFilter` in `./all-purpose.ts`. `search` is a single
// free-text field that the backend matches against pool_name
// (case-insensitive substring), instance_pool_id (exact), and cluster_id
// (exact, via a back-reference to the filtered rows — see §5.1
// search-clause notes).
export interface InstancePoolFilter {
  start_date: string;
  end_date: string;
  search?: string;
  page: number;
  per_page: number;
}

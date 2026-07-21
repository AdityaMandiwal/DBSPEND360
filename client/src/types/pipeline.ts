// Pipeline Compute wire-level types.
//
// Mirrors the Pydantic models added to `server/models/job_spend.py` in CP5
// (search for "Pipeline" models). Kept hand-written here in
// `client/src/types/` rather than imported from `@/fastapi_client/models`
// so the UI layer stays decoupled from the auto-generated client (matches
// the precedent set by `client/src/types/job-spend.ts`,
// `client/src/types/all-purpose.ts`, and `client/src/types/instance-pool.ts`).
//
// See plan §3 / §4.1 / §5 (`docs/plan_dlt_tab.md`) for the data-model
// rationale:
//   - `usage_metadata.dlt_pipeline_id IS NOT NULL` is the sole row filter;
//     `billing_origin_product` only *labels* via `workload_type` (§3.1)
//   - v1 is DBU-only; `cloud_cost` is always null but plumbed for v2 (§3.2)
//   - Single-level drill-down: pipeline -> per-day (§3.3 / §5.2)
//   - `compute_mode` (serverless/classic/mixed) + `cost_basis`
//     (full/dbu_only/partial) carry the per-row cost-honesty signal (§3.2)
//   - Three-state metadata badge via `metadata_missing` +
//     `pipeline_deleted_at`, neutral and product-aware (§3.5)
//   - `created_by`/`run_as` come straight from
//     `system.lakeflow.pipelines` — no REST API (§3.4)

// First-level drill-down inside a pipeline's `days` array.
//
// The rollup is at product grain (§3.3); the §5.2 read sums across
// `billing_origin_product` within each `usage_date` before nesting here,
// so the UI sees exactly one row per pipeline-day. `cost_basis` is
// collapsed to one label for the day ('partial' when the day straddles
// `full` + `dbu_only`). `cloud_cost` is always null in v1.
export interface PipelineDailySpend {
  usage_date: string; // ISO date string (YYYY-MM-DD)
  databricks_cost: number;
  cost_basis: string; // 'full' | 'dbu_only' | 'partial'
  cloud_cost?: number | null;
  total_cost: number;
}

// Top-level pipeline row in the By-Pipeline table.
//
// `workload_type` is the cost-dominant workload label across the window
// (sum-then-`max_by`, not the largest single row — §3.1), rendered as a
// badge. `compute_mode` is serverless/classic/mixed; `cost_basis` is
// full/dbu_only/partial and drives the §3.2 info-icon on the `$`.
//
// `metadata_missing` + `pipeline_deleted_at` together encode the §3.5
// three-state badge in the UI:
//   - active                 : both falsy
//   - "Deleted YYYY-MM-DD"     : `pipeline_deleted_at` populated, flag false
//   - "Metadata not available" : flag true, `pipeline_deleted_at` null —
//     the *expected* state for Vector Search etc., rendered neutral grey
//     (not alarming)
//
// `created_by`/`run_as`/`pipeline_type` are null ("Unknown") when the
// snapshot is absent; `pipeline_name` falls back to `Pipeline {id}`.
// `total_cloud_cost` is always null in v1.
export interface GroupedPipeline {
  workspace_id: string;
  pipeline_id: string;
  pipeline_name?: string | null;
  pipeline_type?: string | null;
  created_by?: string | null;
  run_as?: string | null;
  workload_type: string;
  compute_mode: string; // 'serverless' | 'classic' | 'mixed'
  cost_basis: string; // 'full' | 'dbu_only' | 'partial'
  metadata_missing: boolean;
  // ISO datetime string when populated.
  pipeline_deleted_at?: string | null;
  active_days: number;
  total_databricks_cost: number;
  total_cloud_cost?: number | null;
  total_cost: number;
  workspace_covered?: boolean;
  // Drill-down expansion: per-day rows for this pipeline. Populated on the
  // `/grouped` endpoint, empty on `/top-pipelines` (skipped for cost;
  // mirrors the existing top-N pattern on the other tabs).
  days: PipelineDailySpend[];
}

// KPI strip metrics.
//
// The pipeline-count split is exhaustive of THREE buckets —
// `serverless_pipelines + classic_pipelines + mixed_pipelines ==
// total_pipelines` — so mode-switching pipelines land in `mixed` and are
// never double-counted (§5.3). The `$` split is likewise three buckets
// summing to `total_spend`: `serverless_spend` (full cost) +
// `classic_spend` (DBU only) + `mixed_spend` (partial), so the summary
// footnote stays exact even when mixed rows exist.
//
// `workload_breakdown` is the exact per-`workload_type` `$` map (reconciles
// row-for-row with staging — §3.1/§5.3) used by the KPI workload split.
// `metadata_unavailable` counts only DLT/SQL/Online-Table pipelines that
// *should* carry a snapshot but don't — Vector Search etc. are excluded so
// the number stays meaningful (§3.5). `total_cloud_cost` is always null in
// v1.
export interface PipelineSummaryMetrics {
  total_pipelines: number;
  serverless_pipelines: number;
  classic_pipelines: number;
  mixed_pipelines: number;
  metadata_unavailable: number;
  total_spend: number;
  serverless_spend: number; // full cost
  classic_spend: number; // DBU only — excludes cloud VM
  mixed_spend: number; // partial (classic portion DBU only)
  total_databricks_cost: number;
  total_cloud_cost?: number | null;
  dbu_in_non_covered_workspaces?: number;
  workload_breakdown: Record<string, number>;
  date_range_days: number;
}

// Pipeline configuration details for the pipeline details modal.
//
// Sourced from `system.lakeflow.pipelines` (most-recent SCD snapshot via
// QUALIFY ROW_NUMBER() per (workspace_id, pipeline_id) — §5.5 / CP6). No
// REST API, no GUID resolution: `created_by`/`run_as` are the
// human-readable values straight from the system table (§3.4).
// `workload_type`/`compute_mode`/`cost_basis` are joined in from the rollup
// so the modal can render the workload badge and the DBU-only caveat
// consistently with the list. `metadata_missing=true` indicates no snapshot
// row was found (normal for Vector Search / cross-region); the config
// fields fall back to null and the modal renders the neutral §3.5 banner.
export interface PipelineDetails {
  workspace_id: string;
  pipeline_id: string;
  pipeline_name?: string | null;
  pipeline_type?: string | null;
  created_by?: string | null;
  run_as?: string | null;
  workload_type?: string | null;
  compute_mode?: string | null;
  cost_basis?: string | null;
  tags?: Record<string, string> | null;
  metadata_missing: boolean;
  pipeline_deleted_at?: string | null;
}

// LLM-generated cost analysis. The `analysis` text is expected to include
// the DBU-only caveat ("excludes cloud VM cost") iff `cost_basis != 'full'`
// (§3.2 / §9 acceptance criterion #14 / CP7 exit criterion #4).
export interface PipelineAnalysis {
  pipeline_id: string;
  analysis: string;
  timestamp: string;
}

export interface PaginatedPipelines {
  data: GroupedPipeline[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

// Filter shape passed to the paginated `/grouped` endpoint. Parallels
// `InstancePoolFilter` in `./instance-pool.ts`. `search` is a single
// free-text field the backend matches against pipeline_name
// (case-insensitive substring), pipeline_id (exact), and created_by
// (case-insensitive substring). `workload_type` is the optional multi-value
// chip filter — it only *narrows*, never drops spend (§3.1).
export interface PipelineFilter {
  start_date: string;
  end_date: string;
  search?: string;
  workload_type?: string[];
  page: number;
  per_page: number;
}

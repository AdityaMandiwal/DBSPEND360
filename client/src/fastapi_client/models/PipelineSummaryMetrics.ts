/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Summary metrics for the Pipeline Compute tab KPI strip.
 *
 * The pipeline-count split is exhaustive of THREE buckets —
 * `serverless_pipelines + classic_pipelines + mixed_pipelines ==
 * total_pipelines` — so mode-switching pipelines land in `mixed` and are
 * never double-counted (plan §5.3). The `$` split is likewise three buckets
 * that sum to `total_spend`: `serverless_spend` (full cost) +
 * `classic_spend` + `mixed_spend`, with each pipeline's full known spend
 * assigned to its collapsed compute-mode bucket.
 *
 * `workload_breakdown` is the per-`workload_type` `$` map (e.g.
 * {"DLT Pipeline": ..., "DBSQL Materialized View": ...}); because
 * `billing_origin_product` is kept in the rollup grain it is EXACT and
 * reconciles row-for-row with staging (no dominant-product approximation —
 * plan §3.1/§5.3). `metadata_unavailable` counts only DLT/SQL/Online-Table
 * pipelines that *should* carry a `system.lakeflow.pipelines` snapshot but
 * don't — workloads that never have metadata (Vector Search) are excluded so
 * the number stays meaningful (plan §3.5). `total_cloud_cost` is the summed
 * classic EC2/EBS cost across the window (CP2, plan §3.2); `None` when every
 * matched pipeline is fully serverless (no separate VM line — KPI hidden),
 * not `$0`.
 */
export type PipelineSummaryMetrics = {
    total_pipelines: number;
    serverless_pipelines: number;
    classic_pipelines: number;
    mixed_pipelines: number;
    metadata_unavailable: number;
    total_spend: number;
    serverless_spend: number;
    classic_spend: number;
    mixed_spend: number;
    total_databricks_cost: number;
    total_cloud_cost?: (number | null);
    covered_cloud_cost?: number;
    covered_databricks_cost?: number;
    uncovered_cloud_cost?: number;
    workload_breakdown?: Record<string, number>;
    date_range_days: number;
    dbu_in_non_covered_workspaces?: number;
    latest_data_date?: (string | null);
    latest_dbu_date?: (string | null);
    latest_cloud_date?: (string | null);
    data_days?: number;
    cloud_data_days?: number;
};


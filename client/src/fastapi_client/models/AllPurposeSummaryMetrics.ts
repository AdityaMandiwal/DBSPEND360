/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Summary metrics for the All-Purpose tab KPI strip.
 *
 * `avg_cost_per_cluster_day` / `max_cost_per_cluster_day` /
 * `min_cost_per_cluster_day` are computed at the (cluster_id, user_id,
 * usage_date) grain (see plan §5.3) — not per cluster overall — so the
 * "average" is interpretable as "what does a single day on a single cluster
 * cost on average".
 */
export type AllPurposeSummaryMetrics = {
    total_clusters: number;
    total_users: number;
    total_spend: number;
    avg_cost_per_cluster_day: number;
    max_cost_per_cluster_day: number;
    min_cost_per_cluster_day: number;
    total_cloud_cost: number;
    total_databricks_cost: number;
    total_compute_cost?: (number | null);
    total_storage_cost?: (number | null);
    total_network_cost?: (number | null);
    total_other_cost?: (number | null);
    date_range_days: number;
};


/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Summary metrics for the Instance Pools tab KPI strip.
 *
 * `avg_cost_per_pool_day` / `max_cost_per_pool_day` /
 * `min_cost_per_pool_day` are computed at the (instance_pool_id,
 * usage_date) grain (plan §5.3) so "average" reads as "what does a single
 * day on a single pool cost on average". `orphaned_pools` is the count of
 * distinct pools with `pool_snapshot_missing = TRUE`, surfaced as a KPI so
 * operators can spot lost-metadata churn at a glance (plan §10 risk).
 * `total_cloud_cost` is intentionally left optional: in v1 every row has
 * `cloud_cost = NULL` so the SUM is always 0 and the KPI is hidden;
 * keeping it nullable in the wire shape avoids a v2 schema migration.
 */
export type InstancePoolSummaryMetrics = {
    total_pools: number;
    total_clusters: number;
    orphaned_pools: number;
    total_spend: number;
    avg_cost_per_pool_day: number;
    max_cost_per_pool_day: number;
    min_cost_per_pool_day: number;
    total_databricks_cost: number;
    total_cloud_cost?: (number | null);
    date_range_days: number;
};


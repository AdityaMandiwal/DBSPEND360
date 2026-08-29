/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Per-cluster cost contribution within a pool's per-day expansion.
 *
 * Drill-down sub-row inside `InstancePoolDailySpend.clusters`. One entry
 * per cluster that attached to the pool on a given `usage_date`.
 * `cluster_id == '__pool_overhead__'` represents pool-level bootstrap
 * charges that have no attributable cluster (plan §3.3 edge case); the UI
 * renders that row as italicized "Pool overhead". `cloud_cost` is `None` on
 * real per-cluster rows: active pool-backed VM cost remains on the cluster
 * lens. The overhead row carries ClusterId-free idle/warm cloud cost, so
 * surfacing it makes `total_cost` break down visibly as
 * `databricks_cost + cloud_cost`.
 */
export type InstancePoolClusterSpend = {
    cluster_id: string;
    databricks_cost: number;
    cloud_cost?: (number | null);
    total_cost?: number;
};


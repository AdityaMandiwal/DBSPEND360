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
 * renders that row as italicized "Pool overhead". `cloud_cost` is always
 * `None` on per-cluster rows even after CP7: pool EC2/EBS is pool-level, not
 * attributable to a specific attached cluster (AWS tags pool instances
 * `DatabricksInstancePoolId`, not `ClusterId`), so the UI renders "—" here
 * and surfaces the EC2 figure at the pool/day level instead (plan §4.4).
 */
export type InstancePoolClusterSpend = {
    cluster_id: string;
    databricks_cost: number;
    cloud_cost?: (number | null);
    total_cost?: number;
};


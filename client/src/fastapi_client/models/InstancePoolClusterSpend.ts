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
 * real per-cluster rows even after CP7: pool EC2/EBS is pool-level, not
 * attributable to a specific attached cluster (AWS tags pool instances
 * `DatabricksInstancePoolId`, not `ClusterId`), so the UI renders "—" there.
 * The one exception is the `__pool_overhead__` row itself, which DOES carry
 * the pool EC2/EBS `cloud_cost` — that is where the pool VM cost genuinely
 * lands, so surfacing it makes the row's `total_cost` break down visibly as
 * `databricks_cost + cloud_cost` instead of a Total with no components
 * (issue #3). The pool/day-level EC2 figure is still the authoritative one.
 */
export type InstancePoolClusterSpend = {
    cluster_id: string;
    databricks_cost: number;
    cloud_cost?: (number | null);
    total_cost?: number;
};


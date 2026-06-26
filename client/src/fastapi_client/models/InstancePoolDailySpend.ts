/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { InstancePoolClusterSpend } from './InstancePoolClusterSpend';
/**
 * Per-day cost contribution within an instance pool grouping.
 *
 * Drill-down sub-row inside `GroupedInstancePool.days`. `clusters` is the
 * second-level expansion (plan §3.3) listing per-cluster contributions for
 * that day, sorted DESC by `total_cost` (per the §5.2 SQL ORDER BY).
 * `cluster_count_on_day` equals `len(clusters)` by construction in the
 * service-layer rollup. `cloud_cost` is reserved for v2 and is always
 * None in v1; `total_cost` is plumbed straight through from the SQL
 * projection rather than computed (see module docstring rationale).
 */
export type InstancePoolDailySpend = {
    usage_date: string;
    cluster_count_on_day: number;
    databricks_cost: number;
    cloud_cost?: (number | null);
    total_cost?: number;
    clusters?: Array<InstancePoolClusterSpend>;
};


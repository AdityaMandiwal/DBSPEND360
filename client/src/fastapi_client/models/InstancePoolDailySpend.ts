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
 * `cluster_count_on_day` counts only real attached clusters and therefore
 * excludes the `__pool_overhead__` entry that may still be present in
 * `clusters`. `cloud_cost` is the ClusterId-free idle/warm pool VM cost for
 * the day — summed from the `__pool_overhead__` row where that cost lands —
 * and is `None` when no cloud row exists for the day (UI renders "—", §5);
 * `total_cost` is plumbed straight through from the SQL projection rather
 * than computed (see module docstring rationale).
 */
export type InstancePoolDailySpend = {
    usage_date: string;
    cluster_count_on_day: number;
    databricks_cost: number;
    cloud_cost?: (number | null);
    total_cost?: number;
    clusters?: Array<InstancePoolClusterSpend>;
};


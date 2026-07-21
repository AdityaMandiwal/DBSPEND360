/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AllPurposeClusterSpend } from './AllPurposeClusterSpend';
/**
 * User-level rollup for the By-User (chargeback) sub-tab.
 *
 * One row per cluster owner within the queried window. `clusters` lists the
 * per-cluster drill-down rows (one entry per (user_id, cluster_id) pair).
 * `user_active_days` is `COUNT(DISTINCT usage_date)` from the raw rows
 * (not summed across clusters — a user active on multiple clusters on the
 * same day must not double-count; see plan §5.2).
 */
export type GroupedAllPurposeUser = {
    user_id: string;
    cluster_count: number;
    user_active_days: number;
    total_cloud_cost?: (number | null);
    total_databricks_cost: number;
    total_compute_cost?: (number | null);
    total_storage_cost?: (number | null);
    total_network_cost?: (number | null);
    total_other_cost?: (number | null);
    workspace_covered?: boolean;
    clusters?: Array<AllPurposeClusterSpend>;
    /**
     * Calculate total cost across all clusters this user owns.
     */
    readonly total_cost: number;
    /**
     * Calculate cloud cost as percentage of total.
     */
    readonly cloud_percentage: number;
    /**
     * Calculate Databricks cost as percentage of total.
     */
    readonly databricks_percentage: number;
};


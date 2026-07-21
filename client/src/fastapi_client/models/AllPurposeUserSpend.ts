/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Per-day cost contribution within an all-purpose cluster grouping.
 *
 * Drill-down sub-row inside `GroupedAllPurposeCluster.users`. Under v1 owner
 * attribution there is exactly one user per (cluster_id, usage_date), so
 * this row collapses to a single calendar day's cost on the cluster owned by
 * that user. Forward-compatible with v2 multi-user attribution where the
 * same cluster-day can fan out to multiple users.
 */
export type AllPurposeUserSpend = {
    cluster_id: string;
    user_id: string;
    usage_date: string;
    cloud_cost?: (number | null);
    databricks_cost: number;
    compute_cost?: (number | null);
    storage_cost?: (number | null);
    network_cost?: (number | null);
    other_cost?: (number | null);
    workspace_covered?: boolean;
    /**
     * Calculate total cost as sum of cloud and Databricks costs.
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


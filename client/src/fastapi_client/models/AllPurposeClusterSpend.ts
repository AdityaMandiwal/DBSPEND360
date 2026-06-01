/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Per-cluster cost contribution within a user grouping.
 *
 * Drill-down sub-row inside `GroupedAllPurposeUser.clusters`. Aggregates a
 * user's cost on a single cluster across the queried date window;
 * `cluster_active_days` is `COUNT(DISTINCT usage_date)` for that
 * `(user_id, cluster_id)` pair. `data_security_mode` is denormalized so the
 * UI can render the attribution-quality badge ("Dedicated" / "Shared" /
 * "Legacy" / "Unknown") next to the cluster name without a second lookup.
 */
export type AllPurposeClusterSpend = {
    cluster_id: string;
    cluster_name?: (string | null);
    user_id: string;
    cluster_active_days: number;
    cloud_cost: number;
    databricks_cost: number;
    compute_cost?: (number | null);
    storage_cost?: (number | null);
    network_cost?: (number | null);
    other_cost?: (number | null);
    data_security_mode?: (string | null);
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


/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Individual job run details.
 */
export type JobRun = {
    run_id: string;
    cluster_id: string;
    cluster_ids?: Array<string>;
    start_date: string;
    end_date: string;
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


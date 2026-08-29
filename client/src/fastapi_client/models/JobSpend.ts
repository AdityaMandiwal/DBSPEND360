/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Data model for Databricks job spending records.
 */
export type JobSpend = {
    cluster_id: string;
    cloud_cost?: (number | null);
    job_id: string;
    job_name?: (string | null);
    run_id: string;
    usage_date: string;
    databricks_cost: number;
    compute_cost?: (number | null);
    storage_cost?: (number | null);
    network_cost?: (number | null);
    other_cost?: (number | null);
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


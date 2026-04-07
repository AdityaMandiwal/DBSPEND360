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
    start_date: string;
    end_date: string;
    ec2_cost: number;
    databricks_cost: number;
    compute_cost?: (number | null);
    storage_cost?: (number | null);
    network_cost?: (number | null);
    other_cost?: (number | null);
    /**
     * Calculate total cost as sum of EC2 and Databricks costs.
     */
    readonly total_cost: number;
    /**
     * Calculate EC2 cost as percentage of total.
     */
    readonly ec2_percentage: number;
    /**
     * Calculate Databricks cost as percentage of total.
     */
    readonly databricks_percentage: number;
};


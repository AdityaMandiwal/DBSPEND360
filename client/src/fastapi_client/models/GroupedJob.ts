/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { JobRun } from './JobRun';
/**
 * Grouped job data with aggregated costs and run details.
 */
export type GroupedJob = {
    job_id: string;
    job_name?: (string | null);
    run_count: number;
    total_ec2_cost: number;
    total_databricks_cost: number;
    total_compute_cost?: (number | null);
    total_storage_cost?: (number | null);
    total_network_cost?: (number | null);
    total_other_cost?: (number | null);
    runs: Array<JobRun>;
    /**
     * Calculate total cost across all runs.
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


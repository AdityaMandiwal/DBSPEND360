/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { JobRun } from './JobRun';
/**
 * Grouped job data with aggregated costs and (optional) run details.
 *
 * `runs` may be empty when the consumer only needs job-level totals (e.g. the
 * "Top N Costliest Jobs" card on the dashboard, which renders a flat list and
 * deliberately skips the per-run enrichment query to keep the endpoint cheap).
 * Callers that need a per-run drill-down read from `runs`; callers that only
 * care about totals can ignore it.
 */
export type GroupedJob = {
    job_id: string;
    job_name?: (string | null);
    run_count: number;
    total_cloud_cost: number;
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
     * Calculate cloud cost as percentage of total.
     */
    readonly cloud_percentage: number;
    /**
     * Calculate Databricks cost as percentage of total.
     */
    readonly databricks_percentage: number;
};


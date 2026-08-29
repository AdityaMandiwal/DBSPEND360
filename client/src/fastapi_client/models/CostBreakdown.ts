/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Cost breakdown for individual job.
 */
export type CostBreakdown = {
    job_id: string;
    run_id: string;
    cluster_id: string;
    cluster_ids?: Array<string>;
    usage_date: string;
    end_date?: (string | null);
    cloud_cost?: (number | null);
    databricks_cost: number;
    total_cost: number;
    compute_cost?: (number | null);
    storage_cost?: (number | null);
    network_cost?: (number | null);
    other_cost?: (number | null);
    cost_split?: Array<Record<string, any>>;
};


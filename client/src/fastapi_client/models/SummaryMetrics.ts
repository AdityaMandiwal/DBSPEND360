/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Summary metrics for job spending data.
 */
export type SummaryMetrics = {
    total_jobs: number;
    total_spend: number;
    average_cost: number;
    max_cost: number;
    min_cost: number;
    total_cloud_cost: number;
    total_databricks_cost: number;
    total_compute_cost?: (number | null);
    total_storage_cost?: (number | null);
    total_network_cost?: (number | null);
    total_other_cost?: (number | null);
    classification_coverage_pct?: (number | null);
    coverage_status?: (string | null);
    coverage_warning?: (string | null);
    date_range_days: number;
};


/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { JobProductBreakdownItem } from './JobProductBreakdownItem';
/**
 * Read-time DBU breakdown by billing_origin_product for one job.
 */
export type JobProductBreakdownResponse = {
    job_id: string;
    start_date: string;
    end_date: string;
    items: Array<JobProductBreakdownItem>;
    total_cost: number;
    rollup_databricks_cost?: (number | null);
    has_multiple_products: boolean;
    is_estimate?: boolean;
    unpriced_warning?: (string | null);
};


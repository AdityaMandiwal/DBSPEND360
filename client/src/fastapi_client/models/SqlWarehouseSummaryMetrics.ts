/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Summary metrics for the SQL Warehouses tab KPI strip.
 *
 * `total_spend` is tracked DBU spend. It is complete for Serverless, but
 * Classic/Pro infrastructure cost is not attributed. The warehouse-count split
 * is exhaustive: classic + pro + serverless == total_warehouses.
 */
export type SqlWarehouseSummaryMetrics = {
    total_warehouses: number;
    classic_warehouses: number;
    pro_warehouses: number;
    serverless_warehouses: number;
    total_spend: number;
    classic_spend: number;
    pro_spend: number;
    serverless_spend: number;
    total_databricks_cost: number;
    date_range_days: number;
    landed_days?: number;
    data_through_date?: (string | null);
    dbu_in_non_covered_workspaces?: number;
};


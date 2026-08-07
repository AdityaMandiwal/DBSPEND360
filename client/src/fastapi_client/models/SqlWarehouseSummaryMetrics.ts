/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Summary metrics for the SQL Warehouses tab KPI strip.
 *
 * DBU is the complete cost for managed-compute warehouses — no cloud cost
 * fields. The warehouse-count split is exhaustive: classic + pro + serverless
 * == total_warehouses.
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
    dbu_in_non_covered_workspaces?: number;
};


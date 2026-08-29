/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Per-day cost row in the SQL warehouse drill-down.
 */
export type SqlWarehouseDailySpend = {
    usage_date: string;
    databricks_cost: number;
    total_cost: number;
    warehouse_type?: (string | null);
    sku_name?: (string | null);
    cost_basis?: string;
};


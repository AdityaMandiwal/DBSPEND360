/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SqlWarehouseDailySpend } from './SqlWarehouseDailySpend';
/**
 * Warehouse-level rollup for the By-Warehouse list view.
 *
 * One row per warehouse within the queried window. `days` is the per-day
 * drill-down expansion. `metadata_missing` and `warehouse_deleted_at` encode
 * the three-state badge: active (both falsy), "Deleted" (warehouse_deleted_at
 * populated), "Metadata unavailable" (metadata_missing=True). DBU is the
 * complete cost for managed-compute warehouses — no separate cloud cost.
 */
export type GroupedSqlWarehouse = {
    warehouse_id: string;
    warehouse_name?: (string | null);
    warehouse_type?: (string | null);
    warehouse_size?: (string | null);
    creator_id?: (string | null);
    auto_stop_mins?: (number | null);
    min_clusters?: (number | null);
    max_clusters?: (number | null);
    metadata_missing?: boolean;
    warehouse_deleted_at?: (string | null);
    active_days: number;
    total_databricks_cost: number;
    total_cost: number;
    workspace_covered?: boolean;
    days?: Array<SqlWarehouseDailySpend>;
};


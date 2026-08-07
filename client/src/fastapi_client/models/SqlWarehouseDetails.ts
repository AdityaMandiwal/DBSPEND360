/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Warehouse config details for the details modal.
 *
 * Sourced from `system.compute.warehouses` (most-recent SCD snapshot),
 * denormalized into the rollup table. `metadata_missing=True` indicates
 * no system table row was found — the majority of warehouses (common, not
 * exceptional).
 */
export type SqlWarehouseDetails = {
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
    tags?: (Record<string, string> | null);
};


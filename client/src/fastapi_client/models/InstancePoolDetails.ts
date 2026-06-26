/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pool configuration details for the pool details modal.
 *
 * Sourced from `system.compute.instance_pools` (most-recent SCD snapshot
 * via `max_by(col, change_time)` per field — see plan §5.5 / CP6).
 * `pool_creator_id` carries the GUID resolved per-request by
 * `DatabricksService.get_pool_metadata`, which reads
 * `default_tags['DatabricksInstancePoolCreatorId']` from the Instance Pools
 * REST API response. None when the REST API call fails or the pool has no
 * creator tag (e.g. workspace-system-created pools). `pool_creator_user_name`
 * (email) is intentionally absent in v1 — the SDK's `GetInstancePool`
 * dataclass exposes only `default_tags`, and GUID -> email resolution
 * requires a second hop through the Workspace users API which is deferred
 * to v2 (plan §13).
 *
 * `node_type` matches the actual `system.compute.instance_pools` column
 * (NOT `node_type_id` — see plan §10 risks row).
 * `preloaded_spark_version` is singular (the column is also singular).
 * `pool_snapshot_missing=True` indicates no system-table snapshot row was
 * found; in that case the modal still attempts the REST API enrichment so
 * a deleted-but-still-tracked pool can surface its name and creator GUID
 * (plan CP6).
 */
export type InstancePoolDetails = {
    instance_pool_id: string;
    pool_name?: (string | null);
    pool_creator_id?: (string | null);
    node_type?: (string | null);
    min_idle_instances?: (number | null);
    max_capacity?: (number | null);
    idle_instance_autotermination_minutes?: (number | null);
    preloaded_spark_version?: (string | null);
    custom_tags?: (Record<string, string> | null);
    pool_snapshot_missing?: boolean;
    pool_deleted_at?: (string | null);
};


/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { InstancePoolDailySpend } from './InstancePoolDailySpend';
/**
 * Pool-level rollup for the By-Pool list view.
 *
 * One row per instance pool within the queried window. `days` is the
 * first-level drill-down expansion (plan §3.3). `pool_snapshot_missing`
 * and `pool_deleted_at` together encode the three-state badge from plan
 * §3.5: active (both falsy), "Deleted YYYY-MM-DD" (`pool_deleted_at`
 * populated, missing flag false), "Snapshot missing" (missing flag true,
 * `pool_deleted_at` NULL). `pool_name` falls back to `Pool {pool_id}` in
 * the snapshot-missing path (plan §5.5). No creator field — creator info
 * is modal-only via the REST API in v1 (plan §3.4, §4.1).
 */
export type GroupedInstancePool = {
    instance_pool_id: string;
    pool_name?: (string | null);
    node_type?: (string | null);
    min_idle_instances?: (number | null);
    max_capacity?: (number | null);
    idle_instance_autotermination_minutes?: (number | null);
    pool_snapshot_missing?: boolean;
    pool_deleted_at?: (string | null);
    cluster_count: number;
    active_days: number;
    total_databricks_cost: number;
    total_cloud_cost?: (number | null);
    total_cost: number;
    days?: Array<InstancePoolDailySpend>;
};


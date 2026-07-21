/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AllPurposeUserSpend } from './AllPurposeUserSpend';
/**
 * Cluster-level rollup for the By-Cluster sub-tab.
 *
 * One row per all-purpose cluster within the queried window. `users` is the
 * per-day drill-down expansion (under v1: one user per day, the cluster
 * owner). `data_security_mode` drives the UI attribution-quality badge.
 * `cluster_name` may be NULL when the `system.compute.clusters` snapshot row
 * is missing (cluster deleted before October 2023, see plan §10); the UI
 * falls back to `Cluster {cluster_id}` in that case.
 */
export type GroupedAllPurposeCluster = {
    cluster_id: string;
    cluster_name?: (string | null);
    owner_user_id: string;
    data_security_mode?: (string | null);
    active_days: number;
    total_cloud_cost?: (number | null);
    total_databricks_cost: number;
    total_compute_cost?: (number | null);
    total_storage_cost?: (number | null);
    total_network_cost?: (number | null);
    total_other_cost?: (number | null);
    workspace_covered?: boolean;
    users?: Array<AllPurposeUserSpend>;
    /**
     * Calculate total cost across all users on this cluster.
     */
    readonly total_cost: number;
    /**
     * Calculate cloud cost as percentage of total.
     */
    readonly cloud_percentage: number;
    /**
     * Calculate Databricks cost as percentage of total.
     */
    readonly databricks_percentage: number;
};


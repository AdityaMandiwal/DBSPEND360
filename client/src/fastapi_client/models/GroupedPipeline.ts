/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PipelineDailySpend } from './PipelineDailySpend';
/**
 * Pipeline-level rollup for the By-Pipeline list view.
 *
 * One row per pipeline within the queried window (plan §5.1). `days` is the
 * single drill-down expansion (plan §3.3). `workload_type` is the
 * cost-dominant workload label across the window (sum-then-`max_by`, not the
 * largest single row — plan §3.1). `compute_mode` is
 * serverless/classic/mixed and `cost_basis` is full/dbu_only/partial; both
 * are pre-computed in the rollup and collapsed deterministically on read.
 *
 * `metadata_missing` and `pipeline_deleted_at` encode the plan §3.5
 * three-state badge: active (both falsy), "Deleted YYYY-MM-DD"
 * (`pipeline_deleted_at` set, flag false), "Metadata not available" (flag
 * true, `pipeline_deleted_at` NULL — the *expected* state for Vector Search
 * etc., rendered neutral, not alarming). `pipeline_name` falls back to
 * `Pipeline {pipeline_id}` in the metadata-missing path (plan §5.5).
 * `created_by`/`run_as`/`pipeline_type` are None ("Unknown") when absent.
 * `total_cloud_cost` is reserved for v2 and is always None in v1.
 */
export type GroupedPipeline = {
    workspace_id: string;
    pipeline_id: string;
    pipeline_name?: (string | null);
    pipeline_type?: (string | null);
    created_by?: (string | null);
    run_as?: (string | null);
    workload_type: string;
    compute_mode: string;
    cost_basis: string;
    metadata_missing?: boolean;
    pipeline_deleted_at?: (string | null);
    active_days: number;
    total_databricks_cost: number;
    total_cloud_cost?: (number | null);
    total_cost: number;
    days?: Array<PipelineDailySpend>;
};


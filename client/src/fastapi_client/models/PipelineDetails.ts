/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pipeline configuration details for the pipeline details modal.
 *
 * Sourced from `system.lakeflow.pipelines` (most-recent SCD snapshot via
 * QUALIFY ROW_NUMBER() per (workspace_id, pipeline_id) — plan §5.5 / CP6).
 * No REST API and no GUID resolution: `created_by`/`run_as` are the
 * human-readable values straight from the system table (plan §3.4).
 * `workload_type`/`compute_mode`/`cost_basis` are joined in from the rollup
 * so the modal can render the workload and compute context consistently with
 * the list. `metadata_missing=True` indicates no
 * `system.lakeflow.pipelines` row was found (normal for Vector Search /
 * cross-region); in that case the config fields fall back to None and the
 * modal renders the neutral §3.5 banner.
 */
export type PipelineDetails = {
    workspace_id: string;
    pipeline_id: string;
    pipeline_name?: (string | null);
    pipeline_type?: (string | null);
    created_by?: (string | null);
    run_as?: (string | null);
    workload_type?: (string | null);
    compute_mode?: (string | null);
    cost_basis?: (string | null);
    tags?: (Record<string, string> | null);
    metadata_missing?: boolean;
    pipeline_deleted_at?: (string | null);
};


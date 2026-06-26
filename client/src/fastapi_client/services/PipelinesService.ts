/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedPipeline } from '../models/GroupedPipeline';
import type { PaginatedPipelines } from '../models/PaginatedPipelines';
import type { PipelineAnalysis } from '../models/PipelineAnalysis';
import type { PipelineDetails } from '../models/PipelineDetails';
import type { PipelineSummaryMetrics } from '../models/PipelineSummaryMetrics';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class PipelinesService {
    /**
     * Get Pipeline Summary
     * Get KPI summary metrics for the Pipeline Compute tab.
     *
     * Returns the three-bucket pipeline-count split (serverless / classic /
     * mixed, summing to `total_pipelines`), the matching three-bucket `$`
     * split (`serverless_spend` + `classic_spend` + `mixed_spend` ==
     * `total_spend`), the exact per-`workload_type` `$` breakdown, and the
     * `metadata_unavailable` count (which excludes workloads that never carry
     * a `system.lakeflow.pipelines` snapshot, e.g. Vector Search — plan §3.5).
     * @param startDate Start date for summary (YYYY-MM-DD)
     * @param endDate End date for summary (YYYY-MM-DD)
     * @param workloadType Optional workload-type chip filter (multi-value). Only labels / narrows; never drops spend (plan §3.1).
     * @returns PipelineSummaryMetrics Successful Response
     * @throws ApiError
     */
    public static getPipelineSummaryApiPipelinesSummaryGet(
        startDate: string,
        endDate: string,
        workloadType?: (Array<string> | null),
    ): CancelablePromise<PipelineSummaryMetrics> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/pipelines/summary',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'workload_type': workloadType,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Pipelines Grouped
     * Get paginated By-Pipeline rollup with a single per-day drill-down.
     *
     * One row per pipeline in the window (plan §5.1). Each row's `days` array
     * carries the per-day expansion (plan §5.2); the rollup's internal product
     * grain is summed away so the UI sees exactly one row per pipeline-day.
     * The cost-dominant `workload_type` badge is a sum-then-`max_by` label
     * (plan §3.1).
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param search Optional free-text filter matched against pipeline_name (case-insensitive substring), pipeline_id (exact), and created_by (case-insensitive substring)
     * @param workloadType Optional workload-type chip filter (multi-value, e.g. 'DLT Pipeline'). Only labels / narrows; never drops (plan §3.1).
     * @param page Page number
     * @param perPage Items per page
     * @returns PaginatedPipelines Successful Response
     * @throws ApiError
     */
    public static getPipelinesGroupedApiPipelinesGroupedGet(
        startDate: string,
        endDate: string,
        search?: (string | null),
        workloadType?: (Array<string> | null),
        page: number = 1,
        perPage: number = 50,
    ): CancelablePromise<PaginatedPipelines> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/pipelines/grouped',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'search': search,
                'workload_type': workloadType,
                'page': page,
                'per_page': perPage,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Top Pipelines
     * Get the top N most expensive pipelines in the window.
     *
     * Pipeline-grain analogue of `/api/instance-pools/top-pools`. Returns flat
     * `GroupedPipeline` rows with `days=[]` — this endpoint powers a top-N
     * highlight card and intentionally skips the per-day enrichment query for
     * cost reasons (mirrors the other tabs' top-N pattern). Use `/grouped` for
     * the drill-down view. Accepts the optional `workload_type` chip filter so
     * the card narrows alongside the rest of the tab.
     * @param startDate Start date (YYYY-MM-DD)
     * @param endDate End date (YYYY-MM-DD)
     * @param limit Number of top pipelines to return
     * @param workloadType Optional workload-type chip filter (multi-value). Narrows the Top-N in lock-step with the KPI strip and table; never drops spend (plan §3.1).
     * @returns GroupedPipeline Successful Response
     * @throws ApiError
     */
    public static getTopPipelinesApiPipelinesTopPipelinesGet(
        startDate: string,
        endDate: string,
        limit: number = 5,
        workloadType?: (Array<string> | null),
    ): CancelablePromise<Array<GroupedPipeline>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/pipelines/top-pipelines',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'limit': limit,
                'workload_type': workloadType,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Pipeline Details
     * Get pipeline configuration details for the pipeline details modal.
     *
     * Reads config straight from `system.lakeflow.pipelines` (most-recent SCD
     * snapshot) — no REST API, no GUID resolution (plan §3.4). Returns a
     * sentinel `PipelineDetails(metadata_missing=True, ...)` when no snapshot
     * row exists (normal for Vector Search / cross-region — a made-up id must
     * not raise). Returns 409 when the id is ambiguous across workspaces and
     * no `workspace_id` was supplied (plan §6).
     * @param pipelineId
     * @param workspaceId Optional workspace scope. `pipeline_id` is only unique within a workspace (plan §3.3/§6); omit for the single-workspace dev path. If the id spans >1 workspace and this is omitted, returns 409.
     * @returns PipelineDetails Successful Response
     * @throws ApiError
     */
    public static getPipelineDetailsApiPipelinesPipelineIdDetailsGet(
        pipelineId: string,
        workspaceId?: (string | null),
    ): CancelablePromise<PipelineDetails> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/pipelines/{pipeline_id}/details',
            path: {
                'pipeline_id': pipelineId,
            },
            query: {
                'workspace_id': workspaceId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Analyze Pipeline
     * Get LLM-powered cost + workload analysis for a pipeline.
     *
     * Fetches `PipelineDetails` and the pipeline's cost summary in parallel,
     * then hands both to `LLMService.analyze_pipeline_costs`. The single
     * workload-aware prompt
     * (`server.services.llm_service.PIPELINE_ANALYSIS_PROMPT`) tailors itself
     * off the `workload_type` field with no per-product branching (plan §4.1).
     *
     * The analysis MUST include the DBU-only caveat ("excludes cloud VM cost")
     * iff `cost_basis != 'full'` (plan §3.2 / §9 acceptance criterion #14 /
     * CP7 exit criterion #4); the structured fallback carries the same
     * conditional so the invariant holds on LLM failure.
     * @param pipelineId
     * @param workspaceId Optional workspace scope (see `/{id}/details`). Returns 409 if the id is ambiguous across workspaces and this is omitted.
     * @returns PipelineAnalysis Successful Response
     * @throws ApiError
     */
    public static analyzePipelineApiPipelinesPipelineIdAnalyzeGet(
        pipelineId: string,
        workspaceId?: (string | null),
    ): CancelablePromise<PipelineAnalysis> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/pipelines/{pipeline_id}/analyze',
            path: {
                'pipeline_id': pipelineId,
            },
            query: {
                'workspace_id': workspaceId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Pipelines Health
     * Health-check endpoint for the Pipeline Compute router.
     *
     * Used as a smoke test that the router is mounted above the StaticFiles
     * catch-all in `server/app.py` (plan §10 risks table) — if this returns
     * the static index.html instead of JSON, the include order is wrong.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static pipelinesHealthApiPipelinesHealthGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/pipelines/health',
        });
    }
}

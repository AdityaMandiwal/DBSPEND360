/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedInstancePool } from '../models/GroupedInstancePool';
import type { InstancePoolAnalysis } from '../models/InstancePoolAnalysis';
import type { InstancePoolDailyTrendPoint } from '../models/InstancePoolDailyTrendPoint';
import type { InstancePoolDetails } from '../models/InstancePoolDetails';
import type { InstancePoolSummaryMetrics } from '../models/InstancePoolSummaryMetrics';
import type { PaginatedInstancePools } from '../models/PaginatedInstancePools';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class InstancePoolsService {
    /**
     * Get Instance Pool Summary
     * Get KPI summary metrics for the Instance Pools tab.
     *
     * Returns aggregated metrics across the window: total spend, distinct
     * pool + cluster counts, count of pools with `pool_snapshot_missing = TRUE`
     * (the "orphaned pools" KPI surfaced for cross-region / pre-Oct-2023
     * deleted pools per plan §10), and per-pool-day cost statistics
     * (avg/max/min) computed at the `(instance_pool_id, usage_date)` grain.
     * @param startDate Start date for summary (YYYY-MM-DD)
     * @param endDate End date for summary (YYYY-MM-DD)
     * @returns InstancePoolSummaryMetrics Successful Response
     * @throws ApiError
     */
    public static getInstancePoolSummaryApiInstancePoolsSummaryGet(
        startDate: string,
        endDate: string,
    ): CancelablePromise<InstancePoolSummaryMetrics> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/instance-pools/summary',
            query: {
                'start_date': startDate,
                'end_date': endDate,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Instance Pool Daily Trend
     * Get daily aggregate pool spend for the trend sparkline.
     *
     * Returns one point per calendar day in the window (zero-filled when no
     * covered-workspace pool spend landed). Powers the Daily Pool Spend Trend
     * card on the Instance Pools tab.
     * @param startDate Start date (YYYY-MM-DD)
     * @param endDate End date (YYYY-MM-DD)
     * @returns InstancePoolDailyTrendPoint Successful Response
     * @throws ApiError
     */
    public static getInstancePoolDailyTrendApiInstancePoolsDailyTrendGet(
        startDate: string,
        endDate: string,
    ): CancelablePromise<Array<InstancePoolDailyTrendPoint>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/instance-pools/daily-trend',
            query: {
                'start_date': startDate,
                'end_date': endDate,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Instance Pools Grouped
     * Get paginated By-Pool rollup with two-level drill-down.
     *
     * One row per instance pool in the window. Each row's `days` array
     * carries the per-day expansion, and each day's `clusters` array
     * carries the per-cluster expansion (plan §3.3 / §5.2). The list
     * endpoint deliberately does NOT enrich rows with the REST-resolved
     * creator GUID — creator info is modal-only in v1 per plan §3.4 /
     * §4.1 / CP10 regression guard.
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param search Optional free-text filter matched against pool_name (case-insensitive substring), instance_pool_id (exact), and cluster_id (exact, via a back-reference to the filtered rows)
     * @param page Page number
     * @param perPage Items per page
     * @returns PaginatedInstancePools Successful Response
     * @throws ApiError
     */
    public static getInstancePoolsGroupedApiInstancePoolsGroupedGet(
        startDate: string,
        endDate: string,
        search?: (string | null),
        page: number = 1,
        perPage: number = 50,
    ): CancelablePromise<PaginatedInstancePools> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/instance-pools/grouped',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'search': search,
                'page': page,
                'per_page': perPage,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Top Instance Pools
     * Get the top N most expensive instance pools in the window.
     *
     * Pool-grain analogue of `/api/top-jobs` and
     * `/api/all-purpose/top-clusters`. Returns flat `GroupedInstancePool`
     * rows with `days=[]` — this endpoint powers a top-N highlight card
     * and intentionally skips the per-day + per-cluster enrichment query
     * for cost reasons (mirrors the existing top-N endpoints' `runs=[]`
     * / `users=[]` pattern). Use `/grouped` for the drill-down view.
     * @param startDate Start date (YYYY-MM-DD)
     * @param endDate End date (YYYY-MM-DD)
     * @param limit Number of top pools to return
     * @returns GroupedInstancePool Successful Response
     * @throws ApiError
     */
    public static getTopInstancePoolsApiInstancePoolsTopPoolsGet(
        startDate: string,
        endDate: string,
        limit: number = 5,
    ): CancelablePromise<Array<GroupedInstancePool>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/instance-pools/top-pools',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'limit': limit,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Instance Pool Details
     * Get pool configuration details for the pool details modal.
     *
     * Reads pool config from `system.compute.instance_pools` (most-recent
     * SCD snapshot) and enriches the creator GUID via a per-request call
     * to the Instance Pools REST API
     * (`default_tags['DatabricksInstancePoolCreatorId']`). Per plan §3.4
     * / §10, the system table's `tags` column excludes default tags, so
     * the REST API is the only source for the auto-applied creator tag.
     *
     * Returns a sentinel `InstancePoolDetails(pool_snapshot_missing=True, ...)`
     * when no system-table snapshot row exists. The REST API call is still
     * attempted in the sentinel path so a deleted-but-still-tracked pool
     * can surface its name + creator GUID.
     *
     * GUID -> email resolution is deferred to v2 (plan §13).
     * @param poolId
     * @returns InstancePoolDetails Successful Response
     * @throws ApiError
     */
    public static getInstancePoolDetailsApiInstancePoolsPoolIdDetailsGet(
        poolId: string,
    ): CancelablePromise<InstancePoolDetails> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/instance-pools/{pool_id}/details',
            path: {
                'pool_id': poolId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Analyze Instance Pool
     * Get LLM-powered configuration + cost analysis for an instance pool.
     *
     * Fetches `InstancePoolDetails` and the pool's cost summary in
     * parallel, then hands both to `LLMService.analyze_instance_pool_costs`.
     * The pool prompt
     * (`server.services.llm_service.INSTANCE_POOL_ANALYSIS_PROMPT`) is
     * built on top of `CLUSTER_ANALYSIS_SYSTEM_PROMPT`'s config-analysis
     * shape (Overall Rating / Right-Sizing / Cost Savings / Idle Waste
     * Risk / Configuration Gaps) — pool analysis is a configuration-shape
     * question closer to `analyze_cluster_configuration` than to a
     * per-run trend analysis.
     *
     * As of CP8 (plan_pool_pipeline_ec2_cost.md §4.4) pool EC2/EBS cost is
     * joined into the cost summary, so the prompt MANDATES only the remaining
     * idle-vs-active-split caveat ("the idle-vs-active VM cost split is not
     * available yet" — §4.5) rather than the old DBU-only caveat; the response
     * must include that string and the structured fallback
     * (`_build_pool_fallback`) carries it too so the invariant holds on LLM
     * failure.
     * @param poolId
     * @returns InstancePoolAnalysis Successful Response
     * @throws ApiError
     */
    public static analyzeInstancePoolApiInstancePoolsPoolIdAnalyzeGet(
        poolId: string,
    ): CancelablePromise<InstancePoolAnalysis> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/instance-pools/{pool_id}/analyze',
            path: {
                'pool_id': poolId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Instance Pools Health
     * Health-check endpoint for the Instance Pools router.
     *
     * Used as a smoke test that the router is mounted above the StaticFiles
     * catch-all in `server/app.py` (per plan §10 risks table) — if this
     * returns the static index.html instead of JSON, the include order is
     * wrong.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static instancePoolsHealthApiInstancePoolsHealthGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/instance-pools/health',
        });
    }
}

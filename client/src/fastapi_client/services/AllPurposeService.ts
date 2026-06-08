/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AllPurposeSummaryMetrics } from '../models/AllPurposeSummaryMetrics';
import type { GroupedAllPurposeCluster } from '../models/GroupedAllPurposeCluster';
import type { GroupedAllPurposeUser } from '../models/GroupedAllPurposeUser';
import type { PaginatedAllPurposeClusters } from '../models/PaginatedAllPurposeClusters';
import type { PaginatedAllPurposeUsers } from '../models/PaginatedAllPurposeUsers';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AllPurposeService {
    /**
     * Get All Purpose Summary
     * Get KPI summary metrics for the All-Purpose tab.
     *
     * Returns aggregated metrics across the window: total spend, distinct
     * cluster + user counts, and per-cluster-day cost statistics. Mirrors
     * `/api/summary` in shape but reports cluster and user counts rather than
     * job counts (the all-purpose model is keyed by user, not job).
     * @param startDate Start date for summary (YYYY-MM-DD)
     * @param endDate End date for summary (YYYY-MM-DD)
     * @returns AllPurposeSummaryMetrics Successful Response
     * @throws ApiError
     */
    public static getAllPurposeSummaryApiAllPurposeSummaryGet(
        startDate: string,
        endDate: string,
    ): CancelablePromise<AllPurposeSummaryMetrics> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/all-purpose/summary',
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
     * Get All Purpose Grouped By Cluster
     * Get paginated By-Cluster all-purpose spend, with per-day drill-down.
     *
     * One row per cluster in the window, with the owner's `user_id` and
     * `data_security_mode` denormalized. Each row's `users` array is
     * pre-populated with the per-day breakdown for that cluster (under v1
     * owner attribution, one user per day — the cluster owner).
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param search Optional free-text filter matched against cluster_name, cluster_id, and owner_user_id
     * @param page Page number
     * @param perPage Items per page
     * @returns PaginatedAllPurposeClusters Successful Response
     * @throws ApiError
     */
    public static getAllPurposeGroupedByClusterApiAllPurposeGroupedByClusterGet(
        startDate: string,
        endDate: string,
        search?: (string | null),
        page: number = 1,
        perPage: number = 50,
    ): CancelablePromise<PaginatedAllPurposeClusters> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/all-purpose/grouped-by-cluster',
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
     * Get All Purpose Grouped By User
     * Get paginated By-User all-purpose spend (chargeback view).
     *
     * One row per user (cluster owner) in the window, with per-cluster
     * drill-down enrichment. `user_active_days` is computed correctly
     * (distinct days from raw rows, not summed across clusters) — see plan
     * §5.2 for why summing would double-count.
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param search Optional free-text filter matched against user_id (case-insensitive)
     * @param page Page number
     * @param perPage Items per page
     * @returns PaginatedAllPurposeUsers Successful Response
     * @throws ApiError
     */
    public static getAllPurposeGroupedByUserApiAllPurposeGroupedByUserGet(
        startDate: string,
        endDate: string,
        search?: (string | null),
        page: number = 1,
        perPage: number = 50,
    ): CancelablePromise<PaginatedAllPurposeUsers> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/all-purpose/grouped-by-user',
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
     * Get All Purpose Top Clusters
     * Get the top N most expensive all-purpose clusters in the window.
     *
     * Cluster-grain analogue of `/api/top-jobs`. Returns flat
     * `GroupedAllPurposeCluster` rows with `users=[]` — this endpoint powers
     * a top-N highlight card and intentionally skips per-day enrichment for
     * cost reasons. Use `/grouped-by-cluster` for the drill-down view.
     * @param startDate Start date (YYYY-MM-DD)
     * @param endDate End date (YYYY-MM-DD)
     * @param limit Number of top clusters to return
     * @returns GroupedAllPurposeCluster Successful Response
     * @throws ApiError
     */
    public static getAllPurposeTopClustersApiAllPurposeTopClustersGet(
        startDate: string,
        endDate: string,
        limit: number = 5,
    ): CancelablePromise<Array<GroupedAllPurposeCluster>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/all-purpose/top-clusters',
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
     * Get All Purpose Top Users
     * Get the top N most expensive all-purpose users in the window.
     *
     * User-grain (chargeback) analogue of `/api/top-jobs`. Returns flat
     * `GroupedAllPurposeUser` rows with `clusters=[]`. Use `/grouped-by-user`
     * for the per-user drill-down with per-cluster expansion.
     * @param startDate Start date (YYYY-MM-DD)
     * @param endDate End date (YYYY-MM-DD)
     * @param limit Number of top users to return
     * @returns GroupedAllPurposeUser Successful Response
     * @throws ApiError
     */
    public static getAllPurposeTopUsersApiAllPurposeTopUsersGet(
        startDate: string,
        endDate: string,
        limit: number = 5,
    ): CancelablePromise<Array<GroupedAllPurposeUser>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/all-purpose/top-users',
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
     * All Purpose Health
     * Health-check endpoint for the All-Purpose router.
     *
     * Used as a smoke test that the router is mounted above the StaticFiles
     * catch-all in `server/app.py` (per plan §10 risks table) — if this
     * returns the static index.html instead of JSON, the include order is
     * wrong.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static allPurposeHealthApiAllPurposeHealthGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/all-purpose/health',
        });
    }
}

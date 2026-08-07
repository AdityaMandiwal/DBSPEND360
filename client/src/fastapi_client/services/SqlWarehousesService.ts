/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedSqlWarehouse } from '../models/GroupedSqlWarehouse';
import type { PaginatedSqlWarehouses } from '../models/PaginatedSqlWarehouses';
import type { SqlWarehouseAnalysis } from '../models/SqlWarehouseAnalysis';
import type { SqlWarehouseDetails } from '../models/SqlWarehouseDetails';
import type { SqlWarehouseSummaryMetrics } from '../models/SqlWarehouseSummaryMetrics';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SqlWarehousesService {
    /**
     * Get Sql Warehouse Summary
     * Get KPI summary metrics for the SQL Warehouses tab.
     *
     * Returns the exhaustive three-bucket warehouse-count split (classic + pro +
     * serverless == `total_warehouses`) and the matching `$` split
     * (`classic_spend` + `pro_spend` + `serverless_spend` == `total_spend`).
     * `total_spend` equals `total_databricks_cost` by construction — DBU is the
     * complete cost for managed compute, so there is no cloud component and no
     * Cloud-vs-DBU KPI.
     * @param startDate Start date for summary (YYYY-MM-DD)
     * @param endDate End date for summary (YYYY-MM-DD)
     * @returns SqlWarehouseSummaryMetrics Successful Response
     * @throws ApiError
     */
    public static getSqlWarehouseSummaryApiWarehousesSummaryGet(
        startDate: string,
        endDate: string,
    ): CancelablePromise<SqlWarehouseSummaryMetrics> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/warehouses/summary',
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
     * Get Sql Warehouses Grouped
     * Get paginated By-Warehouse rollup with a per-day drill-down.
     *
     * One row per warehouse in the window. Each row's `days` array carries the
     * per-day expansion, so the sum of `days[].total_cost` equals the row's
     * `total_cost`.
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param search Optional free-text filter matched against warehouse_name (case-insensitive substring) and warehouse_id (exact)
     * @param page Page number
     * @param perPage Items per page
     * @returns PaginatedSqlWarehouses Successful Response
     * @throws ApiError
     */
    public static getSqlWarehousesGroupedApiWarehousesGroupedGet(
        startDate: string,
        endDate: string,
        search?: (string | null),
        page: number = 1,
        perPage: number = 50,
    ): CancelablePromise<PaginatedSqlWarehouses> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/warehouses/grouped',
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
     * Get Top Sql Warehouses
     * Get the top N most expensive SQL warehouses in the window.
     *
     * Returns flat `GroupedSqlWarehouse` rows with `days=[]` — this endpoint
     * powers a top-N highlight card and intentionally skips the per-day
     * enrichment query for cost reasons (mirrors the other tabs' top-N pattern).
     * Use `/grouped` for the drill-down view.
     * @param startDate Start date (YYYY-MM-DD)
     * @param endDate End date (YYYY-MM-DD)
     * @param limit Number of top warehouses to return
     * @returns GroupedSqlWarehouse Successful Response
     * @throws ApiError
     */
    public static getTopSqlWarehousesApiWarehousesTopWarehousesGet(
        startDate: string,
        endDate: string,
        limit: number = 5,
    ): CancelablePromise<Array<GroupedSqlWarehouse>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/warehouses/top-warehouses',
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
     * Get Sql Warehouse Details
     * Get warehouse configuration details for the details modal.
     *
     * Reads the config denormalized into the rollup from
     * `system.compute.warehouses` (name, type, size, creator, auto-stop,
     * min/max clusters, deleted-at) plus a best-effort `tags` lookup. Returns a
     * sentinel `SqlWarehouseDetails(metadata_missing=True, ...)` when no rollup
     * row exists so a made-up id renders the neutral badge instead of raising.
     *
     * No `workspace_id` param: `warehouse_id` is account-unique, so there is no
     * ambiguity to resolve.
     * @param warehouseId
     * @returns SqlWarehouseDetails Successful Response
     * @throws ApiError
     */
    public static getSqlWarehouseDetailsApiWarehousesWarehouseIdDetailsGet(
        warehouseId: string,
    ): CancelablePromise<SqlWarehouseDetails> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/warehouses/{warehouse_id}/details',
            path: {
                'warehouse_id': warehouseId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Analyze Sql Warehouse
     * Get LLM-powered cost analysis for a SQL warehouse.
     *
     * Fetches `SqlWarehouseDetails` and the warehouse's cost summary in parallel,
     * then hands both to `LLMService.analyze_sql_warehouse_costs`. The single
     * prompt (`server.services.llm_service.SQL_WAREHOUSE_ANALYSIS_PROMPT`)
     * tailors itself off the `warehouse_type` field with no per-type branching.
     *
     * The analysis MUST NOT carry a cloud-cost caveat: DBU is the complete cost
     * for managed-compute warehouses (plan Q4), unlike the Pipeline and Instance
     * Pool tabs. Auto-stop tuning is the warehouse-specific cost signal
     * (`auto_stop_mins > 30` is flagged as idle DBU waste). A cost-summary
     * failure degrades to a config-only analysis rather than a 500; the
     * structured fallback covers LLM failure.
     * @param warehouseId
     * @returns SqlWarehouseAnalysis Successful Response
     * @throws ApiError
     */
    public static analyzeSqlWarehouseApiWarehousesWarehouseIdAnalyzeGet(
        warehouseId: string,
    ): CancelablePromise<SqlWarehouseAnalysis> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/warehouses/{warehouse_id}/analyze',
            path: {
                'warehouse_id': warehouseId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Sql Warehouses Health
     * Health-check endpoint for the SQL Warehouses router.
     *
     * Used as a smoke test that the router is mounted above the StaticFiles
     * catch-all in `server/app.py` — if this returns the static index.html
     * instead of JSON, the include order is wrong.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static sqlWarehousesHealthApiWarehousesHealthGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/warehouses/health',
        });
    }
}

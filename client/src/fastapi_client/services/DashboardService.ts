/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CloudPlatformInfo } from '../models/CloudPlatformInfo';
import type { ClusterAnalysis } from '../models/ClusterAnalysis';
import type { ClusterDetails } from '../models/ClusterDetails';
import type { CostAnalysis } from '../models/CostAnalysis';
import type { CostBreakdown } from '../models/CostBreakdown';
import type { CoverageTrendResponse } from '../models/CoverageTrendResponse';
import type { JobSpend } from '../models/JobSpend';
import type { OtherCostBreakdownResponse } from '../models/OtherCostBreakdownResponse';
import type { PaginatedGroupedJobs } from '../models/PaginatedGroupedJobs';
import type { PaginatedJobSpends } from '../models/PaginatedJobSpends';
import type { SummaryMetrics } from '../models/SummaryMetrics';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class DashboardService {
    /**
     * Get Job Spends
     * Get paginated job spending data with optional filters.
     *
     * Returns job spending records for the specified date range with optional job name filtering.
     * Results are paginated and sorted by total cost (highest first).
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param jobName Optional job name filter
     * @param page Page number
     * @param perPage Items per page
     * @returns PaginatedJobSpends Successful Response
     * @throws ApiError
     */
    public static getJobSpendsApiJobSpendsGet(
        startDate: string,
        endDate: string,
        jobName?: (string | null),
        page: number = 1,
        perPage: number = 50,
    ): CancelablePromise<PaginatedJobSpends> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/job-spends',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'job_name': jobName,
                'page': page,
                'per_page': perPage,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Grouped Job Spends
     * Get paginated job spending data grouped by job with aggregated costs and run details.
     *
     * Returns jobs with aggregated costs across all runs and detailed run information.
     * Each job shows total costs and individual run breakdowns for drill-down functionality.
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param jobName Optional job name filter
     * @param page Page number
     * @param perPage Items per page
     * @returns PaginatedGroupedJobs Successful Response
     * @throws ApiError
     */
    public static getGroupedJobSpendsApiGroupedJobSpendsGet(
        startDate: string,
        endDate: string,
        jobName?: (string | null),
        page: number = 1,
        perPage: number = 50,
    ): CancelablePromise<PaginatedGroupedJobs> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/grouped-job-spends',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'job_name': jobName,
                'page': page,
                'per_page': perPage,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Summary Metrics
     * Get summary metrics for job spending in the specified date range.
     *
     * Returns aggregated metrics including total spend, average cost, and breakdowns.
     * @param startDate Start date for summary (YYYY-MM-DD)
     * @param endDate End date for summary (YYYY-MM-DD)
     * @returns SummaryMetrics Successful Response
     * @throws ApiError
     */
    public static getSummaryMetricsApiSummaryGet(
        startDate: string,
        endDate: string,
    ): CancelablePromise<SummaryMetrics> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/summary',
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
     * Get Job Cost Breakdown
     * Get detailed cost breakdown for a specific job run.
     *
     * Returns EC2 vs Databricks cost breakdown and additional job details
     * for use in drill-down modals and pie charts.
     * @param jobId
     * @param runId Run ID for the specific job execution
     * @returns CostBreakdown Successful Response
     * @throws ApiError
     */
    public static getJobCostBreakdownApiJobJobIdBreakdownGet(
        jobId: string,
        runId: string,
    ): CancelablePromise<CostBreakdown> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/job/{job_id}/breakdown',
            path: {
                'job_id': jobId,
            },
            query: {
                'run_id': runId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Top Jobs
     * Get the top N most expensive jobs for the specified date range.
     *
     * Used for summary cards and highlighting high-cost jobs.
     * @param startDate Start date for top jobs (YYYY-MM-DD)
     * @param endDate End date for top jobs (YYYY-MM-DD)
     * @param limit Number of top jobs to return
     * @returns JobSpend Successful Response
     * @throws ApiError
     */
    public static getTopJobsApiTopJobsGet(
        startDate: string,
        endDate: string,
        limit: number = 5,
    ): CancelablePromise<Array<JobSpend>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/top-jobs',
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
     * Get Date Presets
     * Get common date range presets for the dashboard.
     *
     * Returns predefined date ranges like "Today", "This Week", "Last 30 Days", etc.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static getDatePresetsApiDatePresetsGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/date-presets',
        });
    }
    /**
     * Dashboard Health
     * Health check endpoint for the dashboard API.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static dashboardHealthApiHealthGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/health',
        });
    }
    /**
     * Get Databricks Host
     * Get the Databricks host URL for frontend use.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static getDatabricksHostApiDatabricksHostGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/databricks-host',
        });
    }
    /**
     * Debug Environment
     * Debug endpoint to see environment variables and client info.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static debugEnvironmentApiDebugEnvironmentGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/debug-environment',
        });
    }
    /**
     * Debug Table Data
     * Debug endpoint to see sample data from the table.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static debugTableDataApiDebugTableGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/debug-table',
        });
    }
    /**
     * Analyze Job Costs
     * Get LLM-powered cost analysis for a specific job run.
     *
     * Fetches cost breakdown, historical stats, and job name in parallel,
     * then passes all context to the LLM for grounded analysis.
     * @param jobId
     * @param runId Run ID for the specific job execution
     * @returns CostAnalysis Successful Response
     * @throws ApiError
     */
    public static analyzeJobCostsApiJobJobIdAnalyzeGet(
        jobId: string,
        runId: string,
    ): CancelablePromise<CostAnalysis> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/job/{job_id}/analyze',
            path: {
                'job_id': jobId,
            },
            query: {
                'run_id': runId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Cluster Details
     * Get detailed cluster configuration from system.compute.clusters.
     *
     * Returns cluster configuration including node types, autoscaling settings,
     * runtime version, and other configuration details.
     * @param clusterId
     * @returns ClusterDetails Successful Response
     * @throws ApiError
     */
    public static getClusterDetailsApiClusterClusterIdDetailsGet(
        clusterId: string,
    ): CancelablePromise<ClusterDetails> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/cluster/{cluster_id}/details',
            path: {
                'cluster_id': clusterId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Analyze Cluster Configuration
     * Get LLM-powered cluster configuration analysis.
     *
     * Fetches cluster details and cost summary in parallel, then passes
     * all context to the LLM for grounded configuration analysis.
     * @param clusterId
     * @returns ClusterAnalysis Successful Response
     * @throws ApiError
     */
    public static analyzeClusterConfigurationApiClusterClusterIdAnalyzeGet(
        clusterId: string,
    ): CancelablePromise<ClusterAnalysis> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/cluster/{cluster_id}/analyze',
            path: {
                'cluster_id': clusterId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Other Cost Breakdown
     * Get breakdown of 'other' (unclassified) costs by service name.
     *
     * Returns top contributing services with cost and percentage.
     * Useful for investigating what drives unclassified costs.
     * @param startDate Start date (YYYY-MM-DD)
     * @param endDate End date (YYYY-MM-DD)
     * @param clusterId Optional cluster ID filter
     * @returns OtherCostBreakdownResponse Successful Response
     * @throws ApiError
     */
    public static getOtherCostBreakdownApiOtherCostBreakdownGet(
        startDate: string,
        endDate: string,
        clusterId?: (string | null),
    ): CancelablePromise<OtherCostBreakdownResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/other-cost-breakdown',
            query: {
                'start_date': startDate,
                'end_date': endDate,
                'cluster_id': clusterId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Classification Coverage Trend
     * Get classification coverage percentage over time.
     *
     * Parsed from pipeline audit log entries. Shows how well cloud costs
     * are being classified into compute/storage/network categories.
     * @param limit Max data points to return
     * @returns CoverageTrendResponse Successful Response
     * @throws ApiError
     */
    public static getClassificationCoverageTrendApiClassificationCoverageTrendGet(
        limit: number = 30,
    ): CancelablePromise<CoverageTrendResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/classification-coverage-trend',
            query: {
                'limit': limit,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Cloud Platform Config
     * Get cloud platform configuration for dynamic UI labeling.
     * @returns CloudPlatformInfo Successful Response
     * @throws ApiError
     */
    public static getCloudPlatformConfigApiCloudPlatformGet(): CancelablePromise<CloudPlatformInfo> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/cloud-platform',
        });
    }
    /**
     * Test Databricks Connection
     * Test Databricks connection and table access.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static testDatabricksConnectionApiTestConnectionGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/test-connection',
        });
    }
}

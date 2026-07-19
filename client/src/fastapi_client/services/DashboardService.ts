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
import type { FeatureFlagsResponse } from '../models/FeatureFlagsResponse';
import type { GroupedJob } from '../models/GroupedJob';
import type { JobProductBreakdownResponse } from '../models/JobProductBreakdownResponse';
import type { JobRun } from '../models/JobRun';
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
     * @param sortBy Column to sort by across the full dataset. One of: total_cost, total_cloud_cost, total_databricks_cost, total_compute_cost, total_storage_cost, total_network_cost, total_other_cost, run_count, job_id. Unknown values fall back to total_cost.
     * @param sortDir Sort direction
     * @returns PaginatedGroupedJobs Successful Response
     * @throws ApiError
     */
    public static getGroupedJobSpendsApiGroupedJobSpendsGet(
        startDate: string,
        endDate: string,
        jobName?: (string | null),
        page: number = 1,
        perPage: number = 50,
        sortBy: string = 'total_cost',
        sortDir: 'asc' | 'desc' = 'desc',
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
                'sort_by': sortBy,
                'sort_dir': sortDir,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Job Runs
     * Get recent runs for a single job within a date range.
     *
     * Powers the lazy-loaded run breakdown shown when a job row is expanded in the
     * Job Spending Details table. `/api/grouped-job-spends` no longer embeds runs,
     * so this endpoint is fetched on-demand per job to keep the list query fast.
     * @param jobId
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @param limit Max runs to return
     * @returns JobRun Successful Response
     * @throws ApiError
     */
    public static getJobRunsApiJobJobIdRunsGet(
        jobId: string,
        startDate: string,
        endDate: string,
        limit: number = 10,
    ): CancelablePromise<Array<JobRun>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/job/{job_id}/runs',
            path: {
                'job_id': jobId,
            },
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
     * Get Feature Flags
     * Expose feature flags so the UI can gate optional affordances.
     * @returns FeatureFlagsResponse Successful Response
     * @throws ApiError
     */
    public static getFeatureFlagsApiFeaturesGet(): CancelablePromise<FeatureFlagsResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/features',
        });
    }
    /**
     * Get Job Product Breakdown
     * Read-time DBU breakdown by billing product for one job.
     *
     * Queries ``system.billing.usage`` at list price. Lazy-loaded from the Job
     * Clusters tab when a user opens the DBU breakdown popover.
     * @param jobId
     * @param startDate Start date for filtering (YYYY-MM-DD)
     * @param endDate End date for filtering (YYYY-MM-DD)
     * @returns JobProductBreakdownResponse Successful Response
     * @throws ApiError
     */
    public static getJobProductBreakdownApiJobJobIdProductBreakdownGet(
        jobId: string,
        startDate: string,
        endDate: string,
    ): CancelablePromise<JobProductBreakdownResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/job/{job_id}/product-breakdown',
            path: {
                'job_id': jobId,
            },
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
     * Returns cloud vs Databricks cost breakdown and additional job details
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
     * Get the top N most expensive jobs (aggregated per `job_id`) for the date range.
     *
     * Returns one entry per `job_id` ranked by total `cloud_cost + databricks_cost`
     * across the selected window. Shares the `GroupedJob` model with
     * `/api/grouped-job-spends` so the dashboard's "Top N Costliest Jobs" card and
     * the "Job Spending Details" table are guaranteed to agree on what a job is
     * and what its total cost is. `runs` is intentionally empty here — this
     * endpoint powers a flat top-N highlight card, not a drill-down view.
     * @param startDate Start date for top jobs (YYYY-MM-DD)
     * @param endDate End date for top jobs (YYYY-MM-DD)
     * @param limit Number of top jobs to return
     * @returns GroupedJob Successful Response
     * @throws ApiError
     */
    public static getTopJobsApiTopJobsGet(
        startDate: string,
        endDate: string,
        limit: number = 5,
    ): CancelablePromise<Array<GroupedJob>> {
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
     *
     * ``cluster_kind`` threads through to ``get_cluster_cost_summary`` so the
     * LLM's cost context comes from the rollup table that matches the cluster's
     * source (job clusters vs all-purpose / interactive clusters). When
     * ``cluster_kind`` is omitted the service layer probes
     * ``system.compute.clusters.cluster_source`` to pick the right rollup.
     * @param clusterId
     * @param clusterKind Which rollup table to pull the cluster's cost summary from. Omit to auto-detect from `system.compute.clusters.cluster_source` — required for the Instance Pools drill-down where the cluster's source isn't known client-side. Job-tab and All-Purpose-tab callers still pass 'job' / 'all_purpose' explicitly to skip the detection round-trip (see plan §6 / CP10 review #2).
     * @returns ClusterAnalysis Successful Response
     * @throws ApiError
     */
    public static analyzeClusterConfigurationApiClusterClusterIdAnalyzeGet(
        clusterId: string,
        clusterKind?: ('job' | 'all_purpose' | null),
    ): CancelablePromise<ClusterAnalysis> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/cluster/{cluster_id}/analyze',
            path: {
                'cluster_id': clusterId,
            },
            query: {
                'cluster_kind': clusterKind,
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
     *
     * When `start_date`/`end_date` are supplied the trend is bounded to that
     * window so the chart's x-axis tracks the dashboard's selected date range.
     * @param startDate Optional start date to bound the trend (YYYY-MM-DD)
     * @param endDate Optional end date to bound the trend (YYYY-MM-DD)
     * @param limit Max data points to return
     * @returns CoverageTrendResponse Successful Response
     * @throws ApiError
     */
    public static getClassificationCoverageTrendApiClassificationCoverageTrendGet(
        startDate?: (string | null),
        endDate?: (string | null),
        limit: number = 100,
    ): CancelablePromise<CoverageTrendResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/classification-coverage-trend',
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
     * Get Ai Info
     * Expose the active AI model so the UI doesn't hard-code its name.
     *
     * Returns the raw serving-endpoint name plus a human-readable label used by
     * the "Powered by ..." badges on the analysis panels. Kept lightweight (no
     * LLMService instantiation) so it never depends on credentials being set.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static getAiInfoApiAiInfoGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/ai-info',
        });
    }
}

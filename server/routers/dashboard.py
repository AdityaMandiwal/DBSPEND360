import asyncio
import logging
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from server.config.cloud_platform import cloud_config
from server.models.job_spend import (
    CloudPlatformInfo,
    ClusterAnalysis,
    ClusterDetails,
    CostAnalysis,
    CostBreakdown,
    CoverageTrendResponse,
    GroupedJob,
    JobRun,
    OtherCostBreakdownResponse,
    PaginatedGroupedJobs,
    PaginatedJobSpends,
    SummaryMetrics,
)
from server.services.databricks_service import DatabricksService
from server.services.llm_service import LLMService

router = APIRouter(prefix='/api', tags=['dashboard'])

# Lazy initialization of services
databricks_service = None
llm_service = None

def get_databricks_service():
    global databricks_service
    if databricks_service is None:
        databricks_service = DatabricksService()
    return databricks_service

def get_llm_service():
    global llm_service
    if llm_service is None:
        llm_service = LLMService()
    return llm_service


class DateRangeRequest(BaseModel):
    """Request model for date range operations."""
    start_date: date
    end_date: date


@router.get('/job-spends', response_model=PaginatedJobSpends)
async def get_job_spends(
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    job_name: Optional[str] = Query(None, description='Optional job name filter'),
    page: int = Query(1, ge=1, description='Page number'),
    per_page: int = Query(50, ge=1, le=1000, description='Items per page')
):
    """Get paginated job spending data with optional filters.

    Returns job spending records for the specified date range with optional job name filtering.
    Results are paginated and sorted by total cost (highest first).
    """
    try:
        # Validate date range
        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date'
            )

        # Calculate offset for pagination
        offset = (page - 1) * per_page

        # Get data from Databricks service
        service = get_databricks_service()
        result = await service.get_job_spends(
            start_date=start_date,
            end_date=end_date,
            job_name=job_name,
            limit=per_page,
            offset=offset
        )

        return result

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving job spending data')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve job spending data'
        )


@router.get('/grouped-job-spends', response_model=PaginatedGroupedJobs)
async def get_grouped_job_spends(
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    job_name: Optional[str] = Query(None, description='Optional job name filter'),
    page: int = Query(1, ge=1, description='Page number'),
    per_page: int = Query(50, ge=1, le=1000, description='Items per page'),
    sort_by: str = Query(
        'total_cost',
        description=(
            'Column to sort by across the full dataset. One of: total_cost, '
            'total_cloud_cost, total_databricks_cost, total_compute_cost, '
            'total_storage_cost, total_network_cost, total_other_cost, '
            'run_count, job_id. Unknown values fall back to total_cost.'
        ),
    ),
    sort_dir: Literal['asc', 'desc'] = Query('desc', description='Sort direction'),
):
    """Get paginated job spending data grouped by job with aggregated costs and run details.

    Returns jobs with aggregated costs across all runs and detailed run information.
    Each job shows total costs and individual run breakdowns for drill-down functionality.
    """
    try:
        # Validate date range
        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date'
            )

        # Calculate offset for pagination
        offset = (page - 1) * per_page

        # Get data from Databricks service
        service = get_databricks_service()
        result = await service.get_grouped_job_spends(
            start_date=start_date,
            end_date=end_date,
            job_name=job_name,
            limit=per_page,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

        return result

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving grouped job spending data')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve grouped job spending data'
        )


@router.get('/job/{job_id}/runs', response_model=list[JobRun])
async def get_job_runs(
    job_id: str,
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    limit: int = Query(10, ge=1, le=100, description='Max runs to return'),
):
    """Get recent runs for a single job within a date range.

    Powers the lazy-loaded run breakdown shown when a job row is expanded in the
    Job Spending Details table. `/api/grouped-job-spends` no longer embeds runs,
    so this endpoint is fetched on-demand per job to keep the list query fast.
    """
    try:
        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date'
            )

        service = get_databricks_service()
        return await service.get_job_runs(
            job_id=job_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving runs for job %s', job_id)
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve job runs'
        )


@router.get('/summary', response_model=SummaryMetrics)
async def get_summary_metrics(
    start_date: date = Query(..., description='Start date for summary (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for summary (YYYY-MM-DD)')
):
    """Get summary metrics for job spending in the specified date range.

    Returns aggregated metrics including total spend, average cost, and breakdowns.
    """
    try:
        # Validate date range
        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date'
            )

        # Get summary data from Databricks service
        service = get_databricks_service()
        result = await service.get_summary_metrics(
            start_date=start_date,
            end_date=end_date
        )

        return result

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving summary metrics')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve summary metrics'
        )


@router.get('/job/{job_id}/breakdown', response_model=CostBreakdown)
async def get_job_cost_breakdown(
    job_id: str,
    run_id: str = Query(..., description='Run ID for the specific job execution')
):
    """Get detailed cost breakdown for a specific job run.

    Returns cloud vs Databricks cost breakdown and additional job details
    for use in drill-down modals and pie charts.
    """
    try:
        # Get breakdown data from Databricks service
        service = get_databricks_service()
        result = await service.get_job_cost_breakdown(
            job_id=job_id,
            run_id=run_id
        )

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f'No cost breakdown found for job_id: {job_id}, run_id: {run_id}'
            )

        return result

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving job cost breakdown')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve job cost breakdown'
        )


@router.get('/top-jobs', response_model=list[GroupedJob])
async def get_top_jobs(
    start_date: date = Query(..., description='Start date for top jobs (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for top jobs (YYYY-MM-DD)'),
    limit: int = Query(5, ge=1, le=20, description='Number of top jobs to return')
):
    """Get the top N most expensive jobs (aggregated per `job_id`) for the date range.

    Returns one entry per `job_id` ranked by total `cloud_cost + databricks_cost`
    across the selected window. Shares the `GroupedJob` model with
    `/api/grouped-job-spends` so the dashboard's "Top N Costliest Jobs" card and
    the "Job Spending Details" table are guaranteed to agree on what a job is
    and what its total cost is. `runs` is intentionally empty here — this
    endpoint powers a flat top-N highlight card, not a drill-down view.
    """
    try:
        # Validate date range
        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date'
            )

        # Get top jobs from Databricks service
        service = get_databricks_service()
        result = await service.get_top_jobs(
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )

        return result

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving top jobs')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve top jobs'
        )


@router.get('/date-presets')
async def get_date_presets():
    """Get common date range presets for the dashboard.

    Returns predefined date ranges like "Today", "This Week", "Last 30 Days", etc.
    """
    today = date.today()

    presets = {
        'today': {
            'label': 'Today',
            'start_date': today,
            'end_date': today
        },
        'yesterday': {
            'label': 'Yesterday',
            'start_date': today - timedelta(days=1),
            'end_date': today - timedelta(days=1)
        },
        'this_week': {
            'label': 'This Week',
            'start_date': today - timedelta(days=today.weekday()),
            'end_date': today
        },
        'last_week': {
            'label': 'Last Week',
            'start_date': today - timedelta(days=today.weekday() + 7),
            'end_date': today - timedelta(days=today.weekday() + 1)
        },
        'this_month': {
            'label': 'This Month',
            'start_date': today.replace(day=1),
            'end_date': today
        },
        'last_7_days': {
            'label': 'Last 7 Days',
            'start_date': today - timedelta(days=7),
            'end_date': today
        },
        'last_30_days': {
            'label': 'Last 30 Days',
            'start_date': today - timedelta(days=30),
            'end_date': today
        },
        'last_90_days': {
            'label': 'Last 90 Days',
            'start_date': today - timedelta(days=90),
            'end_date': today
        }
    }

    return presets


@router.get('/health')
async def dashboard_health():
    """Health check endpoint for the dashboard API."""
    return {'status': 'healthy', 'service': 'dashboard'}


@router.get('/databricks-host')
async def get_databricks_host():
    """Get the Databricks host URL for frontend use."""
    import os
    from urllib.parse import urlparse

    # Check if we're running in Databricks Apps environment (OAuth mode)
    client_id = os.getenv('DATABRICKS_CLIENT_ID')

    try:
        if client_id:
            # Running in Databricks Apps / OAuth
            service = get_databricks_service()
            host = service.client.config.host

        else:
            # Running locally with PAT
            host = os.getenv('DATABRICKS_HOST')

            if not host:
                # Fallback to SDK client host if env not set
                service = get_databricks_service()
                if hasattr(service.client, 'config') and service.client.config.host:
                    host = service.client.config.host
                elif hasattr(service.client, 'host') and service.client.host:
                    host = service.client.host
                elif hasattr(service.client, '_host') and service.client._host:
                    host = service.client._host

        if not host:
            raise ValueError('Unable to determine Databricks workspace URL')

        # Ensure we never return a databricksapps.com URL
        parsed = urlparse(host)
        if parsed.hostname and 'databricksapps.com' in parsed.hostname:
            service = get_databricks_service()
            host = service.client.config.host

        return {'databricks_host': host}

    except HTTPException:
        raise
    except Exception:
        logger.exception('Unable to determine Databricks workspace URL')
        raise HTTPException(
            status_code=500,
            detail='Unable to determine Databricks workspace URL'
        )


@router.get('/job/{job_id}/analyze', response_model=CostAnalysis)
async def analyze_job_costs(
    job_id: str,
    run_id: str = Query(..., description='Run ID for the specific job execution'),
):
    """Get LLM-powered cost analysis for a specific job run.

    Fetches cost breakdown, historical stats, and job name in parallel,
    then passes all context to the LLM for grounded analysis.
    """
    try:
        service = get_databricks_service()

        breakdown, historical_stats, job_name = await asyncio.gather(
            service.get_job_cost_breakdown(job_id=job_id, run_id=run_id),
            service.get_job_historical_stats(
                job_id=job_id, current_run_id=run_id
            ),
            service.get_job_name(job_id=job_id),
            return_exceptions=True,
        )

        if isinstance(breakdown, Exception):
            logger.error('Failed to fetch cost breakdown for job %s run %s: %s', job_id, run_id, breakdown)
            breakdown = None
        if breakdown is None:
            raise HTTPException(
                status_code=404,
                detail=f'No cost breakdown found for job_id: {job_id}, run_id: {run_id}',
            )
        if isinstance(historical_stats, Exception):
            logger.error('Failed to fetch historical stats for job %s: %s', job_id, historical_stats)
            historical_stats = None
        if isinstance(job_name, Exception):
            logger.error('Failed to fetch job name for job %s: %s', job_id, job_name)
            job_name = None

        llm = get_llm_service()
        usage_date_str = breakdown.usage_date.isoformat()
        if breakdown.end_date:
            usage_date_str = f'{breakdown.usage_date.isoformat()} to {breakdown.end_date.isoformat()}'
        analysis = await llm.analyze_job_costs(
            job_id=job_id,
            run_id=run_id,
            cloud_cost=breakdown.cloud_cost,
            databricks_cost=breakdown.databricks_cost,
            total_cost=breakdown.total_cost,
            cluster_id=breakdown.cluster_id,
            usage_date=usage_date_str,
            job_name=job_name,
            historical_stats=historical_stats,
        )

        return CostAnalysis(
            job_id=job_id,
            run_id=run_id,
            analysis=analysis,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error generating cost analysis')
        raise HTTPException(
            status_code=500,
            detail='Failed to generate cost analysis',
        )


@router.get('/cluster/{cluster_id}/details', response_model=ClusterDetails)
async def get_cluster_details(cluster_id: str):
    """Get detailed cluster configuration from system.compute.clusters.

    Returns cluster configuration including node types, autoscaling settings,
    runtime version, and other configuration details.
    """
    try:
        # Get cluster details from Databricks service
        databricks_service = get_databricks_service()
        cluster_details = await databricks_service.get_cluster_details(cluster_id)

        if not cluster_details:
            raise HTTPException(
                status_code=404,
                detail=f'Cluster details not found for cluster_id: {cluster_id}'
            )

        return cluster_details

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving cluster details')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve cluster details'
        )


@router.get('/cluster/{cluster_id}/analyze', response_model=ClusterAnalysis)
async def analyze_cluster_configuration(
    cluster_id: str,
    cluster_kind: Optional[Literal['job', 'all_purpose']] = Query(
        None,
        description=(
            "Which rollup table to pull the cluster's cost summary from. "
            "Omit to auto-detect from `system.compute.clusters.cluster_source` "
            "— required for the Instance Pools drill-down where the cluster's "
            "source isn't known client-side. Job-tab and All-Purpose-tab "
            "callers still pass 'job' / 'all_purpose' explicitly to skip the "
            "detection round-trip (see plan §6 / CP10 review #2)."
        ),
    ),
):
    """Get LLM-powered cluster configuration analysis.

    Fetches cluster details and cost summary in parallel, then passes
    all context to the LLM for grounded configuration analysis.

    ``cluster_kind`` threads through to ``get_cluster_cost_summary`` so the
    LLM's cost context comes from the rollup table that matches the cluster's
    source (job clusters vs all-purpose / interactive clusters). When
    ``cluster_kind`` is omitted the service layer probes
    ``system.compute.clusters.cluster_source`` to pick the right rollup.
    """
    try:
        service = get_databricks_service()

        cluster_details, cost_summary = await asyncio.gather(
            service.get_cluster_details(cluster_id),
            service.get_cluster_cost_summary(cluster_id, cluster_kind=cluster_kind),
            return_exceptions=True,
        )

        if isinstance(cluster_details, Exception):
            logger.error('Failed to fetch cluster details for %s: %s', cluster_id, cluster_details)
            cluster_details = None
        if cluster_details is None:
            raise HTTPException(
                status_code=404,
                detail=f'Cluster details not found for cluster_id: {cluster_id}',
            )
        if isinstance(cost_summary, Exception):
            logger.error('Failed to fetch cluster cost summary for %s: %s', cluster_id, cost_summary)
            cost_summary = None

        llm = get_llm_service()
        analysis = await llm.analyze_cluster_configuration(
            cluster_details=cluster_details,
            cost_summary=cost_summary,
        )

        return ClusterAnalysis(
            cluster_id=cluster_id,
            analysis=analysis,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error generating cluster analysis')
        raise HTTPException(
            status_code=500,
            detail='Failed to generate cluster analysis',
        )


@router.get('/other-cost-breakdown', response_model=OtherCostBreakdownResponse)
async def get_other_cost_breakdown(
    start_date: date = Query(..., description='Start date (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date (YYYY-MM-DD)'),
    cluster_id: Optional[str] = Query(None, description='Optional cluster ID filter'),
):
    """Get breakdown of 'other' (unclassified) costs by service name.

    Returns top contributing services with cost and percentage.
    Useful for investigating what drives unclassified costs.
    """
    try:
        if start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date'
            )

        service = get_databricks_service()
        return await service.get_other_cost_breakdown(
            start_date=start_date,
            end_date=end_date,
            cluster_id=cluster_id,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving other cost breakdown')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve other cost breakdown'
        )


@router.get('/classification-coverage-trend', response_model=CoverageTrendResponse)
async def get_classification_coverage_trend(
    start_date: Optional[date] = Query(
        None, description='Optional start date to bound the trend (YYYY-MM-DD)'
    ),
    end_date: Optional[date] = Query(
        None, description='Optional end date to bound the trend (YYYY-MM-DD)'
    ),
    limit: int = Query(100, ge=1, le=366, description='Max data points to return'),
):
    """Get classification coverage percentage over time.

    Parsed from pipeline audit log entries. Shows how well cloud costs
    are being classified into compute/storage/network categories.

    When `start_date`/`end_date` are supplied the trend is bounded to that
    window so the chart's x-axis tracks the dashboard's selected date range.
    """
    try:
        if start_date and end_date and start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date'
            )

        service = get_databricks_service()
        return await service.get_classification_coverage_trend(
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving coverage trend')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve coverage trend'
        )


@router.get('/cloud-platform', response_model=CloudPlatformInfo)
async def get_cloud_platform_config():
    """Get cloud platform configuration for dynamic UI labeling."""
    try:
        return CloudPlatformInfo(
            platform=cloud_config.platform.value,
            compute_service=cloud_config.compute_service_name,
            compute_display_name=cloud_config.compute_display_name,
            platform_display_name=cloud_config.platform_display_name
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving cloud platform configuration')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve cloud platform configuration'
        )


@router.get('/ai-info')
async def get_ai_info():
    """Expose the active AI model so the UI doesn't hard-code its name.

    Returns the raw serving-endpoint name plus a human-readable label used by
    the "Powered by ..." badges on the analysis panels. Kept lightweight (no
    LLMService instantiation) so it never depends on credentials being set.
    """
    from server.services.llm_service import DEFAULT_MODEL_NAME, model_display_label

    return {
        'model_name': DEFAULT_MODEL_NAME,
        'model_label': model_display_label(DEFAULT_MODEL_NAME),
    }


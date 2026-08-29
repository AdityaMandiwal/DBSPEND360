"""Pipeline Compute router.

Implements plan §6 (`docs/plan_dlt_tab.md`). Mounts under
`/api/pipelines/*` and exposes the 6 endpoints that power the Pipeline
Compute tab (the 4th top-level tab, parallel to Job Clusters,
All-Purpose Clusters, and Instance Pools):

- `/summary`           — KPI strip with the workload-type `$` breakdown
                          and the three-bucket serverless/classic/mixed
                          split (mirrors `/api/instance-pools/summary`)
- `/grouped`           — paginated By-Pipeline table with a single
                          per-day drill-down (`days[]`); accepts the
                          optional `workload_type` chip filter
- `/top-pipelines`     — top-N most expensive pipelines (flat;
                          mirrors `/api/instance-pools/top-pools`)
- `/{id}/details`      — pipeline config from
                          `system.lakeflow.pipelines` (no REST API)
- `/{id}/analyze`      — workload-aware LLM analysis with a missing-cloud
                          caveat only when cloud coverage is incomplete
- `/health`            — smoke test for StaticFiles ordering

This tab covers ALL `usage_metadata.dlt_pipeline_id` spend (not just
DLT) dimensioned by `workload_type` per plan §0/§3.1. `pipeline_id` is
only unique within a workspace (plan §3.3/§6), so the two id-keyed
endpoints accept an optional `workspace_id` query param and return HTTP
409 (via `AmbiguousPipelineError`) rather than silently picking a
workspace when an ambiguous id is requested without it.
"""

import asyncio
import logging
from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from server.models.job_spend import (
    GroupedPipeline,
    PaginatedPipelines,
    PipelineAnalysis,
    PipelineDetails,
    PipelineSummaryMetrics,
)
from server.services.databricks_service import (
    AmbiguousPipelineError,
    DatabricksService,
)
from server.services.llm_service import LLMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/pipelines', tags=['pipelines'])


# Lazy initialization mirrors `instance_pools.py` so we share the same
# service singletons across requests without touching the Databricks SDK
# at import time (which would break local-dev startup when no credentials
# are present).
_databricks_service: Optional[DatabricksService] = None
_llm_service: Optional[LLMService] = None


def get_databricks_service() -> DatabricksService:
    """Return the singleton `DatabricksService` for this router."""
    global _databricks_service
    if _databricks_service is None:
        _databricks_service = DatabricksService()
    return _databricks_service


def get_llm_service() -> LLMService:
    """Return the singleton `LLMService` for this router."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def _validate_date_range(start_date: date, end_date: date) -> None:
    """Reject inverted windows with a 400.

    Duplicated from `instance_pools.py` per plan §6 — small helper, one-off
    duplication is preferred over a shared utility module here.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail='Start date must be before or equal to end date',
        )


def _ambiguity_409(exc: AmbiguousPipelineError) -> HTTPException:
    """Translate `AmbiguousPipelineError` into an HTTP 409 (plan §6).

    The detail names the candidate workspaces so the caller can retry with
    `?workspace_id=...` rather than receiving a silent wrong-workspace pick.
    """
    return HTTPException(
        status_code=409,
        detail=(
            f"pipeline_id '{exc.pipeline_id}' exists in "
            f"{len(exc.workspace_ids)} workspaces "
            f"({', '.join(exc.workspace_ids)}); pass workspace_id to "
            "disambiguate."
        ),
    )


@router.get('/summary', response_model=PipelineSummaryMetrics)
async def get_pipeline_summary(
    start_date: date = Query(..., description='Start date for summary (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for summary (YYYY-MM-DD)'),
    workload_type: Optional[List[str]] = Query(
        None,
        description=(
            'Optional workload-type chip filter (multi-value). Only labels / '
            'narrows; never drops spend (plan §3.1).'
        ),
    ),
):
    """Get KPI summary metrics for the Pipeline Compute tab.

    Returns the three-bucket pipeline-count split (serverless / classic /
    mixed, summing to `total_pipelines`), the matching three-bucket `$`
    split (`serverless_spend` + `classic_spend` + `mixed_spend` ==
    `total_spend`), the exact per-`workload_type` `$` breakdown, and the
    `metadata_unavailable` count (which excludes workloads that never carry
    a `system.lakeflow.pipelines` snapshot, e.g. Vector Search — plan §3.5).
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_pipeline_summary_metrics(
            start_date=start_date,
            end_date=end_date,
            workload_type=workload_type,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving pipeline summary metrics')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve pipeline summary metrics',
        )


@router.get('/grouped', response_model=PaginatedPipelines)
async def get_pipelines_grouped(
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    search: Optional[str] = Query(
        None,
        description=(
            'Optional free-text filter matched against pipeline_name '
            '(case-insensitive substring), pipeline_id (exact), and '
            'created_by (case-insensitive substring)'
        ),
    ),
    workload_type: Optional[List[str]] = Query(
        None,
        description=(
            "Optional workload-type chip filter (multi-value, e.g. "
            "'DLT Pipeline'). Only labels / narrows; never drops (plan §3.1)."
        ),
    ),
    sort_by: Literal[
        'pipeline',
        'name',
        'workload',
        'compute',
        'creator',
        'active_days',
        'cloud',
        'dbu',
        'total',
    ] = Query('total', description='Column to sort by'),
    sort_dir: Literal['asc', 'desc'] = Query('desc', description='Sort direction'),
    page: int = Query(1, ge=1, description='Page number'),
    per_page: int = Query(50, ge=1, le=1000, description='Items per page'),
):
    """Get paginated By-Pipeline rollup with a single per-day drill-down.

    One row per pipeline in the window (plan §5.1). Each row's `days` array
    carries the per-day expansion (plan §5.2); the rollup's internal product
    grain is summed away so the UI sees exactly one row per pipeline-day.
    The cost-dominant `workload_type` badge is a sum-then-`max_by` label
    (plan §3.1).
    """
    try:
        _validate_date_range(start_date, end_date)
        offset = (page - 1) * per_page
        service = get_databricks_service()
        return await service.get_pipelines_grouped(
            start_date=start_date,
            end_date=end_date,
            search=search,
            workload_type=workload_type,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=per_page,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving pipelines grouped data')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve pipelines grouped data',
        )


@router.get('/top-pipelines', response_model=list[GroupedPipeline])
async def get_top_pipelines(
    start_date: date = Query(..., description='Start date (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date (YYYY-MM-DD)'),
    limit: int = Query(5, ge=1, le=20, description='Number of top pipelines to return'),
    workload_type: Optional[List[str]] = Query(
        None,
        description=(
            'Optional workload-type chip filter (multi-value). Narrows the '
            'Top-N in lock-step with the KPI strip and table; never drops '
            'spend (plan §3.1).'
        ),
    ),
):
    """Get the top N most expensive pipelines in the window.

    Pipeline-grain analogue of `/api/instance-pools/top-pools`. Returns flat
    `GroupedPipeline` rows with `days=[]` — this endpoint powers a top-N
    highlight card and intentionally skips the per-day enrichment query for
    cost reasons (mirrors the other tabs' top-N pattern). Use `/grouped` for
    the drill-down view. Accepts the optional `workload_type` chip filter so
    the card narrows alongside the rest of the tab.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_top_pipelines(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            workload_type=workload_type,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving top pipelines')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve top pipelines',
        )


@router.get('/{pipeline_id}/details', response_model=PipelineDetails)
async def get_pipeline_details(
    pipeline_id: str,
    workspace_id: Optional[str] = Query(
        None,
        description=(
            'Optional workspace scope. `pipeline_id` is only unique within a '
            'workspace (plan §3.3/§6); omit for the single-workspace dev path. '
            'If the id spans >1 workspace and this is omitted, returns 409.'
        ),
    ),
):
    """Get pipeline configuration details for the pipeline details modal.

    Reads config straight from `system.lakeflow.pipelines` (most-recent SCD
    snapshot) — no REST API, no GUID resolution (plan §3.4). Returns a
    sentinel `PipelineDetails(metadata_missing=True, ...)` when no snapshot
    row exists (normal for Vector Search / cross-region — a made-up id must
    not raise). Returns 409 when the id is ambiguous across workspaces and
    no `workspace_id` was supplied (plan §6).
    """
    try:
        service = get_databricks_service()
        return await service.get_pipeline_details(
            pipeline_id, workspace_id=workspace_id
        )
    except AmbiguousPipelineError as e:
        raise _ambiguity_409(e)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            'Error retrieving pipeline details for %s', pipeline_id
        )
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve pipeline details',
        )


@router.get('/{pipeline_id}/analyze', response_model=PipelineAnalysis)
async def analyze_pipeline(
    pipeline_id: str,
    workspace_id: Optional[str] = Query(
        None,
        description=(
            'Optional workspace scope (see `/{id}/details`). Returns 409 if '
            'the id is ambiguous across workspaces and this is omitted.'
        ),
    ),
):
    """Get LLM-powered cost + workload analysis for a pipeline.

    Fetches `PipelineDetails` and the pipeline's cost summary in parallel,
    then hands both to `LLMService.analyze_pipeline_costs`. The single
    workload-aware prompt
    (`server.services.llm_service.PIPELINE_ANALYSIS_PROMPT`) tailors itself
    off the `workload_type` field with no per-product branching (plan §4.1).

    The analysis includes "excludes cloud VM cost" only when the cost summary
    reports incomplete cloud coverage. The structured fallback carries the
    same conditional so the invariant holds on LLM failure.
    """
    try:
        service = get_databricks_service()

        pipeline_details, cost_summary = await asyncio.gather(
            service.get_pipeline_details(pipeline_id, workspace_id=workspace_id),
            service.get_pipeline_cost_summary(
                pipeline_id, workspace_id=workspace_id
            ),
            return_exceptions=True,
        )

        # An ambiguous id surfaces as an exception from either gathered call;
        # translate it to a 409 rather than a 500 (plan §6).
        for result in (pipeline_details, cost_summary):
            if isinstance(result, AmbiguousPipelineError):
                raise _ambiguity_409(result)

        if isinstance(pipeline_details, Exception):
            logger.error(
                'Failed to fetch pipeline details for %s: %s',
                pipeline_id,
                pipeline_details,
            )
            raise HTTPException(
                status_code=500,
                detail='Failed to fetch pipeline details',
            )
        if isinstance(cost_summary, Exception):
            logger.error(
                'Failed to fetch pipeline cost summary for %s: %s',
                pipeline_id,
                cost_summary,
            )
            cost_summary = None

        llm = get_llm_service()
        analysis = await llm.analyze_pipeline_costs(
            pipeline_details=pipeline_details,
            cost_summary=cost_summary,
        )

        return PipelineAnalysis(
            pipeline_id=pipeline_id,
            analysis=analysis,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception(
            'Error generating pipeline analysis for %s', pipeline_id
        )
        raise HTTPException(
            status_code=500,
            detail='Failed to generate pipeline analysis',
        )


@router.get('/health')
async def pipelines_health():
    """Health-check endpoint for the Pipeline Compute router.

    Used as a smoke test that the router is mounted above the StaticFiles
    catch-all in `server/app.py` (plan §10 risks table) — if this returns
    the static index.html instead of JSON, the include order is wrong.
    """
    return {'status': 'healthy', 'service': 'pipelines'}

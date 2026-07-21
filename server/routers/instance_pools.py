"""Instance Pools router.

Implements plan §6 (`docs/plan_instance_pools_tab.md`). Mounts under
`/api/instance-pools/*` and exposes the 6 endpoints that power the
Instance Pools tab (parallel to the Job Clusters and All-Purpose
Clusters routers in `dashboard.py` and `all_purpose.py`):

- `/summary`           — KPI strip (mirrors `/api/all-purpose/summary`)
- `/daily-trend`       — calendar-day pool spend series for the
                          Daily Pool Spend Trend sparkline
- `/grouped`           — paginated By-Pool table with two-level
                          drill-down (`days[].clusters[]`)
- `/top-pools`         — top-N most expensive pools (flat;
                          mirrors `/api/all-purpose/top-clusters`)
- `/{id}/details`      — pool config + REST-resolved creator GUID
                          for the pool details modal
- `/{id}/analyze`      — pool-tuned LLM configuration analysis with
                          the mandatory idle-vs-active-split caveat
                          (CP8 / plan_pool_pipeline_ec2_cost.md §4.5)
- `/health`            — smoke test for StaticFiles ordering

Per plan §3.4 / §4.1 the list endpoint deliberately does NOT enrich
each row with the REST-resolved creator GUID (the
`system.compute.instance_pools.tags` source column excludes default
tags, so `DatabricksInstancePoolCreatorId` is REST-only — fanning out
a REST call per row would defeat the table's caching story). Creator
GUID enrichment lives in `/{id}/details` and transitively in
`/{id}/analyze` via `get_pool_metadata`.
"""

import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from server.models.job_spend import (
    GroupedInstancePool,
    InstancePoolAnalysis,
    InstancePoolDailyTrendPoint,
    InstancePoolDetails,
    InstancePoolSummaryMetrics,
    PaginatedInstancePools,
)
from server.services.databricks_service import DatabricksService
from server.services.llm_service import LLMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/instance-pools', tags=['instance-pools'])


# Lazy initialization mirrors the pattern in `dashboard.py` and
# `all_purpose.py` so we share the same service singletons across
# requests without touching the Databricks SDK at import time (which
# would break local-dev startup when no credentials are present).
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

    Duplicated from `all_purpose.py` per plan §6 — small helper, one-off
    duplication is preferred over a shared utility module here.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail='Start date must be before or equal to end date',
        )


@router.get('/summary', response_model=InstancePoolSummaryMetrics)
async def get_instance_pool_summary(
    start_date: date = Query(..., description='Start date for summary (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for summary (YYYY-MM-DD)'),
):
    """Get KPI summary metrics for the Instance Pools tab.

    Returns aggregated metrics across the window: total spend, distinct
    pool + cluster counts, count of pools with `pool_snapshot_missing = TRUE`
    (the "orphaned pools" KPI surfaced for cross-region / pre-Oct-2023
    deleted pools per plan §10), and per-pool-day cost statistics
    (avg/max/min) computed at the `(instance_pool_id, usage_date)` grain.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_instance_pool_summary_metrics(
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving instance pool summary metrics')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve instance pool summary metrics',
        )


@router.get('/daily-trend', response_model=list[InstancePoolDailyTrendPoint])
async def get_instance_pool_daily_trend(
    start_date: date = Query(..., description='Start date (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date (YYYY-MM-DD)'),
):
    """Get daily aggregate pool spend for the trend sparkline.

    Returns one point per calendar day in the window (zero-filled when no
    covered-workspace pool spend landed). Powers the Daily Pool Spend Trend
    card on the Instance Pools tab.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_instance_pool_daily_trend(
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving instance pool daily trend')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve instance pool daily trend',
        )


@router.get('/grouped', response_model=PaginatedInstancePools)
async def get_instance_pools_grouped(
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    search: Optional[str] = Query(
        None,
        description=(
            'Optional free-text filter matched against pool_name '
            '(case-insensitive substring), instance_pool_id (exact), and '
            'cluster_id (exact, via a back-reference to the filtered rows)'
        ),
    ),
    page: int = Query(1, ge=1, description='Page number'),
    per_page: int = Query(50, ge=1, le=1000, description='Items per page'),
):
    """Get paginated By-Pool rollup with two-level drill-down.

    One row per instance pool in the window. Each row's `days` array
    carries the per-day expansion, and each day's `clusters` array
    carries the per-cluster expansion (plan §3.3 / §5.2). The list
    endpoint deliberately does NOT enrich rows with the REST-resolved
    creator GUID — creator info is modal-only in v1 per plan §3.4 /
    §4.1 / CP10 regression guard.
    """
    try:
        _validate_date_range(start_date, end_date)
        offset = (page - 1) * per_page
        service = get_databricks_service()
        return await service.get_instance_pools_grouped(
            start_date=start_date,
            end_date=end_date,
            search=search,
            limit=per_page,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving instance pools grouped data')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve instance pools grouped data',
        )


@router.get('/top-pools', response_model=list[GroupedInstancePool])
async def get_top_instance_pools(
    start_date: date = Query(..., description='Start date (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date (YYYY-MM-DD)'),
    limit: int = Query(5, ge=1, le=20, description='Number of top pools to return'),
):
    """Get the top N most expensive instance pools in the window.

    Pool-grain analogue of `/api/top-jobs` and
    `/api/all-purpose/top-clusters`. Returns flat `GroupedInstancePool`
    rows with `days=[]` — this endpoint powers a top-N highlight card
    and intentionally skips the per-day + per-cluster enrichment query
    for cost reasons (mirrors the existing top-N endpoints' `runs=[]`
    / `users=[]` pattern). Use `/grouped` for the drill-down view.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_top_instance_pools(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving top instance pools')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve top instance pools',
        )


@router.get('/{pool_id}/details', response_model=InstancePoolDetails)
async def get_instance_pool_details(pool_id: str):
    """Get pool configuration details for the pool details modal.

    Reads pool config from `system.compute.instance_pools` (most-recent
    SCD snapshot) and enriches the creator GUID via a per-request call
    to the Instance Pools REST API
    (`default_tags['DatabricksInstancePoolCreatorId']`). Per plan §3.4
    / §10, the system table's `tags` column excludes default tags, so
    the REST API is the only source for the auto-applied creator tag.

    Returns a sentinel `InstancePoolDetails(pool_snapshot_missing=True, ...)`
    when no system-table snapshot row exists. The REST API call is still
    attempted in the sentinel path so a deleted-but-still-tracked pool
    can surface its name + creator GUID.

    GUID -> email resolution is deferred to v2 (plan §13).
    """
    try:
        service = get_databricks_service()
        return await service.get_instance_pool_details(pool_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            'Error retrieving instance pool details for %s', pool_id
        )
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve instance pool details',
        )


@router.get('/{pool_id}/analyze', response_model=InstancePoolAnalysis)
async def analyze_instance_pool(pool_id: str):
    """Get LLM-powered configuration + cost analysis for an instance pool.

    Fetches `InstancePoolDetails` and the pool's cost summary in
    parallel, then hands both to `LLMService.analyze_instance_pool_costs`.
    The pool prompt
    (`server.services.llm_service.INSTANCE_POOL_ANALYSIS_PROMPT`) is
    built on top of `CLUSTER_ANALYSIS_SYSTEM_PROMPT`'s config-analysis
    shape (Overall Rating / Right-Sizing / Cost Savings / Idle Waste
    Risk / Configuration Gaps) — pool analysis is a configuration-shape
    question closer to `analyze_cluster_configuration` than to a
    per-run trend analysis.

    As of CP8 (plan_pool_pipeline_ec2_cost.md §4.4) pool EC2/EBS cost is
    joined into the cost summary, so the prompt MANDATES only the remaining
    idle-vs-active-split caveat ("the idle-vs-active VM cost split is not
    available yet" — §4.5) rather than the old DBU-only caveat; the response
    must include that string and the structured fallback
    (`_build_pool_fallback`) carries it too so the invariant holds on LLM
    failure.
    """
    try:
        service = get_databricks_service()

        pool_details, cost_summary = await asyncio.gather(
            service.get_instance_pool_details(pool_id),
            service.get_pool_cost_summary(pool_id),
            return_exceptions=True,
        )

        if isinstance(pool_details, Exception):
            logger.error(
                'Failed to fetch pool details for %s: %s',
                pool_id,
                pool_details,
            )
            raise HTTPException(
                status_code=500,
                detail='Failed to fetch pool details',
            )
        if isinstance(cost_summary, Exception):
            logger.error(
                'Failed to fetch pool cost summary for %s: %s',
                pool_id,
                cost_summary,
            )
            cost_summary = None

        llm = get_llm_service()
        analysis = await llm.analyze_instance_pool_costs(
            pool_details=pool_details,
            cost_summary=cost_summary,
        )

        return InstancePoolAnalysis(
            instance_pool_id=pool_id,
            analysis=analysis,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception(
            'Error generating instance pool analysis for %s', pool_id
        )
        raise HTTPException(
            status_code=500,
            detail='Failed to generate instance pool analysis',
        )


@router.get('/health')
async def instance_pools_health():
    """Health-check endpoint for the Instance Pools router.

    Used as a smoke test that the router is mounted above the StaticFiles
    catch-all in `server/app.py` (per plan §10 risks table) — if this
    returns the static index.html instead of JSON, the include order is
    wrong.
    """
    return {'status': 'healthy', 'service': 'instance-pools'}

"""All-Purpose Clusters router.

Implements plan §6 (`docs/plan_all_purpose_clusters_tab.md`). Mounts under
`/api/all-purpose/*` and exposes the 5 endpoints that power the All-Purpose
Clusters tab (parallel to the Job Clusters tab served by `dashboard.py`):

- `/summary`             — KPI strip (mirrors `/api/summary`)
- `/grouped-by-cluster`  — paginated By-Cluster table (mirrors `/api/grouped-job-spends`)
- `/grouped-by-user`     — paginated By-User chargeback table (no analogue today)
- `/top-clusters`        — top-N most expensive clusters (mirrors `/api/top-jobs`)
- `/top-users`           — top-N most expensive users (chargeback)

Cluster-detail and LLM-analysis endpoints (`/api/cluster/{id}/details`,
`/api/cluster/{id}/analyze`) are reused as-is from `dashboard_router` — they
are already cluster-source-agnostic.
"""

import logging
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from server.models.job_spend import (
    AllPurposeSummaryMetrics,
    GroupedAllPurposeCluster,
    GroupedAllPurposeUser,
    PaginatedAllPurposeClusters,
    PaginatedAllPurposeUsers,
)
from server.services.databricks_service import DatabricksService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/all-purpose', tags=['all-purpose'])


# Lazy initialization mirrors the pattern in `dashboard.py` so we share the
# same DatabricksService instance across requests but avoid touching the
# Databricks SDK at import time (which would break local-dev startup when no
# credentials are present).
_databricks_service: Optional[DatabricksService] = None


def get_databricks_service() -> DatabricksService:
    """Return a singleton `DatabricksService` for this router.

    Note: this is intentionally a separate module-level singleton from the
    one in `dashboard.py`. Both lazily call `DatabricksService()` which is
    idempotent for our purposes — the SDK client and warehouse_id are
    derived from the same config.
    """
    global _databricks_service
    if _databricks_service is None:
        _databricks_service = DatabricksService()
    return _databricks_service


def _validate_date_range(start_date: date, end_date: date) -> None:
    """Reject inverted windows with a 400 (mirrors `dashboard.py` style)."""
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail='Start date must be before or equal to end date',
        )


@router.get('/summary', response_model=AllPurposeSummaryMetrics)
async def get_all_purpose_summary(
    start_date: date = Query(..., description='Start date for summary (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for summary (YYYY-MM-DD)'),
):
    """Get KPI summary metrics for the All-Purpose tab.

    Returns aggregated metrics across the window: total spend, distinct
    cluster + user counts, and per-cluster-day cost statistics. Mirrors
    `/api/summary` in shape but reports cluster and user counts rather than
    job counts (the all-purpose model is keyed by user, not job).
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_all_purpose_summary_metrics(
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving all-purpose summary metrics')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve all-purpose summary metrics',
        )


@router.get('/grouped-by-cluster', response_model=PaginatedAllPurposeClusters)
async def get_all_purpose_grouped_by_cluster(
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    search: Optional[str] = Query(
        None,
        description='Optional free-text filter matched against cluster_name, cluster_id, and owner_user_id',
    ),
    page: int = Query(1, ge=1, description='Page number'),
    per_page: int = Query(50, ge=1, le=1000, description='Items per page'),
    sort_by: str = Query('total_cost', description='Column to sort by'),
    sort_dir: Literal['asc', 'desc'] = Query('desc', description='Sort direction'),
):
    """Get paginated By-Cluster all-purpose spend, with per-day drill-down.

    One row per cluster in the window, with the owner's `user_id` and
    `data_security_mode` denormalized. Each row's `users` array is
    pre-populated with the per-day breakdown for that cluster (under v1
    owner attribution, one user per day — the cluster owner).
    """
    try:
        _validate_date_range(start_date, end_date)
        offset = (page - 1) * per_page
        service = get_databricks_service()
        return await service.get_all_purpose_grouped_by_cluster(
            start_date=start_date,
            end_date=end_date,
            search=search,
            limit=per_page,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving all-purpose grouped-by-cluster data')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve all-purpose grouped-by-cluster data',
        )


@router.get('/grouped-by-user', response_model=PaginatedAllPurposeUsers)
async def get_all_purpose_grouped_by_user(
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    search: Optional[str] = Query(
        None,
        description='Optional free-text filter matched against user_id (case-insensitive)',
    ),
    page: int = Query(1, ge=1, description='Page number'),
    per_page: int = Query(50, ge=1, le=1000, description='Items per page'),
    sort_by: str = Query('total_cost', description='Column to sort by'),
    sort_dir: Literal['asc', 'desc'] = Query('desc', description='Sort direction'),
):
    """Get paginated By-User all-purpose spend (chargeback view).

    One row per user (cluster owner) in the window, with per-cluster
    drill-down enrichment. `user_active_days` is computed correctly
    (distinct days from raw rows, not summed across clusters) — see plan
    §5.2 for why summing would double-count.
    """
    try:
        _validate_date_range(start_date, end_date)
        offset = (page - 1) * per_page
        service = get_databricks_service()
        return await service.get_all_purpose_grouped_by_user(
            start_date=start_date,
            end_date=end_date,
            search=search,
            limit=per_page,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving all-purpose grouped-by-user data')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve all-purpose grouped-by-user data',
        )


@router.get('/top-clusters', response_model=list[GroupedAllPurposeCluster])
async def get_all_purpose_top_clusters(
    start_date: date = Query(..., description='Start date (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date (YYYY-MM-DD)'),
    limit: int = Query(5, ge=1, le=20, description='Number of top clusters to return'),
):
    """Get the top N most expensive all-purpose clusters in the window.

    Cluster-grain analogue of `/api/top-jobs`. Returns flat
    `GroupedAllPurposeCluster` rows with `users=[]` — this endpoint powers
    a top-N highlight card and intentionally skips per-day enrichment for
    cost reasons. Use `/grouped-by-cluster` for the drill-down view.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_all_purpose_top_clusters(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving all-purpose top clusters')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve all-purpose top clusters',
        )


@router.get('/top-users', response_model=list[GroupedAllPurposeUser])
async def get_all_purpose_top_users(
    start_date: date = Query(..., description='Start date (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date (YYYY-MM-DD)'),
    limit: int = Query(5, ge=1, le=20, description='Number of top users to return'),
):
    """Get the top N most expensive all-purpose users in the window.

    User-grain (chargeback) analogue of `/api/top-jobs`. Returns flat
    `GroupedAllPurposeUser` rows with `clusters=[]`. Use `/grouped-by-user`
    for the per-user drill-down with per-cluster expansion.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_all_purpose_top_users(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving all-purpose top users')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve all-purpose top users',
        )


@router.get('/health')
async def all_purpose_health():
    """Health-check endpoint for the All-Purpose router.

    Used as a smoke test that the router is mounted above the StaticFiles
    catch-all in `server/app.py` (per plan §10 risks table) — if this
    returns the static index.html instead of JSON, the include order is
    wrong.
    """
    return {'status': 'healthy', 'service': 'all-purpose'}

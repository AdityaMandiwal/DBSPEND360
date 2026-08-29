"""SQL Warehouses router.

Implements plan §3d (`docs/plans/sql-warehouse-costs.md`). Mounts under
`/api/warehouses/*` and exposes the 6 endpoints that power the SQL Warehouses
tab (the 5th top-level tab, parallel to Job Clusters, All-Purpose Clusters,
Instance Pools, and Pipeline Compute):

- `/summary`         — KPI strip with the exhaustive Classic / Pro / Serverless
                        count and `$` split
- `/grouped`         — paginated By-Warehouse table with a per-day drill-down
                        (`days[]`)
- `/top-warehouses`  — top-N most expensive warehouses (flat)
- `/{id}/details`    — warehouse config denormalized from
                        `system.compute.warehouses`
- `/{id}/analyze`    — LLM cost analysis
- `/health`          — smoke test for StaticFiles ordering

This tab is DBU-only: all three warehouse types run on Databricks-managed
compute, so there are no customer VMs to attribute cloud cost to and DBU IS
the complete cost (plan Q4). No cloud-cost fields appear on any response.

Unlike `pipelines.py`, no endpoint takes a `workspace_id`: `warehouse_id` is
account-unique (validated Q1/Q2), so there is no cross-workspace ambiguity to
disambiguate and no 409 path.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from server.models.job_spend import (
    GroupedSqlWarehouse,
    PaginatedSqlWarehouses,
    SqlWarehouseAnalysis,
    SqlWarehouseDetails,
    SqlWarehouseSummaryMetrics,
)
from server.services.databricks_service import DatabricksService
from server.services.llm_service import LLMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/warehouses', tags=['sql-warehouses'])


# Lazy initialization mirrors `pipelines.py` so we share the same service
# singletons across requests without touching the Databricks SDK at import
# time (which would break local-dev startup when no credentials are present).
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

    Duplicated from `pipelines.py` — small helper, one-off duplication is
    preferred over a shared utility module here.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail='Start date must be before or equal to end date',
        )


@router.get('/summary', response_model=SqlWarehouseSummaryMetrics)
async def get_sql_warehouse_summary(
    start_date: date = Query(..., description='Start date for summary (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for summary (YYYY-MM-DD)'),
):
    """Get KPI summary metrics for the SQL Warehouses tab.

    Returns the exhaustive three-bucket warehouse-count split (classic + pro +
    serverless == `total_warehouses`) and the matching `$` split
    (`classic_spend` + `pro_spend` + `serverless_spend` == `total_spend`).
    `total_spend` equals tracked DBU. This is complete for Serverless and
    DBU-only for Classic/Pro until cloud infrastructure can be attributed.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_sql_warehouse_summary_metrics(
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving SQL warehouse summary metrics')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve SQL warehouse summary metrics',
        )


@router.get('/grouped', response_model=PaginatedSqlWarehouses)
async def get_sql_warehouses_grouped(
    start_date: date = Query(..., description='Start date for filtering (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date for filtering (YYYY-MM-DD)'),
    search: Optional[str] = Query(
        None,
        description=(
            'Optional free-text filter matched against warehouse_name '
            '(case-insensitive substring) and warehouse_id (exact)'
        ),
    ),
    page: int = Query(1, ge=1, description='Page number'),
    per_page: int = Query(50, ge=1, le=1000, description='Items per page'),
    sort_by: Literal[
        'total_cost', 'total_databricks_cost', 'active_days', 'warehouse_name'
    ] = Query('total_cost'),
    sort_dir: Literal['asc', 'desc'] = Query('desc'),
):
    """Get paginated By-Warehouse rollup with a per-day drill-down.

    One row per warehouse in the window. Each row's `days` array carries the
    per-day expansion, so the sum of `days[].total_cost` equals the row's
    `total_cost`.
    """
    try:
        _validate_date_range(start_date, end_date)
        offset = (page - 1) * per_page
        service = get_databricks_service()
        return await service.get_sql_warehouses_grouped(
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
        logger.exception('Error retrieving SQL warehouses grouped data')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve SQL warehouses grouped data',
        )


@router.get('/top-warehouses', response_model=list[GroupedSqlWarehouse])
async def get_top_sql_warehouses(
    start_date: date = Query(..., description='Start date (YYYY-MM-DD)'),
    end_date: date = Query(..., description='End date (YYYY-MM-DD)'),
    limit: int = Query(5, ge=1, le=20, description='Number of top warehouses to return'),
):
    """Get the top N most expensive SQL warehouses in the window.

    Returns flat `GroupedSqlWarehouse` rows with `days=[]` — this endpoint
    powers a top-N highlight card and intentionally skips the per-day
    enrichment query for cost reasons (mirrors the other tabs' top-N pattern).
    Use `/grouped` for the drill-down view.
    """
    try:
        _validate_date_range(start_date, end_date)
        service = get_databricks_service()
        return await service.get_top_sql_warehouses(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving top SQL warehouses')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve top SQL warehouses',
        )


@router.get('/{warehouse_id}/details', response_model=SqlWarehouseDetails)
async def get_sql_warehouse_details(warehouse_id: str):
    """Get warehouse configuration details for the details modal.

    Reads the config denormalized into the rollup from
    `system.compute.warehouses` (name, type, size, creator, auto-stop,
    min/max clusters, deleted-at) plus a best-effort `tags` lookup. Returns a
    sentinel `SqlWarehouseDetails(metadata_missing=True, ...)` when no rollup
    row exists so a made-up id renders the neutral badge instead of raising.

    No `workspace_id` param: `warehouse_id` is account-unique, so there is no
    ambiguity to resolve.
    """
    try:
        service = get_databricks_service()
        return await service.get_sql_warehouse_details(warehouse_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving SQL warehouse details for %s', warehouse_id)
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve SQL warehouse details',
        )


@router.get('/{warehouse_id}/analyze', response_model=SqlWarehouseAnalysis)
async def analyze_sql_warehouse(
    warehouse_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    """Get LLM-powered cost analysis for a SQL warehouse.

    Fetches `SqlWarehouseDetails` and the warehouse's cost summary in parallel,
    then hands both to `LLMService.analyze_sql_warehouse_costs`. The single
    prompt (`server.services.llm_service.SQL_WAREHOUSE_ANALYSIS_PROMPT`)
    tailors itself off the `warehouse_type` field with no per-type branching.

    The requested window matches the table/modal. When dates are omitted for
    backward compatibility, the latest 30 inclusive calendar days are used.
    Classic/Pro analysis must disclose that tracked spend excludes customer
    cloud infrastructure.
    """
    try:
        if (start_date is None) != (end_date is None):
            raise HTTPException(
                status_code=400,
                detail='start_date and end_date must be provided together',
            )
        resolved_end = end_date or date.today()
        resolved_start = start_date or (resolved_end - timedelta(days=29))
        _validate_date_range(resolved_start, resolved_end)
        service = get_databricks_service()

        warehouse_details, cost_summary = await asyncio.gather(
            service.get_sql_warehouse_details(warehouse_id),
            service.get_sql_warehouse_cost_summary(
                warehouse_id,
                start_date=resolved_start,
                end_date=resolved_end,
            ),
            return_exceptions=True,
        )

        if isinstance(warehouse_details, Exception):
            logger.error(
                'Failed to fetch SQL warehouse details for %s: %s',
                warehouse_id,
                warehouse_details,
            )
            raise HTTPException(
                status_code=500,
                detail='Failed to fetch SQL warehouse details',
            )
        if isinstance(cost_summary, Exception):
            logger.error(
                'Failed to fetch SQL warehouse cost summary for %s: %s',
                warehouse_id,
                cost_summary,
            )
            cost_summary = None

        llm = get_llm_service()
        analysis = await llm.analyze_sql_warehouse_costs(
            warehouse_details=warehouse_details,
            cost_summary=cost_summary,
        )

        return SqlWarehouseAnalysis(
            warehouse_id=warehouse_id,
            analysis=analysis,
            start_date=resolved_start,
            end_date=resolved_end,
            cost_basis=(
                cost_summary.get('cost_basis', warehouse_details.cost_basis)
                if cost_summary
                else warehouse_details.cost_basis
            ),
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception('Error generating SQL warehouse analysis for %s', warehouse_id)
        raise HTTPException(
            status_code=500,
            detail='Failed to generate SQL warehouse analysis',
        )


@router.get('/health')
async def sql_warehouses_health():
    """Health-check endpoint for the SQL Warehouses router.

    Used as a smoke test that the router is mounted above the StaticFiles
    catch-all in `server/app.py` — if this returns the static index.html
    instead of JSON, the include order is wrong.
    """
    return {'status': 'healthy', 'service': 'sql-warehouses'}

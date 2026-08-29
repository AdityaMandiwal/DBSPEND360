"""Subscription coverage aggregate endpoint."""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from server.models.job_spend import CoverageSummaryResponse
from server.services.databricks_service import DatabricksService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['coverage'])

_databricks_service: Optional[DatabricksService] = None


def get_databricks_service() -> DatabricksService:
    global _databricks_service
    if _databricks_service is None:
        _databricks_service = DatabricksService()
    return _databricks_service


@router.get('/coverage', response_model=CoverageSummaryResponse)
async def get_coverage_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    """Return the full subscription-coverage map for banners and KPIs.

    When a date range is supplied, excluded-workspace and excluded-DBU values
    are scoped to that same inclusive window so they reconcile with tab KPIs.
    """
    try:
        if start_date and end_date and start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail='Start date must be before or equal to end date',
            )
        service = get_databricks_service()
        return await service.get_coverage_summary(
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception('Error retrieving coverage summary')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve coverage summary',
        )

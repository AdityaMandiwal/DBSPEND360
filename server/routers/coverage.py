"""Subscription coverage aggregate endpoint."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

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
async def get_coverage_summary():
    """Return the full subscription-coverage map for banners and KPIs.

    Single param-less call; the client fetches once and each tab reads its
    own key from `excluded_dbu_by_tab`.
    """
    try:
        service = get_databricks_service()
        return await service.get_coverage_summary()
    except Exception:
        logger.exception('Error retrieving coverage summary')
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve coverage summary',
        )

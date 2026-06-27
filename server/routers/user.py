"""User router for Databricks user information."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter()


class UserInfo(BaseModel):
  """Databricks user information."""

  userName: str
  displayName: str | None = None
  active: bool
  emails: list[str] = []


class UserWorkspaceInfo(BaseModel):
  """User and workspace information."""

  user: UserInfo
  workspace: dict


@router.get('/me', response_model=UserInfo)
async def get_current_user():
  """Get current user information from Databricks."""
  try:
    service = UserService()
    user_info = service.get_user_info()

    return UserInfo(
      userName=user_info['userName'],
      displayName=user_info['displayName'],
      active=user_info['active'],
      emails=user_info['emails'],
    )
  except Exception:
    logger.exception('Failed to fetch user info')
    raise HTTPException(status_code=500, detail='Failed to fetch user info')


@router.get('/me/workspace', response_model=UserWorkspaceInfo)
async def get_user_workspace_info():
  """Get user information along with workspace details."""
  try:
    service = UserService()
    info = service.get_user_workspace_info()

    return UserWorkspaceInfo(
      user=UserInfo(
        userName=info['user']['userName'],
        displayName=info['user']['displayName'],
        active=info['user']['active'],
      ),
      workspace=info['workspace'],
    )
  except Exception:
    logger.exception('Failed to fetch workspace info')
    raise HTTPException(status_code=500, detail='Failed to fetch workspace info')

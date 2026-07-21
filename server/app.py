"""FastAPI application for Databricks App Template."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.routers import router
from server.routers.all_purpose import router as all_purpose_router
from server.routers.dashboard import router as dashboard_router
from server.routers.instance_pools import router as instance_pools_router
from server.routers.pipelines import router as pipelines_router
from server.routers.coverage import router as coverage_router


# Load environment variables from .env.local if it exists
def load_env_file(filepath: str) -> None:
  """Load environment variables from a file."""
  if Path(filepath).exists():
    with open(filepath) as f:
      for line in f:
        line = line.strip()
        if line and not line.startswith('#'):
          key, _, value = line.partition('=')
          if key and value:
            os.environ[key] = value


# Load .env files
load_env_file('.env')
load_env_file('.env.local')


@asynccontextmanager
async def lifespan(app: FastAPI):
  """Manage application lifespan."""
  yield


app = FastAPI(
  title='Databricks App API',
  description='Modern FastAPI application template for Databricks Apps with React frontend',
  version='0.1.0',
  lifespan=lifespan,
)

app.add_middleware(
  CORSMiddleware,
  allow_origins=['*'],  # Allow all origins for development
  allow_credentials=False,  # Set to False when using allow_origins=['*']
  allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allow_headers=['*'],
)

app.include_router(router, prefix='/api', tags=['api'])
app.include_router(dashboard_router)
app.include_router(all_purpose_router)
app.include_router(instance_pools_router)
app.include_router(pipelines_router)
app.include_router(coverage_router)


@app.get('/health')
async def health():
  """Health check endpoint."""
  return {'status': 'healthy'}


# ============================================================================
# SERVE STATIC FILES FROM CLIENT BUILD DIRECTORY (MUST BE LAST!)
# ============================================================================
# This static file mount MUST be the last route registered!
# It catches all unmatched requests and serves the React app.
# Any routes added after this will be unreachable!
if os.path.exists('client/build'):
  app.mount('/', StaticFiles(directory='client/build', html=True), name='static')

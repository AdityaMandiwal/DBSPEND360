import logging
import os
import time
from datetime import date, timedelta
from typing import Dict, List, Literal, Optional, Tuple

from databricks.sdk import WorkspaceClient

from server.config.config_loader import app_config
from server.models.job_spend import (
    AllPurposeClusterSpend,
    AllPurposeSummaryMetrics,
    AllPurposeUserSpend,
    ClusterDetails,
    CostBreakdown,
    CoverageTrendPoint,
    CoverageTrendResponse,
    GroupedAllPurposeCluster,
    GroupedAllPurposeUser,
    GroupedInstancePool,
    GroupedJob,
    GroupedPipeline,
    InstancePoolClusterSpend,
    InstancePoolDailySpend,
    InstancePoolDetails,
    InstancePoolSummaryMetrics,
    JobProductBreakdownItem,
    JobProductBreakdownResponse,
    JobRun,
    JobSpend,
    OtherCostBreakdownItem,
    OtherCostBreakdownResponse,
    PaginatedAllPurposeClusters,
    PaginatedAllPurposeUsers,
    PaginatedGroupedJobs,
    PaginatedInstancePools,
    PaginatedJobSpends,
    PaginatedPipelines,
    PipelineDailySpend,
    PipelineDetails,
    PipelineSummaryMetrics,
    SummaryMetrics,
)

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 180

# Friendly `workload_type` labels (mirrors WORKLOAD_MAP in
# `pipeline_spends_app.ipynb`, plan §5.5) that are *expected* to carry a
# `system.lakeflow.pipelines` snapshot. Reused by the §5.3 metadata-missing KPI
# so the count only flags pipelines that SHOULD have metadata but don't —
# workloads that never get a snapshot (e.g. Vector Search) are excluded by
# design so the number stays meaningful (plan §3.5).
METADATA_BEARING_WORKLOADS = (
    'DLT Pipeline',
    'DBSQL Materialized View',
    'Online Table',
)


class AmbiguousPipelineError(Exception):
    """Raised when a `pipeline_id` is requested without a `workspace_id` but
    that id exists in more than one workspace.

    `pipeline_id` is only unique within a workspace (plan §3.3/§6), so the
    id-keyed endpoints (`/{id}/details`, `/{id}/analyze`) must refuse to
    silently pick a workspace. The router translates this into an HTTP 409
    naming the candidate workspaces rather than returning a wrong-workspace
    pipeline.
    """

    def __init__(self, pipeline_id: str, workspace_ids: List[str]):
        self.pipeline_id = pipeline_id
        self.workspace_ids = workspace_ids
        super().__init__(
            f"pipeline_id '{pipeline_id}' exists in {len(workspace_ids)} "
            f"workspaces ({', '.join(workspace_ids)}); pass workspace_id to "
            "disambiguate."
        )

# How long to cache the job_id -> name map resolved from system.lakeflow.jobs.
# That system table costs ~4-5s to scan regardless of filtering, so we collapse
# it once and reuse the result. Job names rarely change, so modest staleness is
# an acceptable trade for a ~5x faster job list/search.
JOB_NAME_MAP_TTL_SECONDS = 30 * 60

# Friendly labels for billing_origin_product in job DBU breakdowns.
_JOB_PRODUCT_LABELS: Dict[str, str] = {
    'JOBS': 'Job Compute',
    'MODEL_SERVING': 'Model Serving',
    'AI_FUNCTIONS': 'AI Functions',
}


class DatabricksService:
    """Service for interacting with Databricks SQL Warehouse."""

    def __init__(self):
        # Check if we're running in Databricks Apps (OAuth available)
        client_id = os.getenv('DATABRICKS_CLIENT_ID')
        host = os.getenv('DATABRICKS_HOST')
        token = os.getenv('DATABRICKS_TOKEN')

        if client_id:
            # Running in Databricks Apps - use OAuth automatically
            self.client = WorkspaceClient()
        elif host and token:
            # Running locally with PAT
            self.client = WorkspaceClient(
                host=host,
                token=token
            )
        else:
            raise ValueError('Either DATABRICKS_CLIENT_ID (for OAuth) or both DATABRICKS_HOST and DATABRICKS_TOKEN (for PAT) must be set')

        # Load configuration from environment-specific config files
        self.warehouse_id = app_config.warehouse_id
        self.table_name = app_config.table_name
        self.all_purpose_table_name = app_config.all_purpose_table_name
        self.pool_table_name = app_config.pool_table_name
        self.pipeline_table_name = app_config.pipeline_table_name
        self.query_timeout = app_config.query_timeout_seconds
        self.job_name_cache: Dict[str, str] = {}  # Cache for job names
        # Bulk {job_id: latest_name} map cached with a TTL. Populated from
        # system.lakeflow.jobs (see `_get_job_name_map`). Lets the grouped job
        # query skip the expensive SCD join and attach names in Python instead.
        self._job_name_map: Optional[Dict[str, str]] = None
        self._job_name_map_ts: float = 0.0
        # Lazy cache for pool name + creator GUID resolved per-request via
        # WorkspaceClient.instance_pools.get(...). Plan §3.4 / §4.1 / CP6:
        # the system table's `tags` column excludes default tags so the
        # auto-applied `DatabricksInstancePoolCreatorId` is not visible there;
        # we resolve the GUID per-request and cache the (name, guid) tuple.
        # Failure tuples (f"Pool {id}", None) are cached too so a flaky or
        # nonexistent pool ID does not re-issue the REST API on every render.
        self.pool_metadata_cache: Dict[str, Tuple[str, Optional[str]]] = {}
        # Read-time job DBU product breakdown cache keyed by (job_id, start, end).
        self._product_breakdown_cache: Dict[
            Tuple[str, str, str], Tuple[JobProductBreakdownResponse, float]
        ] = {}

    async def get_job_name(self, job_id: str) -> str:
        """Get job name from Jobs API with caching."""
        if job_id in self.job_name_cache:
            return self.job_name_cache[job_id]

        try:
            # Try to get job details from Jobs API
            job = self.client.jobs.get(job_id=int(job_id))
            job_name = job.settings.name if job.settings and job.settings.name else f'Job {job_id}'
            self.job_name_cache[job_id] = job_name
            return job_name
        except Exception:
            # If job doesn't exist or we can't access it, return a default name
            job_name = f'Job {job_id}'
            self.job_name_cache[job_id] = job_name
            return job_name

    def _get_job_name_map(self, force_refresh: bool = False) -> Dict[str, str]:
        """Return a cached {job_id: latest_name} map for all jobs.

        Joining system.lakeflow.jobs on every request is the dominant cost of
        the job list/search (~4-5s) because that system table has a high fixed
        read cost and does not prune on job_id or name. We collapse its SCD
        history to the latest name per job once, cache it with a TTL, and let
        callers attach names in Python so the hot query never touches it.
        On refresh failure we serve the previous (stale) map if available.
        """
        now = time.monotonic()
        if (
            not force_refresh
            and self._job_name_map is not None
            and (now - self._job_name_map_ts) < JOB_NAME_MAP_TTL_SECONDS
        ):
            return self._job_name_map

        query = """
        SELECT job_id, MAX_BY(name, change_time) AS name
        FROM system.lakeflow.jobs
        GROUP BY job_id
        """
        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query,
            )
            name_map: Dict[str, str] = {}
            if response.result and response.result.data_array:
                for row in response.result.data_array:
                    if row[0] is not None and row[1] is not None:
                        name_map[str(row[0])] = row[1]
            self._job_name_map = name_map
            self._job_name_map_ts = now
            return name_map
        except Exception as e:
            logger.error('Failed to refresh job name map: %s', e)
            return self._job_name_map if self._job_name_map is not None else {}

    async def get_job_spends(
        self,
        start_date: date,
        end_date: date,
        job_name: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> PaginatedJobSpends:
        """Get paginated job spending data with optional job name filter."""
        # Build the base query with direct string interpolation
        where_clause = f"WHERE usage_date >= '{start_date.isoformat()}' AND usage_date <= '{end_date.isoformat()}'"

        # Add job name filter if provided
        if job_name:
            # Escape single quotes in job_name to prevent SQL injection
            escaped_job_name = job_name.replace("'", "''")
            where_clause += f" AND job_id LIKE '%{escaped_job_name}%'"

        # Count query for pagination
        count_query = f"""
        SELECT COUNT(*) as total_count
        FROM {self.table_name}
        {where_clause}
        """

        # Data query with pagination
        data_query = f"""
        SELECT
            a.cluster_id,
            a.cloud_cost,
            a.job_id,
            a.run_id,
            a.usage_date,
            a.databricks_cost,
            jobs.name as job_name,
            a.compute_cost,
            a.storage_cost,
            a.network_cost,
            a.other_cost
        FROM {self.table_name} a
        LEFT OUTER JOIN (
            -- Collapse SCD history in system.lakeflow.jobs down to the most
            -- recent name per job_id. A bare LEFT JOIN against the raw table
            -- multiplies each spend row by the number of historical snapshots
            -- for that job_id, producing duplicate rows for renamed jobs.
            SELECT job_id, MAX_BY(name, change_time) AS name
            FROM system.lakeflow.jobs
            GROUP BY job_id
        ) jobs ON a.job_id = jobs.job_id
        {where_clause}
        ORDER BY (a.cloud_cost + a.databricks_cost) DESC
        LIMIT {limit} OFFSET {offset}
        """

        # Execute count query
        count_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=count_query
        )

        total_count = 0
        if count_response.result and count_response.result.data_array:
            total_count = int(count_response.result.data_array[0][0])

        # Execute data query
        data_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=data_query
        )

        job_spends = []
        if data_response.result and data_response.result.data_array:
            for row in data_response.result.data_array:
                job_id = row[2]

                job_spend = JobSpend(
                    cluster_id=row[0],
                    cloud_cost=float(row[1]),
                    job_id=job_id,
                    job_name=row[6],
                    run_id=row[3],
                    usage_date=date.fromisoformat(row[4]),
                    databricks_cost=float(row[5]),
                    compute_cost=float(row[7]) if row[7] is not None else None,
                    storage_cost=float(row[8]) if row[8] is not None else None,
                    network_cost=float(row[9]) if row[9] is not None else None,
                    other_cost=float(row[10]) if row[10] is not None else None,
                )
                job_spends.append(job_spend)

        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit
        current_page = (offset // limit) + 1

        return PaginatedJobSpends(
            data=job_spends,
            total_count=total_count,
            page=current_page,
            per_page=limit,
            total_pages=total_pages,
            has_next=current_page < total_pages,
            has_previous=current_page > 1
        )

    async def get_summary_metrics(self, start_date: date, end_date: date) -> SummaryMetrics:
        """Get summary metrics for the specified date range.

        Uses the same `filtered -> run_level -> job_level` CTE chain as
        `get_top_jobs()` / `get_grouped_job_spends()` so KPI cards speak the
        same job-level / run-level model as the lists below them and the
        numbers can be reconciled:

        - `total_jobs` counts distinct `job_id`s in the window (not raw spend
          rows). Same denominator as the "Job Spending Details" table.
        - `average_cost` / `max_cost` / `min_cost` are computed at the run
          level (one row per `(job_id, run_id)`, summed across days), so the
          "Highest Cost" card is the costliest actual job execution and a user
          can drill into it from `/api/grouped-job-spends`.
        - `total_*_cost` sums are taken at the run level too, which is
          arithmetically identical to summing the raw rows but stays
          consistent with the rest of the query's grain.
        """
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        run_level AS (
            SELECT
                job_id,
                run_id,
                SUM(cloud_cost) AS cloud_cost,
                SUM(databricks_cost) AS databricks_cost,
                SUM(compute_cost) AS compute_cost,
                SUM(storage_cost) AS storage_cost,
                SUM(network_cost) AS network_cost,
                SUM(other_cost) AS other_cost
            FROM filtered
            GROUP BY job_id, run_id
        ),
        job_level AS (
            SELECT job_id
            FROM run_level
            GROUP BY job_id
        )
        SELECT
            (SELECT COUNT(*) FROM job_level) AS total_jobs,
            SUM(cloud_cost + databricks_cost) AS total_spend,
            AVG(cloud_cost + databricks_cost) AS avg_cost,
            MAX(cloud_cost + databricks_cost) AS max_cost,
            MIN(cloud_cost + databricks_cost) AS min_cost,
            SUM(cloud_cost) AS total_cloud_cost,
            SUM(databricks_cost) AS total_databricks_cost,
            SUM(compute_cost) AS total_compute_cost,
            SUM(storage_cost) AS total_storage_cost,
            SUM(network_cost) AS total_network_cost,
            SUM(other_cost) AS total_other_cost
        FROM run_level
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        if response.result and response.result.data_array:
            row = response.result.data_array[0]
            date_range_days = (end_date - start_date).days + 1

            total_compute = float(row[7]) if row[7] is not None else None
            total_storage = float(row[8]) if row[8] is not None else None
            total_network = float(row[9]) if row[9] is not None else None
            total_other = float(row[10]) if row[10] is not None else None

            total_cloud = float(row[5]) if row[5] else 0.0
            coverage_pct = None
            if total_compute is not None and total_cloud > 0:
                classified = (total_compute or 0) + (total_storage or 0) + (total_network or 0)
                coverage_pct = (classified / total_cloud) * 100

            coverage_status = None
            coverage_warning = None
            if coverage_pct is not None:
                if coverage_pct >= 95:
                    coverage_status = 'ok'
                elif coverage_pct >= 80:
                    coverage_status = 'warning'
                    coverage_warning = (
                        "Moderate unclassified cost detected. "
                        "Review the 'Other' category for potential classification improvements."
                    )
                else:
                    coverage_status = 'critical'
                    coverage_warning = (
                        "High unclassified cost detected. "
                        "Investigate 'Other' category immediately."
                    )

            return SummaryMetrics(
                total_jobs=int(row[0]) if row[0] else 0,
                total_spend=float(row[1]) if row[1] else 0.0,
                average_cost=float(row[2]) if row[2] else 0.0,
                max_cost=float(row[3]) if row[3] else 0.0,
                min_cost=float(row[4]) if row[4] else 0.0,
                total_cloud_cost=total_cloud,
                total_databricks_cost=float(row[6]) if row[6] else 0.0,
                total_compute_cost=total_compute,
                total_storage_cost=total_storage,
                total_network_cost=total_network,
                total_other_cost=total_other,
                classification_coverage_pct=coverage_pct,
                coverage_status=coverage_status,
                coverage_warning=coverage_warning,
                date_range_days=date_range_days
            )

        return SummaryMetrics(
            total_jobs=0,
            total_spend=0.0,
            average_cost=0.0,
            max_cost=0.0,
            min_cost=0.0,
            total_cloud_cost=0.0,
            total_databricks_cost=0.0,
            date_range_days=(end_date - start_date).days + 1
        )

    async def get_job_cost_breakdown(self, job_id: str, run_id: str) -> Optional[CostBreakdown]:
        """Get detailed cost breakdown for a specific job run, aggregated across all days."""
        escaped_job_id = job_id.replace("'", "''")
        escaped_run_id = run_id.replace("'", "''")

        query = f"""
        SELECT
            job_id,
            run_id,
            MIN(cluster_id) as cluster_id,
            MIN(usage_date) as start_date,
            MAX(usage_date) as end_date,
            SUM(cloud_cost) as total_cloud_cost,
            SUM(databricks_cost) as total_databricks_cost,
            SUM(compute_cost) as total_compute_cost,
            SUM(storage_cost) as total_storage_cost,
            SUM(network_cost) as total_network_cost,
            SUM(other_cost) as total_other_cost
        FROM {self.table_name}
        WHERE job_id = '{escaped_job_id}' AND run_id = '{escaped_run_id}'
        GROUP BY job_id, run_id
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        if response.result and response.result.data_array:
            row = response.result.data_array[0]
            cloud_cost = float(row[5])
            databricks_cost = float(row[6])
            start_date = date.fromisoformat(row[3])
            end_date = date.fromisoformat(row[4])

            return CostBreakdown(
                job_id=row[0],
                run_id=row[1],
                cluster_id=row[2],
                usage_date=start_date,
                end_date=end_date if end_date != start_date else None,
                cloud_cost=cloud_cost,
                databricks_cost=databricks_cost,
                total_cost=cloud_cost + databricks_cost,
                compute_cost=float(row[7]) if row[7] is not None else None,
                storage_cost=float(row[8]) if row[8] is not None else None,
                network_cost=float(row[9]) if row[9] is not None else None,
                other_cost=float(row[10]) if row[10] is not None else None,
            )

        return None

    async def get_top_jobs(self, start_date: date, end_date: date, limit: int = 5) -> List[GroupedJob]:
        """Get top N most expensive jobs (aggregated per job_id) for the date range.

        Returns one row per `job_id` ranked by total `cloud_cost + databricks_cost`
        across the window. Uses the same `filtered -> run_level -> job_level` CTE
        chain as `get_grouped_job_spends()` so the "Top N Costliest Jobs" card and
        the "Job Spending Details" table speak the exact same job-level model and
        cannot disagree on what a job's total cost is.

        The returned `GroupedJob` objects intentionally carry `runs=[]`: this
        endpoint only powers a flat top-N card and skips the per-run enrichment
        query for cost reasons. See the model docstring on `GroupedJob`.
        """
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        run_level AS (
            SELECT
                job_id,
                run_id,
                SUM(cloud_cost) AS cloud_cost,
                SUM(databricks_cost) AS databricks_cost,
                SUM(compute_cost) AS compute_cost,
                SUM(storage_cost) AS storage_cost,
                SUM(network_cost) AS network_cost,
                SUM(other_cost) AS other_cost
            FROM filtered
            GROUP BY job_id, run_id
        ),
        job_level AS (
            SELECT
                job_id,
                SUM(cloud_cost) AS total_cloud_cost,
                SUM(databricks_cost) AS total_databricks_cost,
                SUM(compute_cost) AS total_compute_cost,
                SUM(storage_cost) AS total_storage_cost,
                SUM(network_cost) AS total_network_cost,
                SUM(other_cost) AS total_other_cost,
                COUNT(*) AS run_count
            FROM run_level
            GROUP BY job_id
        )
        SELECT
            j.job_id,
            j.total_cloud_cost,
            j.total_databricks_cost,
            j.run_count,
            lj.name,
            j.total_compute_cost,
            j.total_storage_cost,
            j.total_network_cost,
            j.total_other_cost
        FROM job_level j
        LEFT JOIN (
            -- Same SCD-collapse used by get_grouped_job_spends(): pick the
            -- most-recent name per job_id so a renamed job doesn't fan out
            -- into multiple top-N entries.
            SELECT job_id, MAX_BY(name, change_time) AS name
            FROM system.lakeflow.jobs
            GROUP BY job_id
        ) lj ON j.job_id = lj.job_id
        ORDER BY (j.total_cloud_cost + j.total_databricks_cost) DESC
        LIMIT {limit}
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        jobs: List[GroupedJob] = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                jobs.append(GroupedJob(
                    job_id=row[0],
                    job_name=row[4],
                    run_count=int(row[3]),
                    total_cloud_cost=float(row[1]),
                    total_databricks_cost=float(row[2]),
                    total_compute_cost=float(row[5]) if row[5] is not None else None,
                    total_storage_cost=float(row[6]) if row[6] is not None else None,
                    total_network_cost=float(row[7]) if row[7] is not None else None,
                    total_other_cost=float(row[8]) if row[8] is not None else None,
                    runs=[],
                ))

        return jobs

    # Whitelist of server-sortable grouped-job columns mapped to their SQL
    # expressions. Anything not in this map falls back to total cost so a bad
    # `sort_by` can never inject SQL or 500 the query. `job_name` is
    # intentionally absent — names are resolved from an in-memory map in Python
    # (not the SQL scan), so they can't be globally ordered server-side.
    _GROUPED_JOB_SORT_COLUMNS = {
        'job_id': 'job_id',
        'run_count': 'run_count',
        'total_cloud_cost': 'total_cloud_cost',
        'total_databricks_cost': 'total_databricks_cost',
        'total_compute_cost': 'total_compute_cost',
        'total_storage_cost': 'total_storage_cost',
        'total_network_cost': 'total_network_cost',
        'total_other_cost': 'total_other_cost',
        'total_cost': '(total_cloud_cost + total_databricks_cost)',
    }

    async def get_grouped_job_spends(
        self,
        start_date: date,
        end_date: date,
        job_name: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = 'total_cost',
        sort_dir: str = 'desc',
    ) -> PaginatedGroupedJobs:
        """Get paginated job spending data grouped by job with run details.

        The job_name parameter is used as a general search term that matches
        against both job name (from system.lakeflow.jobs) and job ID.

        `sort_by` / `sort_dir` apply a server-side ORDER BY over the *full*
        aggregated dataset (not just the current page) so header clicks in the
        UI reflect a global sort. Invalid columns fall back to total cost.
        """
        # Resolve job names from the in-memory cached map rather than joining
        # system.lakeflow.jobs in the hot query. That join costs ~4-5s on every
        # request (the system table has a high fixed read cost and does not
        # prune on job_id/name) and dominated the latency; the aggregation
        # itself is only ~1s. Names are attached in Python below.
        name_map = self._get_job_name_map()

        # For a search, resolve the matching job_ids from the cached name map so
        # the scan never has to touch system.lakeflow.jobs. We still keep a
        # job_id LIKE predicate so an id substring matches even for jobs missing
        # from the name map.
        usage_search_filter = ''
        if job_name:
            escaped_search = job_name.replace("'", "''")
            term = job_name.lower()
            id_predicates = [f"job_id LIKE '%{escaped_search}%'"]
            name_matched_ids = [
                jid for jid, nm in name_map.items() if nm and term in nm.lower()
            ]
            if name_matched_ids:
                # Cap the IN-list defensively; a term matching thousands of jobs
                # is a degenerate search and the LIKE predicate still applies.
                escaped_ids = [j.replace("'", "''") for j in name_matched_ids[:5000]]
                in_list = ', '.join(f"'{j}'" for j in escaped_ids)
                id_predicates.append(f'job_id IN ({in_list})')
            usage_search_filter = 'AND (' + ' OR '.join(id_predicates) + ')'

        order_column = self._GROUPED_JOB_SORT_COLUMNS.get(
            sort_by, '(total_cloud_cost + total_databricks_cost)'
        )
        direction = 'ASC' if str(sort_dir).lower() == 'asc' else 'DESC'
        # `job_id` tiebreaker keeps pagination deterministic when two jobs share
        # the sort value (otherwise the same row could appear on two pages).
        order_clause = f'ORDER BY {order_column} {direction} NULLS LAST, job_id ASC'

        data_query = f"""
        WITH filtered AS (
            SELECT
                job_id,
                run_id,
                cloud_cost,
                databricks_cost,
                compute_cost,
                storage_cost,
                network_cost,
                other_cost
            FROM {self.table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
            AND usage_date <= '{end_date.isoformat()}'
            {usage_search_filter}
        ),
        run_level AS (
            SELECT
                job_id,
                run_id,
                SUM(cloud_cost) AS cloud_cost,
                SUM(databricks_cost) AS databricks_cost,
                SUM(compute_cost) AS compute_cost,
                SUM(storage_cost) AS storage_cost,
                SUM(network_cost) AS network_cost,
                SUM(other_cost) AS other_cost
            FROM filtered
            GROUP BY job_id, run_id
        ),
        job_level AS (
            SELECT
                job_id,
                SUM(cloud_cost) AS total_cloud_cost,
                SUM(databricks_cost) AS total_databricks_cost,
                SUM(compute_cost) AS total_compute_cost,
                SUM(storage_cost) AS total_storage_cost,
                SUM(network_cost) AS total_network_cost,
                SUM(other_cost) AS total_other_cost,
                COUNT(*) AS run_count
            FROM run_level
            GROUP BY job_id
        )
        SELECT
            job_id,
            total_cloud_cost,
            total_databricks_cost,
            run_count,
            COUNT(*) OVER() AS total_matching,
            total_compute_cost,
            total_storage_cost,
            total_network_cost,
            total_other_cost
        FROM job_level
        {order_clause}
        LIMIT {limit} OFFSET {offset}
        """

        data_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=data_query
        )

        total_count = 0
        if data_response.result and data_response.result.data_array:
            total_count = int(data_response.result.data_array[0][4])

        grouped_jobs = []
        if data_response.result and data_response.result.data_array:
            # Runs are intentionally NOT fetched here. Previously this method
            # issued a second batch query (`_get_batch_job_runs`) for every job
            # on the page, doubling the warehouse round-trips on each search even
            # though runs are only ever shown when a row is expanded. Runs are
            # now lazy-loaded per job via `get_job_runs()` / the
            # `/api/job/{job_id}/runs` endpoint when the user expands a row.
            for row in data_response.result.data_array:
                job_id = row[0]
                total_cloud_cost = float(row[1])
                total_databricks_cost = float(row[2])
                run_count = int(row[3])

                grouped_job = GroupedJob(
                    job_id=job_id,
                    job_name=name_map.get(str(job_id)),
                    run_count=run_count,
                    total_cloud_cost=total_cloud_cost,
                    total_databricks_cost=total_databricks_cost,
                    total_compute_cost=float(row[5]) if row[5] is not None else None,
                    total_storage_cost=float(row[6]) if row[6] is not None else None,
                    total_network_cost=float(row[7]) if row[7] is not None else None,
                    total_other_cost=float(row[8]) if row[8] is not None else None,
                    runs=[],
                )
                grouped_jobs.append(grouped_job)

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        current_page = (offset // limit) + 1

        return PaginatedGroupedJobs(
            data=grouped_jobs,
            total_count=total_count,
            page=current_page,
            per_page=limit,
            total_pages=total_pages,
            has_next=current_page < total_pages,
            has_previous=current_page > 1
        )

    async def _get_batch_job_runs(
        self,
        job_ids: List[str],
        start_date: date,
        end_date: date,
        runs_per_job: int = 10
    ) -> dict[str, List[JobRun]]:
        """Fetch runs for multiple jobs in a single SQL query, returning at most runs_per_job per job."""
        if not job_ids:
            return {}

        escaped_ids = [jid.replace("'", "''") for jid in job_ids]
        in_clause = ', '.join(f"'{jid}'" for jid in escaped_ids)

        query = f"""
        WITH ranked_runs AS (
            SELECT
                job_id,
                run_id,
                cluster_id,
                MIN(usage_date) as start_date,
                MAX(usage_date) as end_date,
                SUM(cloud_cost) as total_cloud_cost,
                SUM(databricks_cost) as total_databricks_cost,
                SUM(compute_cost) as total_compute_cost,
                SUM(storage_cost) as total_storage_cost,
                SUM(network_cost) as total_network_cost,
                SUM(other_cost) as total_other_cost,
                ROW_NUMBER() OVER (
                    PARTITION BY job_id
                    ORDER BY MAX(usage_date) DESC, run_id DESC
                ) as rn
            FROM {self.table_name}
            WHERE job_id IN ({in_clause})
            AND usage_date >= '{start_date.isoformat()}'
            AND usage_date <= '{end_date.isoformat()}'
            GROUP BY job_id, run_id, cluster_id
        )
        SELECT job_id, run_id, cluster_id, start_date, end_date,
               total_cloud_cost, total_databricks_cost,
               total_compute_cost, total_storage_cost, total_network_cost,
               total_other_cost
        FROM ranked_runs
        WHERE rn <= {runs_per_job}
        ORDER BY job_id, end_date DESC, run_id DESC
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        runs_by_job: dict[str, List[JobRun]] = {}
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                job_id = row[0]
                run = JobRun(
                    run_id=row[1],
                    cluster_id=row[2],
                    start_date=date.fromisoformat(row[3]),
                    end_date=date.fromisoformat(row[4]),
                    cloud_cost=float(row[5]),
                    databricks_cost=float(row[6]),
                    compute_cost=float(row[7]) if row[7] is not None else None,
                    storage_cost=float(row[8]) if row[8] is not None else None,
                    network_cost=float(row[9]) if row[9] is not None else None,
                    other_cost=float(row[10]) if row[10] is not None else None,
                )
                runs_by_job.setdefault(job_id, []).append(run)

        return runs_by_job

    async def get_job_runs(self, job_id: str, start_date: date, end_date: date, limit: int = 10) -> List[JobRun]:
        """Get recent runs for a specific job within date range, aggregated by run_id."""
        # Escape single quotes to prevent SQL injection
        escaped_job_id = job_id.replace("'", "''")

        query = f"""
        SELECT
            run_id,
            cluster_id,
            MIN(usage_date) as start_date,
            MAX(usage_date) as end_date,
            SUM(cloud_cost) as total_cloud_cost,
            SUM(databricks_cost) as total_databricks_cost,
            SUM(compute_cost) as total_compute_cost,
            SUM(storage_cost) as total_storage_cost,
            SUM(network_cost) as total_network_cost,
            SUM(other_cost) as total_other_cost
        FROM {self.table_name}
        WHERE job_id = '{escaped_job_id}'
        AND usage_date >= '{start_date.isoformat()}'
        AND usage_date <= '{end_date.isoformat()}'
        GROUP BY run_id, cluster_id
        ORDER BY end_date DESC, run_id DESC
        LIMIT {limit}
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        runs = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                run = JobRun(
                    run_id=row[0],
                    cluster_id=row[1],
                    start_date=date.fromisoformat(row[2]),
                    end_date=date.fromisoformat(row[3]),
                    cloud_cost=float(row[4]),
                    databricks_cost=float(row[5]),
                    compute_cost=float(row[6]) if row[6] is not None else None,
                    storage_cost=float(row[7]) if row[7] is not None else None,
                    network_cost=float(row[8]) if row[8] is not None else None,
                    other_cost=float(row[9]) if row[9] is not None else None,
                )
                runs.append(run)

        return runs

    def _product_label(self, billing_origin_product: str) -> str:
        return _JOB_PRODUCT_LABELS.get(
            billing_origin_product, billing_origin_product
        )

    async def get_job_product_breakdown(
        self,
        job_id: str,
        start_date: date,
        end_date: date,
    ) -> JobProductBreakdownResponse:
        """Read-time DBU split by billing_origin_product for one job.

        Queries ``system.billing.usage`` joined to ``system.billing.list_prices``
        filtered by ``usage_metadata.job_id`` and ``job_run_id IS NOT NULL``.
        Does NOT mirror the rollup ETL's ``cluster_source = 'JOB'`` inner join —
        the goal is to expose all products that billed against job runs.
        """
        cache_key = (job_id, start_date.isoformat(), end_date.isoformat())
        cache_ttl = app_config.cache_ttl_minutes * 60
        now = time.monotonic()
        cached = self._product_breakdown_cache.get(cache_key)
        if cached and (now - cached[1]) < cache_ttl:
            return cached[0]

        escaped_job_id = job_id.replace("'", "''")
        wait_timeout = f'{self.query_timeout}s'

        breakdown_query = f"""
        WITH usage_priced AS (
            SELECT
                u.billing_origin_product,
                u.usage_quantity,
                CAST(lp.pricing['default'] AS DOUBLE) AS unit_price
            FROM system.billing.usage u
            LEFT JOIN system.billing.list_prices lp
                ON  u.sku_name = lp.sku_name
                AND u.usage_start_time >= lp.price_start_time
                AND (
                    u.usage_start_time < lp.price_end_time
                    OR lp.price_end_time IS NULL
                )
            WHERE u.usage_metadata.job_id = '{escaped_job_id}'
              AND u.usage_metadata.job_run_id IS NOT NULL
              AND u.usage_date >= '{start_date.isoformat()}'
              AND u.usage_date <= '{end_date.isoformat()}'
        )
        SELECT
            COALESCE(billing_origin_product, 'UNKNOWN') AS product,
            ROUND(SUM(usage_quantity * unit_price), 2) AS cost,
            SUM(
                CASE WHEN unit_price IS NULL THEN usage_quantity ELSE 0 END
            ) AS unpriced_qty
        FROM usage_priced
        GROUP BY 1
        HAVING cost > 0 OR unpriced_qty > 0
        ORDER BY cost DESC
        """

        rollup_query = f"""
        SELECT ROUND(SUM(databricks_cost), 2)
        FROM {self.table_name}
        WHERE job_id = '{escaped_job_id}'
          AND usage_date >= '{start_date.isoformat()}'
          AND usage_date <= '{end_date.isoformat()}'
        """

        breakdown_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=breakdown_query,
            wait_timeout=wait_timeout,
        )

        rollup_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=rollup_query,
            wait_timeout=wait_timeout,
        )

        items: List[JobProductBreakdownItem] = []
        total_unpriced_qty = 0.0
        raw_items: List[tuple[str, float]] = []
        if breakdown_response.result and breakdown_response.result.data_array:
            for row in breakdown_response.result.data_array:
                cost = float(row[1]) if row[1] is not None else 0.0
                unpriced_qty = float(row[2]) if row[2] is not None else 0.0
                total_unpriced_qty += unpriced_qty
                if cost > 0:
                    raw_items.append((row[0] or 'UNKNOWN', cost))

        total_cost = round(sum(cost for _, cost in raw_items), 2)
        for product, cost in raw_items:
            percentage = round((cost / total_cost) * 100, 1) if total_cost > 0 else 0.0
            items.append(
                JobProductBreakdownItem(
                    billing_origin_product=product,
                    label=self._product_label(product),
                    cost=cost,
                    percentage=percentage,
                )
            )

        rollup_databricks_cost = None
        if rollup_response.result and rollup_response.result.data_array:
            raw_rollup = rollup_response.result.data_array[0][0]
            if raw_rollup is not None:
                rollup_databricks_cost = float(raw_rollup)

        unpriced_warning = None
        if total_unpriced_qty > 0:
            unpriced_warning = (
                'Some usage rows had no matching list price; breakdown may be '
                'understated.'
            )

        response = JobProductBreakdownResponse(
            job_id=job_id,
            start_date=start_date,
            end_date=end_date,
            items=items,
            total_cost=total_cost,
            rollup_databricks_cost=rollup_databricks_cost,
            has_multiple_products=len(items) > 1,
            is_estimate=True,
            unpriced_warning=unpriced_warning,
        )
        self._product_breakdown_cache[cache_key] = (response, now)
        return response

    async def get_cluster_details(self, cluster_id: str) -> Optional[ClusterDetails]:
        """Get cluster configuration details from system.compute.clusters."""
        try:
            # Escape single quotes to prevent SQL injection
            escaped_cluster_id = cluster_id.replace("'", "''")

            # Query the system.compute.clusters table for cluster details.
            # `cluster_source` is read so we can distinguish JOB (ephemeral) from
            # interactive clusters — auto-termination is N/A for JOB clusters.
            query = f"""
            SELECT
                cluster_id,
                owned_by,
                create_time,
                driver_node_type,
                worker_node_type,
                worker_count,
                min_autoscale_workers,
                max_autoscale_workers,
                auto_termination_minutes,
                enable_elastic_disk,
                tags,
                aws_attributes,
                azure_attributes,
                gcp_attributes,
                dbr_version,
                data_security_mode,
                cluster_source,
                cluster_name
            FROM system.compute.clusters
            WHERE cluster_id = '{escaped_cluster_id}'
            LIMIT 1
            """

            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query
            )

            if response.result and response.result.data_array and len(response.result.data_array) > 0:
                row = response.result.data_array[0]

                # Parse tags and provider-specific attribute blocks as JSON if they exist
                import json
                tags = None
                aws_attributes = None
                azure_attributes = None
                gcp_attributes = None

                try:
                    if row[10]:  # tags
                        tags = json.loads(row[10])
                except:
                    tags = {'raw': row[10]} if row[10] else None

                try:
                    if row[11]:  # aws_attributes
                        aws_attributes = json.loads(row[11])
                except:
                    aws_attributes = {'raw': row[11]} if row[11] else None

                try:
                    if row[12]:  # azure_attributes
                        azure_attributes = json.loads(row[12])
                except:
                    azure_attributes = {'raw': row[12]} if row[12] else None

                try:
                    if row[13]:  # gcp_attributes
                        gcp_attributes = json.loads(row[13])
                except:
                    gcp_attributes = {'raw': row[13]} if row[13] else None

                return ClusterDetails(
                    cluster_id=row[0],
                    owned_by=row[1],
                    create_time=row[2],
                    driver_node_type=row[3],
                    worker_node_type=row[4],
                    worker_count=int(row[5]) if row[5] is not None else None,
                    min_autoscale_workers=int(row[6]) if row[6] is not None else None,
                    max_autoscale_workers=int(row[7]) if row[7] is not None else None,
                    auto_termination_minutes=int(row[8]) if row[8] is not None else None,
                    enable_elastic_disk=self._parse_bool(row[9]),
                    tags=tags,
                    aws_attributes=aws_attributes,
                    azure_attributes=azure_attributes,
                    gcp_attributes=gcp_attributes,
                    dbr_version=row[14],
                    data_security_mode=row[15],
                    cluster_source=row[16],
                    cluster_name=row[17],
                )

            return None

        except Exception as e:
            logger.error('Error fetching cluster details for %s: %s', cluster_id, str(e))
            return None

    async def get_job_historical_stats(
        self, job_id: str, current_run_id: str
    ) -> Optional[dict]:
        """Get historical cost statistics for a job, excluding the current run from baseline.

        Joins `system.lakeflow.job_run_timeline` to filter the baseline to
        SUCCEEDED runs only, so CANCELED / FAILED / TIMED_OUT runs do not
        skew the trend. Falls back to an unfiltered baseline (with
        `state_filter_applied=False`) when the timeline table grant is
        unavailable.

        Returns:
            dict with baseline metrics and comparison, or None on failure.
        """
        filtered = await self._get_job_historical_stats_filtered(
            job_id=job_id, current_run_id=current_run_id
        )
        if filtered is not None:
            return filtered

        return await self._get_job_historical_stats_unfiltered(
            job_id=job_id, current_run_id=current_run_id
        )

    @staticmethod
    def _confidence_tier(filtered_runs: int) -> str:
        """Map filtered baseline size to a confidence label."""
        if filtered_runs >= 20:
            return 'high'
        if filtered_runs >= 10:
            return 'emerging'
        if filtered_runs >= 3:
            return 'limited'
        return 'none'

    @staticmethod
    def _is_permission_error(exc: Exception) -> bool:
        """Detect missing-grant errors so we can fall back gracefully."""
        msg = str(exc).lower()
        keywords = (
            'permission denied',
            'insufficient_permissions',
            'insufficient permissions',
            'table or view not found',
            'table_or_view_not_found',
            'does not have',
            'access denied',
        )
        return any(k in msg for k in keywords)

    @staticmethod
    def _build_comparison(
        current_cost: Optional[float],
        reference_cost: Optional[float],
        reference_label: str,
        current_state: Optional[str],
    ) -> Tuple[Optional[str], Optional[float]]:
        """Build comparison string + pct, only for SUCCEEDED current runs."""
        MIN_REFERENCE_THRESHOLD = 0.01
        # Only compare when the current run actually completed successfully.
        # Cancelled / failed / timed-out runs incur partial cost and aren't
        # apples-to-apples with the baseline.
        if current_state is not None and current_state != 'SUCCEEDED':
            return None, None
        if (
            current_cost is None
            or reference_cost is None
            or reference_cost <= MIN_REFERENCE_THRESHOLD
        ):
            return None, None

        pct = ((current_cost - reference_cost) / reference_cost) * 100
        if pct > 0:
            text = f'+{pct:.1f}% above {reference_label}'
        elif pct < 0:
            text = f'{pct:.1f}% below {reference_label}'
        else:
            text = f'at {reference_label}'
        return text, pct

    async def _get_job_historical_stats_filtered(
        self, job_id: str, current_run_id: str
    ) -> Optional[dict]:
        """Baseline filtered to SUCCEEDED runs via `system.lakeflow.job_run_timeline`.

        Returns None if the timeline grant is missing (caller falls back to
        the unfiltered legacy query) or on any other unexpected error.
        """
        try:
            escaped_job_id = job_id.replace("'", "''")
            escaped_run_id = current_run_id.replace("'", "''")
            lookback_date = (
                date.today() - timedelta(days=LOOKBACK_DAYS)
            ).isoformat()

            # Notes:
            # - system.lakeflow.job_run_timeline.run_id is BIGINT, but
            #   dbspend360_total_job_spends.run_id is STRING. Cast on the
            #   system side so the join works in either direction.
            # - A run can appear in multiple timeline rows (one per snapshot
            #   period). MAX_BY(result_state, period_end_time) collapses to
            #   the final state per run.
            query = f"""
            WITH run_outcomes AS (
                SELECT
                    CAST(run_id AS STRING) AS run_id,
                    MAX_BY(result_state, period_end_time) AS final_state
                FROM system.lakeflow.job_run_timeline
                WHERE CAST(job_id AS STRING) = '{escaped_job_id}'
                  AND period_start_time >= TIMESTAMP '{lookback_date} 00:00:00'
                GROUP BY run_id
            ),
            run_costs AS (
                SELECT
                    c.run_id,
                    SUM(c.cloud_cost) AS cloud_cost,
                    SUM(c.databricks_cost) AS databricks_cost,
                    SUM(c.cloud_cost) + SUM(c.databricks_cost) AS total_cost,
                    MIN(c.usage_date) AS first_date,
                    MAX(c.usage_date) AS last_date,
                    MAX(o.final_state) AS final_state
                FROM {self.table_name} c
                LEFT JOIN run_outcomes o ON c.run_id = o.run_id
                WHERE c.job_id = '{escaped_job_id}'
                  AND c.usage_date >= '{lookback_date}'
                GROUP BY c.run_id
            ),
            baseline AS (
                SELECT
                    COUNT(*) AS total_runs,
                    AVG(total_cost) AS avg_cost,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_cost) AS median_cost,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY total_cost) AS p90_cost,
                    MIN(total_cost) AS min_cost,
                    MAX(total_cost) AS max_cost,
                    STDDEV_POP(total_cost) AS stddev_cost,
                    AVG(
                        CASE WHEN total_cost > 0
                             THEN cloud_cost / total_cost * 100
                             ELSE 0
                        END
                    ) AS avg_cloud_pct,
                    MIN(first_date) AS data_start,
                    MAX(last_date) AS data_end
                FROM run_costs
                WHERE run_id != '{escaped_run_id}'
                  AND final_state = 'SUCCEEDED'
            ),
            baseline_unfiltered AS (
                SELECT COUNT(*) AS total_runs_unfiltered
                FROM run_costs
                WHERE run_id != '{escaped_run_id}'
            ),
            current_run AS (
                SELECT
                    total_cost AS current_cost,
                    cloud_cost AS current_cloud_cost,
                    databricks_cost AS current_databricks_cost,
                    final_state AS current_state
                FROM run_costs
                WHERE run_id = '{escaped_run_id}'
            ),
            last_run AS (
                SELECT total_cost AS last_run_cost
                FROM run_costs
                WHERE run_id != '{escaped_run_id}'
                  AND final_state = 'SUCCEEDED'
                ORDER BY last_date DESC, run_id DESC
                LIMIT 1
            )
            SELECT
                b.total_runs,
                b.avg_cost,
                b.median_cost,
                b.p90_cost,
                b.min_cost,
                b.max_cost,
                b.stddev_cost,
                b.avg_cloud_pct,
                b.data_start,
                b.data_end,
                c.current_cost,
                c.current_cloud_cost,
                c.current_databricks_cost,
                l.last_run_cost,
                bu.total_runs_unfiltered,
                c.current_state
            FROM baseline b
            LEFT JOIN current_run c ON 1=1
            LEFT JOIN last_run l ON 1=1
            LEFT JOIN baseline_unfiltered bu ON 1=1
            """

            try:
                response = self.client.statement_execution.execute_statement(
                    warehouse_id=self.warehouse_id,
                    statement=query,
                )
            except Exception as exc:
                if self._is_permission_error(exc):
                    logger.warning(
                        'Falling back to unfiltered historical stats for job %s '
                        '(system.lakeflow.job_run_timeline not accessible): %s',
                        job_id, str(exc),
                    )
                    return None
                raise

            # Statement may also fail server-side with status=FAILED.
            status = getattr(response, 'status', None)
            if status is not None and getattr(status, 'error', None) is not None:
                err_msg = getattr(status.error, 'message', '') or ''
                if self._is_permission_error(Exception(err_msg)):
                    logger.warning(
                        'Falling back to unfiltered historical stats for job %s '
                        '(system.lakeflow.job_run_timeline not accessible): %s',
                        job_id, err_msg,
                    )
                    return None

            if not response.result or not response.result.data_array:
                return {
                    'total_runs': 0,
                    'limited_history': True,
                    'confidence_tier': 'none',
                    'state_filter_applied': True,
                    'current_run_state': None,
                    'total_runs_unfiltered': 0,
                }

            row = response.result.data_array[0]
            total_runs = int(row[0]) if row[0] else 0
            avg_cost = float(row[1]) if row[1] is not None else 0.0
            current_cost = float(row[10]) if row[10] is not None else None
            total_runs_unfiltered = (
                int(row[14]) if row[14] is not None else 0
            )
            current_state = row[15] if row[15] is not None else None

            # Reference for comparison: prefer median (robust to outliers),
            # fall back to avg only when median is unavailable (n < 3).
            median_cost_raw = float(row[2]) if row[2] is not None else None
            p90_cost_raw = float(row[3]) if row[3] is not None else None
            stddev_cost_raw = float(row[6]) if row[6] is not None else None

            median_cost = median_cost_raw if total_runs >= 3 else None
            p90_cost = p90_cost_raw if total_runs >= 3 else None
            stddev_cost = stddev_cost_raw if total_runs >= 2 else None

            reference_cost = (
                median_cost if median_cost is not None else avg_cost
            )
            reference_label = (
                'median' if median_cost is not None else 'average'
            )
            comparison, comparison_pct = self._build_comparison(
                current_cost=current_cost,
                reference_cost=reference_cost if total_runs > 0 else None,
                reference_label=reference_label,
                current_state=current_state,
            )

            result: dict = {
                'total_runs': total_runs,
                'total_runs_unfiltered': total_runs_unfiltered,
                'limited_history': total_runs < 3,
                'confidence_tier': self._confidence_tier(total_runs),
                'state_filter_applied': True,
                'current_run_state': current_state,
                'current_cost': current_cost,
                'current_cloud_cost': (
                    float(row[11]) if row[11] is not None else None
                ),
                'current_databricks_cost': (
                    float(row[12]) if row[12] is not None else None
                ),
                'comparison': comparison,
                'comparison_pct': comparison_pct,
                'comparison_reference': (
                    reference_label if comparison is not None else None
                ),
            }

            if total_runs > 0:
                result.update({
                    'avg_cost': avg_cost,
                    'median_cost': median_cost,
                    'p90_cost': p90_cost,
                    'min_cost': float(row[4]) if row[4] is not None else 0.0,
                    'max_cost': float(row[5]) if row[5] is not None else 0.0,
                    'stddev_cost': stddev_cost,
                    'avg_cloud_pct': float(row[7]) if row[7] is not None else 0.0,
                    'data_start': row[8],
                    'data_end': row[9],
                    'last_run_cost': (
                        float(row[13]) if row[13] is not None else None
                    ),
                })

            return result

        except Exception as e:
            if self._is_permission_error(e):
                logger.warning(
                    'Falling back to unfiltered historical stats for job %s '
                    '(system.lakeflow.job_run_timeline not accessible): %s',
                    job_id, str(e),
                )
                return None
            logger.error(
                'Error fetching filtered historical stats for job %s: %s',
                job_id, str(e),
            )
            return None

    async def _get_job_historical_stats_unfiltered(
        self, job_id: str, current_run_id: str
    ) -> Optional[dict]:
        """Legacy unfiltered baseline (all runs regardless of result_state).

        Used as a fallback when `system.lakeflow.job_run_timeline` is not
        accessible. Stamps `state_filter_applied=False` so the LLM prompt
        can disclose that cancelled/failed runs may be polluting the trend.
        """
        try:
            escaped_job_id = job_id.replace("'", "''")
            escaped_run_id = current_run_id.replace("'", "''")
            lookback_date = (
                date.today() - timedelta(days=LOOKBACK_DAYS)
            ).isoformat()

            query = f"""
            WITH run_costs AS (
                SELECT
                    run_id,
                    SUM(cloud_cost) AS cloud_cost,
                    SUM(databricks_cost) AS databricks_cost,
                    SUM(cloud_cost) + SUM(databricks_cost) AS total_cost,
                    MIN(usage_date) AS first_date,
                    MAX(usage_date) AS last_date
                FROM {self.table_name}
                WHERE job_id = '{escaped_job_id}'
                AND usage_date >= '{lookback_date}'
                GROUP BY run_id
            ),
            baseline AS (
                SELECT
                    COUNT(*) AS total_runs,
                    AVG(total_cost) AS avg_cost,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_cost) AS median_cost,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY total_cost) AS p90_cost,
                    MIN(total_cost) AS min_cost,
                    MAX(total_cost) AS max_cost,
                    STDDEV_POP(total_cost) AS stddev_cost,
                    AVG(
                        CASE WHEN total_cost > 0
                             THEN cloud_cost / total_cost * 100
                             ELSE 0
                        END
                    ) AS avg_cloud_pct,
                    MIN(first_date) AS data_start,
                    MAX(last_date) AS data_end
                FROM run_costs
                WHERE run_id != '{escaped_run_id}'
            ),
            current_run AS (
                SELECT
                    total_cost AS current_cost,
                    cloud_cost AS current_cloud_cost,
                    databricks_cost AS current_databricks_cost
                FROM run_costs
                WHERE run_id = '{escaped_run_id}'
            ),
            last_run AS (
                SELECT total_cost AS last_run_cost
                FROM run_costs
                WHERE run_id != '{escaped_run_id}'
                ORDER BY last_date DESC, run_id DESC
                LIMIT 1
            )
            SELECT
                b.total_runs,
                b.avg_cost,
                b.median_cost,
                b.p90_cost,
                b.min_cost,
                b.max_cost,
                b.stddev_cost,
                b.avg_cloud_pct,
                b.data_start,
                b.data_end,
                c.current_cost,
                c.current_cloud_cost,
                c.current_databricks_cost,
                l.last_run_cost
            FROM baseline b
            LEFT JOIN current_run c ON 1=1
            LEFT JOIN last_run l ON 1=1
            """

            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query,
            )

            if not response.result or not response.result.data_array:
                return {
                    'total_runs': 0,
                    'limited_history': True,
                    'confidence_tier': 'none',
                    'state_filter_applied': False,
                    'current_run_state': None,
                    'total_runs_unfiltered': 0,
                }

            row = response.result.data_array[0]
            total_runs = int(row[0]) if row[0] else 0
            avg_cost = float(row[1]) if row[1] is not None else 0.0
            current_cost = float(row[10]) if row[10] is not None else None

            median_cost_raw = float(row[2]) if row[2] is not None else None
            p90_cost_raw = float(row[3]) if row[3] is not None else None
            stddev_cost_raw = float(row[6]) if row[6] is not None else None

            median_cost = median_cost_raw if total_runs >= 3 else None
            p90_cost = p90_cost_raw if total_runs >= 3 else None
            stddev_cost = stddev_cost_raw if total_runs >= 2 else None

            reference_cost = (
                median_cost if median_cost is not None else avg_cost
            )
            reference_label = (
                'median' if median_cost is not None else 'average'
            )
            # Without the timeline join we can't know current run's state,
            # so pass None and let _build_comparison treat it as comparable.
            comparison, comparison_pct = self._build_comparison(
                current_cost=current_cost,
                reference_cost=reference_cost if total_runs > 0 else None,
                reference_label=reference_label,
                current_state=None,
            )

            result: dict = {
                'total_runs': total_runs,
                'total_runs_unfiltered': total_runs,
                'limited_history': total_runs < 3,
                'confidence_tier': self._confidence_tier(total_runs),
                'state_filter_applied': False,
                'current_run_state': None,
                'current_cost': current_cost,
                'current_cloud_cost': (
                    float(row[11]) if row[11] is not None else None
                ),
                'current_databricks_cost': (
                    float(row[12]) if row[12] is not None else None
                ),
                'comparison': comparison,
                'comparison_pct': comparison_pct,
                'comparison_reference': (
                    reference_label if comparison is not None else None
                ),
            }

            if total_runs > 0:
                result.update({
                    'avg_cost': avg_cost,
                    'median_cost': median_cost,
                    'p90_cost': p90_cost,
                    'min_cost': float(row[4]) if row[4] is not None else 0.0,
                    'max_cost': float(row[5]) if row[5] is not None else 0.0,
                    'stddev_cost': stddev_cost,
                    'avg_cloud_pct': float(row[7]) if row[7] is not None else 0.0,
                    'data_start': row[8],
                    'data_end': row[9],
                    'last_run_cost': (
                        float(row[13]) if row[13] is not None else None
                    ),
                })

            return result

        except Exception as e:
            logger.error(
                'Error fetching unfiltered historical stats for job %s: %s',
                job_id, str(e),
            )
            return None

    async def get_cluster_cost_summary(
        self,
        cluster_id: str,
        cluster_kind: Optional[Literal['job', 'all_purpose']] = None,
    ) -> Optional[dict]:
        """Get aggregated cost summary for a cluster over the lookback window.

        When ``cluster_kind`` is omitted (``None``) the source is
        auto-detected via ``_detect_cluster_kind`` — a small SELECT
        against ``system.compute.clusters.cluster_source``. This is
        required for the Instance Pools drill-down (CP10 review #2):
        a pool can carry both job and all-purpose clusters, and
        defaulting to ``"job"`` routed the cost-summary half of the
        LLM analysis at the wrong rollup table for all-purpose
        clusters.

        For ``cluster_kind="job"`` groups by ``(job_id, run_id)`` against
        ``dbspend360_total_job_spends``. For ``cluster_kind="all_purpose"``
        groups by ``(user_id, usage_date)`` against
        ``dbspend360_total_all_purpose_spends`` — the natural grain
        for an interactive cluster, where there is no job/run concept. The
        returned dict keeps the same shape as the job path so downstream LLM
        prompt builders (`llm_service._build_cluster_user_message`) work
        without branching on cluster_kind, with this semantic remap:

        - ``distinct_job_count`` → 0 (all-purpose has no jobs)
        - ``total_run_count``    → distinct (user_id, usage_date) cluster-day
          count — i.e. number of "active days × users on the cluster" units
        - ``avg_cost_per_run``   → average cost per user-day on the cluster
        - ``distinct_user_count`` (extra key, all-purpose only) → distinct
          owners that incurred cost on this cluster in the window. Always 1
          under v1 owner attribution but kept for v2 forward compatibility
          (see plan §3.3).

        Returns:
            dict with cost breakdown, or None on failure.
        """
        if cluster_kind is None:
            cluster_kind = await self._detect_cluster_kind(cluster_id)
        if cluster_kind == 'all_purpose':
            return await self._get_cluster_cost_summary_all_purpose(cluster_id)
        return await self._get_cluster_cost_summary_job(cluster_id)

    async def _detect_cluster_kind(
        self, cluster_id: str
    ) -> Literal['job', 'all_purpose']:
        """Probe ``system.compute.clusters`` for ``cluster_source``.

        Returns ``"job"`` when ``cluster_source = 'JOB'`` (an ephemeral
        cluster spun up by the Jobs runtime), else ``"all_purpose"``
        (the ``UI`` / ``API`` interactive shapes already filtered to in
        the All-Purpose queries). Falls back to ``"job"`` on lookup
        failure so behavior matches the historical default rather than
        surprising a known caller — the caller can always pass an
        explicit ``cluster_kind`` to bypass detection.
        """
        escaped_cluster_id = cluster_id.replace("'", "''")
        query = (
            "SELECT cluster_source FROM system.compute.clusters "
            f"WHERE cluster_id = '{escaped_cluster_id}' LIMIT 1"
        )
        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query,
            )
            if (
                response.result
                and response.result.data_array
                and response.result.data_array[0]
                and response.result.data_array[0][0]
            ):
                source = str(response.result.data_array[0][0]).upper()
                return 'job' if source == 'JOB' else 'all_purpose'
        except Exception as exc:
            logger.warning(
                'cluster_kind auto-detect failed for %s: %s',
                cluster_id,
                str(exc),
            )
        return 'job'

    async def _get_cluster_cost_summary_job(
        self, cluster_id: str
    ) -> Optional[dict]:
        """Job-cluster path for `get_cluster_cost_summary` (the original)."""
        try:
            escaped_cluster_id = cluster_id.replace("'", "''")
            lookback_date = (
                date.today() - timedelta(days=LOOKBACK_DAYS)
            ).isoformat()

            query = f"""
            WITH filtered AS (
                SELECT *
                FROM {self.table_name}
                WHERE cluster_id = '{escaped_cluster_id}'
                AND cluster_id IS NOT NULL
                AND usage_date >= '{lookback_date}'
            ),
            run_level AS (
                SELECT
                    job_id,
                    run_id,
                    SUM(cloud_cost) AS cloud_cost,
                    SUM(databricks_cost) AS databricks_cost
                FROM filtered
                GROUP BY job_id, run_id
            ),
            agg AS (
                SELECT
                    COALESCE(SUM(cloud_cost), 0) AS total_cloud_cost,
                    COALESCE(SUM(databricks_cost), 0) AS total_databricks_cost,
                    COALESCE(SUM(cloud_cost + databricks_cost), 0) AS total_spend,
                    COUNT(DISTINCT job_id) AS distinct_job_count,
                    COUNT(*) AS total_run_count,
                    COALESCE(AVG(cloud_cost + databricks_cost), 0) AS avg_cost_per_run
                FROM run_level
            ),
            date_range AS (
                SELECT
                    MIN(usage_date) AS first_active_date,
                    MAX(usage_date) AS last_active_date
                FROM filtered
            )
            SELECT
                a.total_cloud_cost,
                a.total_databricks_cost,
                a.total_spend,
                a.distinct_job_count,
                a.total_run_count,
                a.avg_cost_per_run,
                d.first_active_date,
                d.last_active_date
            FROM agg a, date_range d
            """

            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query,
            )

            if not response.result or not response.result.data_array:
                return {
                    'total_spend': 0.0,
                    'total_cloud_cost': 0.0,
                    'total_databricks_cost': 0.0,
                    'cloud_pct': 0.0,
                    'databricks_pct': 0.0,
                    'distinct_job_count': 0,
                    'total_run_count': 0,
                    'avg_cost_per_run': 0.0,
                    'first_active_date': None,
                    'last_active_date': None,
                    'limited_history': True,
                }

            row = response.result.data_array[0]
            total_cloud_cost = float(row[0])
            total_databricks_cost = float(row[1])
            total_spend = float(row[2])
            cloud_pct = (
                (total_cloud_cost / total_spend * 100)
                if total_spend > 0 else 0.0
            )
            databricks_pct = (
                (total_databricks_cost / total_spend * 100)
                if total_spend > 0 else 0.0
            )

            total_run_count = int(row[4])
            return {
                'total_spend': total_spend,
                'total_cloud_cost': total_cloud_cost,
                'total_databricks_cost': total_databricks_cost,
                'cloud_pct': cloud_pct,
                'databricks_pct': databricks_pct,
                'distinct_job_count': int(row[3]),
                'total_run_count': total_run_count,
                'avg_cost_per_run': float(row[5]),
                'first_active_date': row[6],
                'last_active_date': row[7],
                'limited_history': total_run_count < 3,
            }

        except Exception as e:
            logger.error(
                'Error fetching cluster cost summary for %s: %s',
                cluster_id, str(e),
            )
            return None

    async def _get_cluster_cost_summary_all_purpose(
        self, cluster_id: str
    ) -> Optional[dict]:
        """All-purpose-cluster path for `get_cluster_cost_summary`.

        Grain is ``(user_id, usage_date)`` against
        ``dbspend360_total_all_purpose_spends``. Output dict shape mirrors
        the job path so the LLM prompt builder doesn't branch — see
        ``get_cluster_cost_summary`` docstring for the semantic remap.
        """
        try:
            escaped_cluster_id = cluster_id.replace("'", "''")
            lookback_date = (
                date.today() - timedelta(days=LOOKBACK_DAYS)
            ).isoformat()

            query = f"""
            WITH filtered AS (
                SELECT *
                FROM {self.all_purpose_table_name}
                WHERE cluster_id = '{escaped_cluster_id}'
                AND cluster_id IS NOT NULL
                AND usage_date >= '{lookback_date}'
            ),
            day_level AS (
                -- Grain mirrors run_level in the job path: one row per
                -- (user_id, usage_date) cluster-day. Under v1 owner
                -- attribution there's exactly one user per (cluster_id,
                -- usage_date), so this collapses to one row per active day;
                -- under v2 multi-user attribution it fans out.
                SELECT
                    user_id,
                    usage_date,
                    SUM(cloud_cost) AS cloud_cost,
                    SUM(databricks_cost) AS databricks_cost
                FROM filtered
                GROUP BY user_id, usage_date
            ),
            agg AS (
                SELECT
                    COALESCE(SUM(cloud_cost), 0) AS total_cloud_cost,
                    COALESCE(SUM(databricks_cost), 0) AS total_databricks_cost,
                    COALESCE(SUM(cloud_cost + databricks_cost), 0) AS total_spend,
                    COUNT(DISTINCT user_id) AS distinct_user_count,
                    COUNT(*) AS total_run_count,
                    COALESCE(AVG(cloud_cost + databricks_cost), 0) AS avg_cost_per_run
                FROM day_level
            ),
            date_range AS (
                SELECT
                    MIN(usage_date) AS first_active_date,
                    MAX(usage_date) AS last_active_date
                FROM filtered
            )
            SELECT
                a.total_cloud_cost,
                a.total_databricks_cost,
                a.total_spend,
                a.distinct_user_count,
                a.total_run_count,
                a.avg_cost_per_run,
                d.first_active_date,
                d.last_active_date
            FROM agg a, date_range d
            """

            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query,
            )

            if not response.result or not response.result.data_array:
                return {
                    'total_spend': 0.0,
                    'total_cloud_cost': 0.0,
                    'total_databricks_cost': 0.0,
                    'cloud_pct': 0.0,
                    'databricks_pct': 0.0,
                    'distinct_job_count': 0,
                    'distinct_user_count': 0,
                    'total_run_count': 0,
                    'avg_cost_per_run': 0.0,
                    'first_active_date': None,
                    'last_active_date': None,
                    'limited_history': True,
                }

            row = response.result.data_array[0]
            total_cloud_cost = float(row[0])
            total_databricks_cost = float(row[1])
            total_spend = float(row[2])
            cloud_pct = (
                (total_cloud_cost / total_spend * 100)
                if total_spend > 0 else 0.0
            )
            databricks_pct = (
                (total_databricks_cost / total_spend * 100)
                if total_spend > 0 else 0.0
            )

            distinct_user_count = int(row[3]) if row[3] is not None else 0
            total_run_count = int(row[4]) if row[4] is not None else 0
            return {
                'total_spend': total_spend,
                'total_cloud_cost': total_cloud_cost,
                'total_databricks_cost': total_databricks_cost,
                'cloud_pct': cloud_pct,
                'databricks_pct': databricks_pct,
                # No job concept on all-purpose clusters; kept at 0 so the
                # shared LLM prompt builder doesn't KeyError on the job path's
                # `distinct_job_count` access.
                'distinct_job_count': 0,
                'distinct_user_count': distinct_user_count,
                'total_run_count': total_run_count,
                'avg_cost_per_run': float(row[5]) if row[5] is not None else 0.0,
                'first_active_date': row[6],
                'last_active_date': row[7],
                'limited_history': total_run_count < 3,
            }

        except Exception as e:
            logger.error(
                'Error fetching all-purpose cluster cost summary for %s: %s',
                cluster_id, str(e),
            )
            return None

    async def get_other_cost_breakdown(
        self,
        start_date: date,
        end_date: date,
        cluster_id: Optional[str] = None,
        limit: int = 15,
    ) -> OtherCostBreakdownResponse:
        """Get breakdown of other_cost by service_name for the given date range."""
        schema_name = app_config.schema_name
        if not schema_name:
            return OtherCostBreakdownResponse(
                items=[], total_other_cost=0.0,
                start_date=start_date, end_date=end_date,
            )

        breakdown_table = f'{schema_name}.dbspend360_other_cost_breakdown'

        where_parts = [
            f"cost_incurred_date >= '{start_date.isoformat()}'",
            f"cost_incurred_date <= '{end_date.isoformat()}'",
        ]
        if cluster_id:
            escaped = cluster_id.replace("'", "''")
            where_parts.append(f"cluster_id = '{escaped}'")

        where_clause = ' AND '.join(where_parts)

        query = f"""
        WITH ranked AS (
            SELECT
                service_name,
                source_system,
                SUM(cost) AS total_cost,
                ROW_NUMBER() OVER (ORDER BY SUM(cost) DESC) AS rn
            FROM {breakdown_table}
            WHERE {where_clause}
            GROUP BY service_name, source_system
        ),
        top_n AS (
            SELECT service_name, source_system, total_cost
            FROM ranked WHERE rn <= {limit}
        ),
        others AS (
            SELECT 'Other Services' AS service_name,
                   'MIXED' AS source_system,
                   SUM(total_cost) AS total_cost
            FROM ranked WHERE rn > {limit}
        ),
        combined AS (
            SELECT * FROM top_n
            UNION ALL
            SELECT * FROM others WHERE total_cost > 0
        ),
        grand_total AS (
            SELECT COALESCE(SUM(total_cost), 0) AS grand_total FROM ranked
        )
        SELECT c.service_name, c.source_system, c.total_cost,
               g.grand_total
        FROM combined c CROSS JOIN grand_total g
        ORDER BY c.total_cost DESC
        """

        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query
            )

            items: List[OtherCostBreakdownItem] = []
            total_other_cost = 0.0

            if response.result and response.result.data_array:
                total_other_cost = float(response.result.data_array[0][3]) if response.result.data_array[0][3] else 0.0

                for row in response.result.data_array:
                    cost = float(row[2]) if row[2] else 0.0
                    pct = (cost / total_other_cost * 100) if total_other_cost > 0 else 0.0
                    items.append(OtherCostBreakdownItem(
                        service_name=row[0] or 'Unknown',
                        source_system=row[1] or 'Unknown',
                        cost=cost,
                        percentage=round(pct, 1),
                    ))

            return OtherCostBreakdownResponse(
                items=items,
                total_other_cost=total_other_cost,
                start_date=start_date,
                end_date=end_date,
            )

        except Exception as e:
            logger.error('Error fetching other cost breakdown: %s', str(e))
            return OtherCostBreakdownResponse(
                items=[], total_other_cost=0.0,
                start_date=start_date, end_date=end_date,
            )

    async def get_classification_coverage_trend(
        self,
        limit: int = 30,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> CoverageTrendResponse:
        """Get classification coverage trend from the audit log.

        Parses `classification_coverage=XX.X%` from the message column
        of successful cloud cost explorer runs. When `start_date`/`end_date`
        are provided the audit rows are filtered to that window so the trend
        tracks the dashboard's selected date range.
        """
        schema_name = app_config.schema_name
        if not schema_name:
            return CoverageTrendResponse(data=[])

        audit_table = f'{schema_name}.dbspend360_audit_log'

        date_filter = ''
        if start_date:
            date_filter += f"\n          AND end_date >= '{start_date.isoformat()}'"
        if end_date:
            date_filter += f"\n          AND end_date <= '{end_date.isoformat()}'"

        query = f"""
        SELECT
            end_date AS report_date,
            CAST(
                regexp_extract(message, 'classification_coverage=([0-9.]+)%', 1)
                AS DOUBLE
            ) AS coverage_pct
        FROM {audit_table}
        WHERE table_name = 'dbspend360_cloud_cost_explorer'
          AND status = 'SUCCESS'
          AND message LIKE '%classification_coverage=%'{date_filter}
        ORDER BY end_date DESC
        LIMIT {limit}
        """

        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query
            )

            data: List[CoverageTrendPoint] = []
            if response.result and response.result.data_array:
                for row in response.result.data_array:
                    if row[0] and row[1] is not None:
                        data.append(CoverageTrendPoint(
                            report_date=date.fromisoformat(row[0]),
                            coverage_pct=float(row[1]),
                        ))

            data.reverse()
            return CoverageTrendResponse(data=data)

        except Exception as e:
            logger.error('Error fetching coverage trend: %s', str(e))
            return CoverageTrendResponse(data=[])

    # ------------------------------------------------------------------
    # All-Purpose cluster queries
    #
    # Source table: `dbspend360_total_all_purpose_spends`, keyed
    # `(cluster_id, user_id, usage_date)`. Under v1 owner attribution every
    # `(cluster_id, usage_date)` resolves to exactly one `user_id` (the
    # cluster owner, see plan §3.2); the (user_id, ...) key shape is kept
    # for v2 multi-user attribution forward compatibility.
    # ------------------------------------------------------------------

    async def get_all_purpose_summary_metrics(
        self, start_date: date, end_date: date
    ) -> AllPurposeSummaryMetrics:
        """Get summary metrics for the All-Purpose tab KPI strip.

        Implements plan §5.3. Aggregates at the `(cluster_id, user_id,
        usage_date)` grain so `avg/max/min_cost_per_cluster_day` is
        interpretable as "what does a single user-day on a single cluster
        cost on average". Reports distinct cluster + distinct user counts
        (not job counts) since the all-purpose model is keyed by user, not
        job.
        """
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.all_purpose_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        cluster_day_level AS (
            SELECT
                cluster_id,
                user_id,
                usage_date,
                SUM(cloud_cost)      AS cloud_cost,
                SUM(databricks_cost) AS databricks_cost,
                SUM(compute_cost)    AS compute_cost,
                SUM(storage_cost)    AS storage_cost,
                SUM(network_cost)    AS network_cost,
                SUM(other_cost)      AS other_cost
            FROM filtered
            GROUP BY cluster_id, user_id, usage_date
        )
        SELECT
            (SELECT COUNT(DISTINCT cluster_id) FROM filtered) AS total_clusters,
            (SELECT COUNT(DISTINCT user_id)    FROM filtered) AS total_users,
            COALESCE(SUM(cloud_cost + databricks_cost), 0) AS total_spend,
            COALESCE(AVG(cloud_cost + databricks_cost), 0) AS avg_cost_per_cluster_day,
            COALESCE(MAX(cloud_cost + databricks_cost), 0) AS max_cost_per_cluster_day,
            COALESCE(MIN(cloud_cost + databricks_cost), 0) AS min_cost_per_cluster_day,
            COALESCE(SUM(cloud_cost), 0)      AS total_cloud_cost,
            COALESCE(SUM(databricks_cost), 0) AS total_databricks_cost,
            SUM(compute_cost) AS total_compute_cost,
            SUM(storage_cost) AS total_storage_cost,
            SUM(network_cost) AS total_network_cost,
            SUM(other_cost)   AS total_other_cost
        FROM cluster_day_level
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        date_range_days = (end_date - start_date).days + 1

        if response.result and response.result.data_array:
            row = response.result.data_array[0]
            return AllPurposeSummaryMetrics(
                total_clusters=int(row[0]) if row[0] is not None else 0,
                total_users=int(row[1]) if row[1] is not None else 0,
                total_spend=float(row[2]) if row[2] is not None else 0.0,
                avg_cost_per_cluster_day=float(row[3]) if row[3] is not None else 0.0,
                max_cost_per_cluster_day=float(row[4]) if row[4] is not None else 0.0,
                min_cost_per_cluster_day=float(row[5]) if row[5] is not None else 0.0,
                total_cloud_cost=float(row[6]) if row[6] is not None else 0.0,
                total_databricks_cost=float(row[7]) if row[7] is not None else 0.0,
                total_compute_cost=float(row[8]) if row[8] is not None else None,
                total_storage_cost=float(row[9]) if row[9] is not None else None,
                total_network_cost=float(row[10]) if row[10] is not None else None,
                total_other_cost=float(row[11]) if row[11] is not None else None,
                date_range_days=date_range_days,
            )

        return AllPurposeSummaryMetrics(
            total_clusters=0,
            total_users=0,
            total_spend=0.0,
            avg_cost_per_cluster_day=0.0,
            max_cost_per_cluster_day=0.0,
            min_cost_per_cluster_day=0.0,
            total_cloud_cost=0.0,
            total_databricks_cost=0.0,
            date_range_days=date_range_days,
        )

    async def get_all_purpose_grouped_by_cluster(
        self,
        start_date: date,
        end_date: date,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedAllPurposeClusters:
        """Paginated By-Cluster rollup for the All-Purpose tab.

        Implements plan §5.1. One row per cluster in the window, with the
        owner's `user_id` and `data_security_mode` denormalized for badge
        rendering. `users` is enriched via `_get_batch_cluster_days` with
        the per-day drill-down expansion (under v1: one user per day, the
        cluster owner).

        `search` is a free-text term matched against cluster_name,
        cluster_id, and owner_user_id (case-insensitive on cluster_name).
        """
        escaped_search = search.replace("'", "''") if search else None
        search_clause = ''
        if escaped_search:
            search_clause = (
                "WHERE ("
                f"c.cluster_id LIKE '%{escaped_search}%' "
                f"OR LOWER(COALESCE(cl.cluster_name, '')) LIKE LOWER('%{escaped_search}%') "
                f"OR LOWER(COALESCE(c.owner_user_id, '')) LIKE LOWER('%{escaped_search}%')"
                ")"
            )

        data_query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.all_purpose_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        cluster_level AS (
            SELECT
                cluster_id,
                ANY_VALUE(user_id)            AS owner_user_id,
                ANY_VALUE(data_security_mode) AS data_security_mode,
                COUNT(DISTINCT usage_date)    AS active_days,
                SUM(cloud_cost)               AS total_cloud_cost,
                SUM(databricks_cost)          AS total_databricks_cost,
                SUM(compute_cost)             AS total_compute_cost,
                SUM(storage_cost)             AS total_storage_cost,
                SUM(network_cost)             AS total_network_cost,
                SUM(other_cost)               AS total_other_cost
            FROM filtered
            GROUP BY cluster_id
        )
        SELECT
            c.cluster_id,
            c.owner_user_id,
            c.data_security_mode,
            c.active_days,
            c.total_cloud_cost,
            c.total_databricks_cost,
            c.total_compute_cost,
            c.total_storage_cost,
            c.total_network_cost,
            c.total_other_cost,
            cl.cluster_name,
            COUNT(*) OVER() AS total_matching
        FROM cluster_level c
        LEFT JOIN (
            -- system.compute.clusters can have multiple SCD snapshot rows
            -- per cluster_id; MAX_BY collapses to the most-recent name so a
            -- renamed cluster doesn't fan out into duplicate rows here.
            SELECT cluster_id,
                   MAX_BY(cluster_name, change_time) AS cluster_name
            FROM system.compute.clusters
            WHERE cluster_source IN ('UI', 'API')
            GROUP BY cluster_id
        ) cl ON c.cluster_id = cl.cluster_id
        {search_clause}
        ORDER BY (COALESCE(c.total_cloud_cost, 0) + COALESCE(c.total_databricks_cost, 0)) DESC
        LIMIT {limit} OFFSET {offset}
        """

        data_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=data_query,
        )

        total_count = 0
        if data_response.result and data_response.result.data_array:
            total_count = int(data_response.result.data_array[0][11])

        grouped: List[GroupedAllPurposeCluster] = []
        if data_response.result and data_response.result.data_array:
            cluster_ids = [row[0] for row in data_response.result.data_array]
            users_by_cluster = await self._get_batch_cluster_days(
                cluster_ids, start_date, end_date, days_per_cluster=30
            )

            for row in data_response.result.data_array:
                cluster_id = row[0]
                grouped.append(GroupedAllPurposeCluster(
                    cluster_id=cluster_id,
                    cluster_name=row[10],
                    owner_user_id=row[1] or '__unknown__',
                    data_security_mode=row[2],
                    active_days=int(row[3]) if row[3] is not None else 0,
                    # NULL = no cloud row matched this cluster (e.g. it ran on
                    # an instance pool, or Cost Explorer hasn't landed). Keep
                    # None so the UI renders "—" not a misleading "$0.00".
                    total_cloud_cost=float(row[4]) if row[4] is not None else None,
                    total_databricks_cost=float(row[5]) if row[5] is not None else 0.0,
                    total_compute_cost=float(row[6]) if row[6] is not None else None,
                    total_storage_cost=float(row[7]) if row[7] is not None else None,
                    total_network_cost=float(row[8]) if row[8] is not None else None,
                    total_other_cost=float(row[9]) if row[9] is not None else None,
                    users=users_by_cluster.get(cluster_id, []),
                ))

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        current_page = (offset // limit) + 1

        return PaginatedAllPurposeClusters(
            data=grouped,
            total_count=total_count,
            page=current_page,
            per_page=limit,
            total_pages=total_pages,
            has_next=current_page < total_pages,
            has_previous=current_page > 1,
        )

    async def get_all_purpose_grouped_by_user(
        self,
        start_date: date,
        end_date: date,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedAllPurposeUsers:
        """Paginated By-User rollup for the All-Purpose tab (chargeback view).

        Implements plan §5.2. The dedicated `user_active_days` CTE computes
        distinct active days from `filtered` directly — summing
        `COUNT(DISTINCT usage_date)` across the per-cluster CTE would
        double-count any day on which a user was active on multiple
        clusters. `clusters` is enriched via `_get_batch_user_clusters`
        with the per-cluster drill-down expansion.
        """
        escaped_search = search.replace("'", "''") if search else None
        search_clause = ''
        if escaped_search:
            search_clause = (
                f"WHERE LOWER(COALESCE(user_id, '')) LIKE LOWER('%{escaped_search}%')"
            )

        data_query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.all_purpose_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        user_cluster_level AS (
            SELECT
                user_id,
                cluster_id,
                SUM(cloud_cost)             AS cloud_cost,
                SUM(databricks_cost)        AS databricks_cost,
                SUM(compute_cost)           AS compute_cost,
                SUM(storage_cost)           AS storage_cost,
                SUM(network_cost)           AS network_cost,
                SUM(other_cost)             AS other_cost,
                COUNT(DISTINCT usage_date)  AS cluster_active_days
            FROM filtered
            GROUP BY user_id, cluster_id
        ),
        user_active_days AS (
            -- Computed from `filtered` directly so a user active on
            -- multiple clusters on the same day doesn't double-count
            -- (see plan §5.2).
            SELECT user_id, COUNT(DISTINCT usage_date) AS active_days
            FROM filtered
            GROUP BY user_id
        ),
        user_level AS (
            SELECT
                ucl.user_id,
                COUNT(DISTINCT ucl.cluster_id) AS cluster_count,
                uad.active_days                AS user_active_days,
                SUM(ucl.cloud_cost)            AS total_cloud_cost,
                SUM(ucl.databricks_cost)       AS total_databricks_cost,
                SUM(ucl.compute_cost)          AS total_compute_cost,
                SUM(ucl.storage_cost)          AS total_storage_cost,
                SUM(ucl.network_cost)          AS total_network_cost,
                SUM(ucl.other_cost)            AS total_other_cost
            FROM user_cluster_level ucl
            JOIN user_active_days uad USING (user_id)
            GROUP BY ucl.user_id, uad.active_days
        )
        SELECT
            user_id,
            cluster_count,
            user_active_days,
            total_cloud_cost,
            total_databricks_cost,
            total_compute_cost,
            total_storage_cost,
            total_network_cost,
            total_other_cost,
            COUNT(*) OVER() AS total_matching
        FROM user_level
        {search_clause}
        ORDER BY (COALESCE(total_cloud_cost, 0) + COALESCE(total_databricks_cost, 0)) DESC
        LIMIT {limit} OFFSET {offset}
        """

        data_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=data_query,
        )

        total_count = 0
        if data_response.result and data_response.result.data_array:
            total_count = int(data_response.result.data_array[0][9])

        grouped: List[GroupedAllPurposeUser] = []
        if data_response.result and data_response.result.data_array:
            user_ids = [row[0] for row in data_response.result.data_array]
            clusters_by_user = await self._get_batch_user_clusters(
                user_ids, start_date, end_date, clusters_per_user=20
            )

            for row in data_response.result.data_array:
                user_id = row[0] or '__unknown__'
                grouped.append(GroupedAllPurposeUser(
                    user_id=user_id,
                    cluster_count=int(row[1]) if row[1] is not None else 0,
                    user_active_days=int(row[2]) if row[2] is not None else 0,
                    # NULL = none of this user's clusters had a matching cloud
                    # row; keep None so the UI shows "—" not a false "$0.00".
                    total_cloud_cost=float(row[3]) if row[3] is not None else None,
                    total_databricks_cost=float(row[4]) if row[4] is not None else 0.0,
                    total_compute_cost=float(row[5]) if row[5] is not None else None,
                    total_storage_cost=float(row[6]) if row[6] is not None else None,
                    total_network_cost=float(row[7]) if row[7] is not None else None,
                    total_other_cost=float(row[8]) if row[8] is not None else None,
                    clusters=clusters_by_user.get(user_id, []),
                ))

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        current_page = (offset // limit) + 1

        return PaginatedAllPurposeUsers(
            data=grouped,
            total_count=total_count,
            page=current_page,
            per_page=limit,
            total_pages=total_pages,
            has_next=current_page < total_pages,
            has_previous=current_page > 1,
        )

    async def get_all_purpose_top_clusters(
        self, start_date: date, end_date: date, limit: int = 5
    ) -> List[GroupedAllPurposeCluster]:
        """Get top N most expensive all-purpose clusters in the window.

        Cluster-grain analogue of `get_top_jobs`. Returns flat
        `GroupedAllPurposeCluster` rows with `users=[]` — this endpoint
        powers a top-N card and intentionally skips the per-day enrichment
        query for cost reasons (mirrors `get_top_jobs` returning
        `runs=[]`; see the model docstring on `GroupedJob`).
        """
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.all_purpose_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        cluster_level AS (
            SELECT
                cluster_id,
                ANY_VALUE(user_id)            AS owner_user_id,
                ANY_VALUE(data_security_mode) AS data_security_mode,
                COUNT(DISTINCT usage_date)    AS active_days,
                SUM(cloud_cost)               AS total_cloud_cost,
                SUM(databricks_cost)          AS total_databricks_cost,
                SUM(compute_cost)             AS total_compute_cost,
                SUM(storage_cost)             AS total_storage_cost,
                SUM(network_cost)             AS total_network_cost,
                SUM(other_cost)               AS total_other_cost
            FROM filtered
            GROUP BY cluster_id
        )
        SELECT
            c.cluster_id,
            c.owner_user_id,
            c.data_security_mode,
            c.active_days,
            c.total_cloud_cost,
            c.total_databricks_cost,
            c.total_compute_cost,
            c.total_storage_cost,
            c.total_network_cost,
            c.total_other_cost,
            cl.cluster_name
        FROM cluster_level c
        LEFT JOIN (
            SELECT cluster_id,
                   MAX_BY(cluster_name, change_time) AS cluster_name
            FROM system.compute.clusters
            WHERE cluster_source IN ('UI', 'API')
            GROUP BY cluster_id
        ) cl ON c.cluster_id = cl.cluster_id
        ORDER BY (COALESCE(c.total_cloud_cost, 0) + COALESCE(c.total_databricks_cost, 0)) DESC
        LIMIT {limit}
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        clusters: List[GroupedAllPurposeCluster] = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                clusters.append(GroupedAllPurposeCluster(
                    cluster_id=row[0],
                    cluster_name=row[10],
                    owner_user_id=row[1] or '__unknown__',
                    data_security_mode=row[2],
                    active_days=int(row[3]) if row[3] is not None else 0,
                    # NULL cloud → None so the UI renders "—" not "$0.00".
                    total_cloud_cost=float(row[4]) if row[4] is not None else None,
                    total_databricks_cost=float(row[5]) if row[5] is not None else 0.0,
                    total_compute_cost=float(row[6]) if row[6] is not None else None,
                    total_storage_cost=float(row[7]) if row[7] is not None else None,
                    total_network_cost=float(row[8]) if row[8] is not None else None,
                    total_other_cost=float(row[9]) if row[9] is not None else None,
                    users=[],
                ))

        return clusters

    async def get_all_purpose_top_users(
        self, start_date: date, end_date: date, limit: int = 5
    ) -> List[GroupedAllPurposeUser]:
        """Get top N most expensive all-purpose users (chargeback view).

        User-grain analogue of `get_top_jobs`. Returns flat
        `GroupedAllPurposeUser` rows with `clusters=[]` — same per-row
        enrichment skip as `get_top_jobs`. `user_active_days` is computed
        from the raw rows directly (not summed across clusters) for the
        same correctness reason as `get_all_purpose_grouped_by_user`.
        """
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.all_purpose_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        user_cluster_level AS (
            SELECT
                user_id,
                cluster_id,
                SUM(cloud_cost)             AS cloud_cost,
                SUM(databricks_cost)        AS databricks_cost,
                SUM(compute_cost)           AS compute_cost,
                SUM(storage_cost)           AS storage_cost,
                SUM(network_cost)           AS network_cost,
                SUM(other_cost)             AS other_cost
            FROM filtered
            GROUP BY user_id, cluster_id
        ),
        user_active_days AS (
            SELECT user_id, COUNT(DISTINCT usage_date) AS active_days
            FROM filtered
            GROUP BY user_id
        ),
        user_level AS (
            SELECT
                ucl.user_id,
                COUNT(DISTINCT ucl.cluster_id) AS cluster_count,
                uad.active_days                AS user_active_days,
                SUM(ucl.cloud_cost)            AS total_cloud_cost,
                SUM(ucl.databricks_cost)       AS total_databricks_cost,
                SUM(ucl.compute_cost)          AS total_compute_cost,
                SUM(ucl.storage_cost)          AS total_storage_cost,
                SUM(ucl.network_cost)          AS total_network_cost,
                SUM(ucl.other_cost)            AS total_other_cost
            FROM user_cluster_level ucl
            JOIN user_active_days uad USING (user_id)
            GROUP BY ucl.user_id, uad.active_days
        )
        SELECT
            user_id,
            cluster_count,
            user_active_days,
            total_cloud_cost,
            total_databricks_cost,
            total_compute_cost,
            total_storage_cost,
            total_network_cost,
            total_other_cost
        FROM user_level
        ORDER BY (COALESCE(total_cloud_cost, 0) + COALESCE(total_databricks_cost, 0)) DESC
        LIMIT {limit}
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        users: List[GroupedAllPurposeUser] = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                users.append(GroupedAllPurposeUser(
                    user_id=row[0] or '__unknown__',
                    cluster_count=int(row[1]) if row[1] is not None else 0,
                    user_active_days=int(row[2]) if row[2] is not None else 0,
                    # NULL cloud → None so the UI renders "—" not "$0.00".
                    total_cloud_cost=float(row[3]) if row[3] is not None else None,
                    total_databricks_cost=float(row[4]) if row[4] is not None else 0.0,
                    total_compute_cost=float(row[5]) if row[5] is not None else None,
                    total_storage_cost=float(row[6]) if row[6] is not None else None,
                    total_network_cost=float(row[7]) if row[7] is not None else None,
                    total_other_cost=float(row[8]) if row[8] is not None else None,
                    clusters=[],
                ))

        return users

    async def _get_batch_cluster_days(
        self,
        cluster_ids: List[str],
        start_date: date,
        end_date: date,
        days_per_cluster: int = 30,
    ) -> Dict[str, List[AllPurposeUserSpend]]:
        """Fetch the top-N per-day rows for a batch of all-purpose clusters.

        Parallel to `_get_batch_job_runs`: takes the page's `cluster_id`s
        and returns up to `days_per_cluster` rows per cluster, ordered by
        most-recent first then by cost. Each row is grain
        `(cluster_id, user_id, usage_date)`; under v1 owner attribution
        this is one row per active day.
        """
        if not cluster_ids:
            return {}

        escaped_ids = [cid.replace("'", "''") for cid in cluster_ids]
        in_clause = ', '.join(f"'{cid}'" for cid in escaped_ids)

        query = f"""
        WITH ranked_days AS (
            SELECT
                cluster_id,
                user_id,
                usage_date,
                SUM(cloud_cost)      AS cloud_cost,
                SUM(databricks_cost) AS databricks_cost,
                SUM(compute_cost)    AS compute_cost,
                SUM(storage_cost)    AS storage_cost,
                SUM(network_cost)    AS network_cost,
                SUM(other_cost)      AS other_cost,
                ROW_NUMBER() OVER (
                    PARTITION BY cluster_id
                    ORDER BY usage_date DESC,
                             (COALESCE(SUM(cloud_cost), 0) + COALESCE(SUM(databricks_cost), 0)) DESC
                ) AS rn
            FROM {self.all_purpose_table_name}
            WHERE cluster_id IN ({in_clause})
              AND usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
            GROUP BY cluster_id, user_id, usage_date
        )
        SELECT
            cluster_id, user_id, usage_date,
            cloud_cost, databricks_cost,
            compute_cost, storage_cost, network_cost, other_cost
        FROM ranked_days
        WHERE rn <= {days_per_cluster}
        ORDER BY cluster_id, usage_date DESC
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        result: Dict[str, List[AllPurposeUserSpend]] = {}
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                cluster_id = row[0]
                spend = AllPurposeUserSpend(
                    cluster_id=cluster_id,
                    user_id=row[1] or '__unknown__',
                    usage_date=date.fromisoformat(row[2]),
                    # NULL cloud → None so the per-day cell renders "—" not "$0.00".
                    cloud_cost=float(row[3]) if row[3] is not None else None,
                    databricks_cost=float(row[4]) if row[4] is not None else 0.0,
                    compute_cost=float(row[5]) if row[5] is not None else None,
                    storage_cost=float(row[6]) if row[6] is not None else None,
                    network_cost=float(row[7]) if row[7] is not None else None,
                    other_cost=float(row[8]) if row[8] is not None else None,
                )
                result.setdefault(cluster_id, []).append(spend)

        return result

    async def _get_batch_user_clusters(
        self,
        user_ids: List[str],
        start_date: date,
        end_date: date,
        clusters_per_user: int = 20,
    ) -> Dict[str, List[AllPurposeClusterSpend]]:
        """Fetch the top-N per-cluster rows for a batch of users.

        Parallel to `_get_batch_cluster_days` but expanded to the per-cluster
        grain for the By-User sub-tab. Joins back to
        `system.compute.clusters` (collapsed via `MAX_BY`) for the cluster
        name. `cluster_active_days` is `COUNT(DISTINCT usage_date)` for
        each `(user_id, cluster_id)` pair. `data_security_mode` is taken
        from the all-purpose table (which carries the SCD-collapsed value
        from the upstream pipeline).
        """
        if not user_ids:
            return {}

        escaped_ids = [uid.replace("'", "''") for uid in user_ids]
        in_clause = ', '.join(f"'{uid}'" for uid in escaped_ids)

        query = f"""
        WITH per_user_cluster AS (
            SELECT
                user_id,
                cluster_id,
                ANY_VALUE(data_security_mode) AS data_security_mode,
                SUM(cloud_cost)               AS cloud_cost,
                SUM(databricks_cost)          AS databricks_cost,
                SUM(compute_cost)             AS compute_cost,
                SUM(storage_cost)             AS storage_cost,
                SUM(network_cost)             AS network_cost,
                SUM(other_cost)               AS other_cost,
                COUNT(DISTINCT usage_date)    AS cluster_active_days
            FROM {self.all_purpose_table_name}
            WHERE user_id IN ({in_clause})
              AND usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
            GROUP BY user_id, cluster_id
        ),
        ranked AS (
            SELECT
                puc.*,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY (COALESCE(cloud_cost, 0) + COALESCE(databricks_cost, 0)) DESC, cluster_id
                ) AS rn
            FROM per_user_cluster puc
        )
        SELECT
            r.user_id,
            r.cluster_id,
            cl.cluster_name,
            r.data_security_mode,
            r.cluster_active_days,
            r.cloud_cost,
            r.databricks_cost,
            r.compute_cost,
            r.storage_cost,
            r.network_cost,
            r.other_cost
        FROM ranked r
        LEFT JOIN (
            SELECT cluster_id,
                   MAX_BY(cluster_name, change_time) AS cluster_name
            FROM system.compute.clusters
            WHERE cluster_source IN ('UI', 'API')
            GROUP BY cluster_id
        ) cl ON r.cluster_id = cl.cluster_id
        WHERE r.rn <= {clusters_per_user}
        ORDER BY r.user_id, (COALESCE(r.cloud_cost, 0) + COALESCE(r.databricks_cost, 0)) DESC
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        result: Dict[str, List[AllPurposeClusterSpend]] = {}
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                user_id = row[0] or '__unknown__'
                spend = AllPurposeClusterSpend(
                    cluster_id=row[1],
                    cluster_name=row[2],
                    user_id=user_id,
                    data_security_mode=row[3],
                    cluster_active_days=int(row[4]) if row[4] is not None else 0,
                    # NULL cloud → None so the per-cluster cell renders "—" not "$0.00".
                    cloud_cost=float(row[5]) if row[5] is not None else None,
                    databricks_cost=float(row[6]) if row[6] is not None else 0.0,
                    compute_cost=float(row[7]) if row[7] is not None else None,
                    storage_cost=float(row[8]) if row[8] is not None else None,
                    network_cost=float(row[9]) if row[9] is not None else None,
                    other_cost=float(row[10]) if row[10] is not None else None,
                )
                result.setdefault(user_id, []).append(spend)

        return result

    # ------------------------------------------------------------------
    # Instance Pool queries
    #
    # Source table: `dbspend360_total_pool_spends`, keyed
    # `(instance_pool_id, cluster_id, usage_date)`. Two-level drill-down
    # (plan §3.3, §5.2): the pool list endpoint enriches each row with the
    # nested `days[].clusters[]` shape via a single finest-grain batch
    # query rolled up in Python — `_get_batch_pool_days_and_clusters` —
    # so the §9 "per-day total equals per-cluster sum" invariant is
    # structural rather than asserted across two warehouse round-trips.
    #
    # As of CP7 (plan §4.4/§4.6) the EC2/EBS `cloud_cost` is joined in from
    # `dbspend360_pool_cloud_cost_explorer`: pool VM cost lands on the
    # synthesized `__pool_overhead__` row (it is pool-level, not per attached
    # cluster), so `SUM(cloud_cost)` over a pool-day is the real billed EC2
    # for that pool. Service-layer methods preserve `NULL` for "unknown"
    # (no pool-tag cloud row yet) and surface `0.0` only for genuine zero
    # (plan §5 / decision #3) — per-cluster drill-down rows stay `None`
    # because pool VM cost is not attributable to a specific attached
    # cluster (AWS tags pool instances `DatabricksInstancePoolId`, not
    # `ClusterId`).
    #
    # Creator info is not denormalized on the rollup table (plan §3.4 /
    # §4.1 — `system.compute.instance_pools.tags` excludes default tags so
    # the auto-applied `DatabricksInstancePoolCreatorId` is not visible
    # from the system table). It is resolved per-request in the pool
    # details modal via `get_pool_metadata` → `client.instance_pools.get`
    # → `default_tags['DatabricksInstancePoolCreatorId']`.
    # ------------------------------------------------------------------

    async def get_pool_metadata(
        self, pool_id: str
    ) -> Tuple[str, Optional[str]]:
        """Resolve pool display name + creator GUID via the Instance Pools REST API.

        Mirrors `get_job_name`'s caching shape but returns a `(pool_name,
        pool_creator_id)` tuple. The creator GUID is the value of
        `default_tags['DatabricksInstancePoolCreatorId']` on the SDK's
        `GetInstancePool` response — the only place that tag is visible
        (the system table's `tags` column excludes default tags per
        plan §10).

        Failure tuples `(f"Pool {pool_id}", None)` are cached as well so
        a flaky or nonexistent pool ID does not re-issue the REST API on
        every render. The SDK call itself is synchronous; this method
        follows `get_job_name`'s `async def` / sync-body pattern so callers
        can `await` it uniformly.

        v1 stops at the GUID; GUID -> email resolution is a v2 follow-up
        (plan §13) that adds a second `client.users.get(<guid>)` hop.
        """
        if pool_id in self.pool_metadata_cache:
            return self.pool_metadata_cache[pool_id]

        try:
            pool_info = self.client.instance_pools.get(instance_pool_id=pool_id)
            pool_name = pool_info.instance_pool_name or f'Pool {pool_id}'
            default_tags = pool_info.default_tags or {}
            creator_id = default_tags.get('DatabricksInstancePoolCreatorId')
            metadata = (pool_name, creator_id)
        except Exception as exc:
            logger.warning(
                'Failed to resolve pool metadata for %s via REST API: %s',
                pool_id,
                str(exc),
            )
            metadata = (f'Pool {pool_id}', None)

        self.pool_metadata_cache[pool_id] = metadata
        return metadata

    async def get_instance_pool_summary_metrics(
        self, start_date: date, end_date: date
    ) -> InstancePoolSummaryMetrics:
        """Get summary metrics for the Instance Pools tab KPI strip.

        Implements plan §5.3. Aggregates at the `(instance_pool_id,
        usage_date)` grain so `avg/max/min_cost_per_pool_day` reads as
        "what does a single day on a single pool cost on average".
        `orphaned_pools` counts distinct pools with
        `pool_snapshot_missing = TRUE` — surfaced as a KPI so operators
        can spot lost-metadata churn at a glance (plan §10 risk row).

        As of CP7 `total_cloud_cost` is the summed pool EC2/EBS cost over
        the window (plan §4.4/§4.6); it stays `None` only when no pool-day
        in the window carries a cloud row yet (`SUM(cloud_cost)` over an
        all-`NULL` slice is `NULL`), so the KPI is hidden rather than
        showing a misleading `$0` (plan §5 / decision #3).
        """
        # `pool_snapshot_state` aggregates pool_snapshot_missing to one
        # row per pool via BOOL_AND so the orphan KPI counts only pools
        # where EVERY row in the window is snapshot-missing. The earlier
        # shape (`COUNT(DISTINCT instance_pool_id) ... WHERE
        # pool_snapshot_missing = TRUE`) over-counted whenever CP3
        # wrote heterogeneous rows for one pool — see the parallel fix
        # in `get_instance_pools_grouped` for the underlying mechanism
        # and the §13 follow-up that moves snapshot-state to a live
        # read against system.compute.instance_pools.
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.pool_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        pool_day_level AS (
            SELECT
                instance_pool_id,
                usage_date,
                SUM(databricks_cost) AS databricks_cost,
                SUM(cloud_cost)      AS cloud_cost,
                SUM(total_cost)      AS total_cost
            FROM filtered
            GROUP BY instance_pool_id, usage_date
        ),
        pool_snapshot_state AS (
            SELECT instance_pool_id,
                   BOOL_AND(pool_snapshot_missing) AS pool_uniformly_orphaned
            FROM filtered
            GROUP BY instance_pool_id
        )
        SELECT
            (SELECT COUNT(DISTINCT instance_pool_id) FROM filtered)            AS total_pools,
            -- Exclude the `__pool_overhead__` sentinel so the KPI counts only
            -- real attached clusters (see get_instance_pools_grouped). NOTE the
            -- global count still won't equal the sum of per-pool cluster_counts:
            -- the sentinel is one literal string, so it collapses to a single
            -- DISTINCT value globally but is excluded per-pool independently.
            (SELECT COUNT(DISTINCT CASE WHEN cluster_id <> '__pool_overhead__'
                                        THEN cluster_id END)
             FROM filtered)                                                    AS total_clusters,
            (SELECT COUNT(*) FROM pool_snapshot_state
                WHERE pool_uniformly_orphaned)                                 AS orphaned_pools,
            COALESCE(SUM(total_cost), 0)       AS total_spend,
            COALESCE(AVG(total_cost), 0)       AS avg_cost_per_pool_day,
            COALESCE(MAX(total_cost), 0)       AS max_cost_per_pool_day,
            COALESCE(MIN(total_cost), 0)       AS min_cost_per_pool_day,
            COALESCE(SUM(databricks_cost), 0)  AS total_databricks_cost,
            SUM(cloud_cost)                    AS total_cloud_cost
        FROM pool_day_level
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        date_range_days = (end_date - start_date).days + 1

        if response.result and response.result.data_array:
            row = response.result.data_array[0]
            return InstancePoolSummaryMetrics(
                total_pools=int(row[0]) if row[0] is not None else 0,
                total_clusters=int(row[1]) if row[1] is not None else 0,
                orphaned_pools=int(row[2]) if row[2] is not None else 0,
                total_spend=float(row[3]) if row[3] is not None else 0.0,
                avg_cost_per_pool_day=float(row[4]) if row[4] is not None else 0.0,
                max_cost_per_pool_day=float(row[5]) if row[5] is not None else 0.0,
                min_cost_per_pool_day=float(row[6]) if row[6] is not None else 0.0,
                total_databricks_cost=float(row[7]) if row[7] is not None else 0.0,
                total_cloud_cost=float(row[8]) if row[8] is not None else None,
                date_range_days=date_range_days,
            )

        return InstancePoolSummaryMetrics(
            total_pools=0,
            total_clusters=0,
            orphaned_pools=0,
            total_spend=0.0,
            avg_cost_per_pool_day=0.0,
            max_cost_per_pool_day=0.0,
            min_cost_per_pool_day=0.0,
            total_databricks_cost=0.0,
            total_cloud_cost=None,
            date_range_days=date_range_days,
        )

    async def get_instance_pools_grouped(
        self,
        start_date: date,
        end_date: date,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedInstancePools:
        """Paginated By-Pool rollup for the Instance Pools tab.

        Implements plan §5.1. One row per pool in the window. Pool
        metadata is already denormalized on the rollup table by
        `pool_spends_app.ipynb`, so no live join to
        `system.compute.instance_pools` is needed at query time.

        `search` matches case-insensitively against `pool_name` and
        exactly against `instance_pool_id`; per plan §5.1, the cluster_id
        branch uses a subquery back into `filtered` because `cluster_id`
        is not projected through `pool_level` (it has been aggregated into
        `COUNT(DISTINCT cluster_id)`), and predicating on it directly
        would fail with "column not found".

        `days` (per-day + per-cluster expansion) is enriched via
        `_get_batch_pool_days_and_clusters` — a single finest-grain
        statement rolled up in Python so the §9 per-day-total invariant
        is structural rather than asserted (plan §5.2). The list
        endpoint deliberately does **not** call the Instance Pools REST
        API (creator enrichment lives in the modal path only — plan §4.1
        regression-guarded by CP10).
        """
        escaped_search = search.replace("'", "''") if search else None
        search_clause = ''
        if escaped_search:
            search_clause = (
                "WHERE ("
                f"LOWER(COALESCE(pool_name, '')) LIKE LOWER('%{escaped_search}%') "
                f"OR instance_pool_id = '{escaped_search}' "
                f"OR instance_pool_id IN ("
                f"    SELECT DISTINCT instance_pool_id"
                f"    FROM filtered"
                f"    WHERE cluster_id = '{escaped_search}'"
                f"))"
            )

        # The pool_meta_ranked / pool_agg split below replaces the earlier
        # single-CTE `ANY_VALUE(...)` rollup. ANY_VALUE is per-column
        # non-deterministic and produced the "Snapshot missing badge on a
        # pool that clearly has a real name + node_type" artifact called
        # out in the CP10 review: when the underlying rollup carries
        # heterogeneous rows for one pool (some pool_snapshot_missing=TRUE
        # with NULL metadata, some FALSE with real metadata — typically
        # from CP3's first-touch lag on system.compute.instance_pools or
        # from older rows that fell outside CP3's `overlap_days` refresh
        # window), the engine could pick `pool_name` from a "good" row
        # while picking `pool_snapshot_missing` from a "bad" row.
        #
        # Two-CTE shape:
        #   * pool_meta_ranked picks ONE representative row per pool to
        #     source name + node_type + config from. ORDER BY
        #     pool_snapshot_missing ASC, usage_date DESC prefers a row
        #     where the snapshot was present, breaking ties by recency.
        #   * pool_agg computes the cost/cluster aggregates and uses
        #     BOOL_AND for the snapshot flag — a pool is reported as
        #     "snapshot missing" only when EVERY row in the window says
        #     so, matching the §3.5 badge intent.
        #
        # Plan §13 follow-up: replace the denormalized columns entirely
        # with a live join to a freshly-SCD-collapsed
        # system.compute.instance_pools (the shape /details already uses)
        # so staleness can't accrue in the rollup at all.
        data_query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.pool_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        pool_meta_ranked AS (
            SELECT
                instance_pool_id,
                pool_name,
                node_type,
                min_idle_instances,
                max_capacity,
                idle_instance_autotermination_minutes,
                pool_deleted_at,
                ROW_NUMBER() OVER (
                    PARTITION BY instance_pool_id
                    ORDER BY pool_snapshot_missing ASC, usage_date DESC
                ) AS rn
            FROM filtered
        ),
        pool_meta AS (
            SELECT instance_pool_id, pool_name, node_type,
                   min_idle_instances, max_capacity,
                   idle_instance_autotermination_minutes, pool_deleted_at
            FROM pool_meta_ranked
            WHERE rn = 1
        ),
        pool_agg AS (
            SELECT
                instance_pool_id,
                BOOL_AND(pool_snapshot_missing)                   AS pool_snapshot_missing,
                -- Exclude the synthetic `__pool_overhead__` sentinel: it is a
                -- pool-level bookkeeping row (idle/warm capacity + NULL-cluster
                -- DBU, plan §3.3/§4.4), not a real attached cluster, so counting
                -- it would over-report "Clusters" by one on every pool that has
                -- an overhead row (and mislabel idle-only pools as "1 cluster").
                COUNT(DISTINCT CASE WHEN cluster_id <> '__pool_overhead__'
                                    THEN cluster_id END)          AS cluster_count,
                COUNT(DISTINCT usage_date)                        AS active_days,
                SUM(databricks_cost)                              AS total_databricks_cost,
                SUM(cloud_cost)                                   AS total_cloud_cost,
                SUM(total_cost)                                   AS total_cost
            FROM filtered
            GROUP BY instance_pool_id
        ),
        pool_level AS (
            SELECT
                a.instance_pool_id,
                m.pool_name,
                m.node_type,
                m.min_idle_instances,
                m.max_capacity,
                m.idle_instance_autotermination_minutes,
                a.pool_snapshot_missing,
                m.pool_deleted_at,
                a.cluster_count,
                a.active_days,
                a.total_databricks_cost,
                a.total_cloud_cost,
                a.total_cost
            FROM pool_agg a
            JOIN pool_meta m USING (instance_pool_id)
        )
        SELECT
            instance_pool_id, pool_name, node_type,
            min_idle_instances, max_capacity,
            idle_instance_autotermination_minutes,
            pool_snapshot_missing, pool_deleted_at,
            cluster_count, active_days,
            total_databricks_cost, total_cloud_cost, total_cost,
            COUNT(*) OVER() AS total_matching
        FROM pool_level
        {search_clause}
        ORDER BY total_cost DESC
        LIMIT {limit} OFFSET {offset}
        """

        data_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=data_query,
        )

        total_count = 0
        if data_response.result and data_response.result.data_array:
            total_count = int(data_response.result.data_array[0][13])

        grouped: List[GroupedInstancePool] = []
        if data_response.result and data_response.result.data_array:
            pool_ids = [row[0] for row in data_response.result.data_array]
            days_by_pool = await self._get_batch_pool_days_and_clusters(
                pool_ids, start_date, end_date
            )

            for row in data_response.result.data_array:
                pool_id = row[0]
                grouped.append(GroupedInstancePool(
                    instance_pool_id=pool_id,
                    pool_name=row[1],
                    node_type=row[2],
                    min_idle_instances=int(row[3]) if row[3] is not None else None,
                    max_capacity=int(row[4]) if row[4] is not None else None,
                    idle_instance_autotermination_minutes=int(row[5]) if row[5] is not None else None,
                    pool_snapshot_missing=self._parse_bool(row[6]) or False,
                    pool_deleted_at=self._parse_timestamp(row[7]),
                    cluster_count=int(row[8]) if row[8] is not None else 0,
                    active_days=int(row[9]) if row[9] is not None else 0,
                    total_databricks_cost=float(row[10]) if row[10] is not None else 0.0,
                    total_cloud_cost=float(row[11]) if row[11] is not None else None,
                    total_cost=float(row[12]) if row[12] is not None else 0.0,
                    days=days_by_pool.get(pool_id, []),
                ))

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        current_page = (offset // limit) + 1

        return PaginatedInstancePools(
            data=grouped,
            total_count=total_count,
            page=current_page,
            per_page=limit,
            total_pages=total_pages,
            has_next=current_page < total_pages,
            has_previous=current_page > 1,
        )

    async def _get_batch_pool_days_and_clusters(
        self,
        pool_ids: List[str],
        start_date: date,
        end_date: date,
    ) -> Dict[str, List[InstancePoolDailySpend]]:
        """Fetch the per-day + per-cluster expansion for a batch of pools.

        Implements plan §5.2. A single `execute_statement` returns rows at
        the finest natural grain `(instance_pool_id, usage_date,
        cluster_id)` — the Statement Execution API only accepts one
        statement per request, so the "two result sets in one round-trip"
        framing in earlier draft notes was structurally wrong. The
        service-layer rollup folds the rows into the nested
        `GroupedInstancePool.days[].clusters[]` shape; the per-day
        `total_cost` is summed from the same cluster rows the
        per-cluster array exposes so the §9 invariant is structural.

        Pool EC2/EBS `cloud_cost` (CP7, plan §4.4) is surfaced at the
        per-day level only: it sits on the synthesized `__pool_overhead__`
        row in the rollup, so summing it across the day's cluster rows
        yields the real pool-day EC2 while every per-cluster sub-row keeps
        `cloud_cost = None` (rendered "—"). `NULL` is preserved when no
        cloud row exists for the day (plan §5 / decision #3).

        Per-cluster rows arrive sorted DESC by `total_cost` (per the
        ORDER BY below), so the CP10 UI can `slice(0, 25)` + roll the
        long tail without resorting.

        Sizing note (plan §5.2): on workspaces that share pools as
        job-cluster substrate, a single shared pool can attach hundreds
        of distinct clusters per day. A 50-pool / 30-day page that
        includes such a pool can land in the 20–40k row region, still
        well under the 25 MiB INLINE payload limit. Revisit if a 30-day
        page warm-fetches > 50k rows in practice.
        """
        if not pool_ids:
            return {}

        escaped_ids = [pid.replace("'", "''") for pid in pool_ids]
        in_clause = ', '.join(f"'{pid}'" for pid in escaped_ids)

        query = f"""
        SELECT
            instance_pool_id,
            usage_date,
            cluster_id,
            SUM(databricks_cost)        AS databricks_cost,
            SUM(cloud_cost)             AS cloud_cost,
            SUM(total_cost)             AS total_cost
        FROM {self.pool_table_name}
        WHERE instance_pool_id IN ({in_clause})
          AND usage_date >= '{start_date.isoformat()}'
          AND usage_date <= '{end_date.isoformat()}'
        GROUP BY instance_pool_id, usage_date, cluster_id
        ORDER BY instance_pool_id, usage_date, total_cost DESC
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        # Two-level dict so we can attach per-cluster rows to the right
        # `(pool, day)` bucket as we stream the result set. The Python
        # rollup mirrors plan §5.2's sketch.
        days_by_pool: Dict[str, Dict[date, InstancePoolDailySpend]] = {}
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                pool_id = row[0]
                usage_date = date.fromisoformat(row[1])
                cluster_id = row[2]
                dbx = float(row[3]) if row[3] is not None else 0.0
                # `cloud` is NULL on per-cluster rows and carries the real
                # pool EC2 only on the synthesized `__pool_overhead__` row
                # (plan §4.4). It is accumulated to the day level so the
                # drill-down surfaces EC2 at the (pool, day) level; real
                # per-cluster rows keep `cloud_cost = None` (rendered "—")
                # because pool VM cost is not attributable to a specific
                # attached cluster. The overhead row DOES keep its `cloud`
                # value (see below) so its `total_cost = DBU + cloud` is
                # self-consistent instead of showing a Total with no visible
                # components (issue #3).
                cloud = float(row[4]) if row[4] is not None else None
                is_overhead = cluster_id == '__pool_overhead__'
                total = float(row[5]) if row[5] is not None else 0.0

                pool_days = days_by_pool.setdefault(pool_id, {})
                day = pool_days.get(usage_date)
                if day is None:
                    day = InstancePoolDailySpend(
                        usage_date=usage_date,
                        cluster_count_on_day=0,
                        databricks_cost=0.0,
                        cloud_cost=None,
                        total_cost=0.0,
                        clusters=[],
                    )
                    pool_days[usage_date] = day

                day.databricks_cost += dbx
                if cloud is not None:
                    day.cloud_cost = (day.cloud_cost or 0.0) + cloud
                day.total_cost += total
                day.clusters.append(InstancePoolClusterSpend(
                    cluster_id=cluster_id,
                    databricks_cost=dbx,
                    # Only the `__pool_overhead__` row carries the pool EC2
                    # `cloud` — surfacing it here makes its `total_cost`
                    # break down visibly (DBU + cloud). Real cluster rows
                    # stay `None` ("—"): pool VM cost isn't per-cluster.
                    cloud_cost=cloud if is_overhead else None,
                    total_cost=total,
                ))

        result: Dict[str, List[InstancePoolDailySpend]] = {}
        for pool_id, pool_days in days_by_pool.items():
            ordered_days = sorted(pool_days.values(), key=lambda d: d.usage_date)
            for day in ordered_days:
                # Exclude the synthetic `__pool_overhead__` row from the count:
                # it stays in `day.clusters` for the "Pool overhead" drill-down
                # line, but it is not a real attached cluster, so counting it
                # would over-report the per-day "N clusters" badge by one
                # (mirrors the SQL cluster_count fix).
                day.cluster_count_on_day = sum(
                    1 for c in day.clusters
                    if c.cluster_id != '__pool_overhead__'
                )
            result[pool_id] = ordered_days

        return result

    async def get_top_instance_pools(
        self, start_date: date, end_date: date, limit: int = 5
    ) -> List[GroupedInstancePool]:
        """Get top N most expensive instance pools in the window.

        Pool-grain analogue of `get_top_jobs` / `get_all_purpose_top_clusters`.
        Returns flat `GroupedInstancePool` rows with `days=[]` — this
        endpoint powers a top-N card and intentionally skips the
        per-day + per-cluster enrichment query for cost reasons (mirrors
        the existing top-N endpoints' `runs=[]` / `users=[]` pattern;
        see the model docstring on `GroupedJob`).
        """
        # Same `pool_meta_ranked` + BOOL_AND shape as
        # `get_instance_pools_grouped` — see that function's docstring
        # for the rationale (ANY_VALUE across heterogeneous rows was
        # non-deterministic and surfaced misleading "Snapshot missing"
        # badges on pools that have a real snapshot).
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.pool_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
        ),
        pool_meta_ranked AS (
            SELECT
                instance_pool_id,
                pool_name,
                node_type,
                min_idle_instances,
                max_capacity,
                idle_instance_autotermination_minutes,
                pool_deleted_at,
                ROW_NUMBER() OVER (
                    PARTITION BY instance_pool_id
                    ORDER BY pool_snapshot_missing ASC, usage_date DESC
                ) AS rn
            FROM filtered
        ),
        pool_meta AS (
            SELECT instance_pool_id, pool_name, node_type,
                   min_idle_instances, max_capacity,
                   idle_instance_autotermination_minutes, pool_deleted_at
            FROM pool_meta_ranked
            WHERE rn = 1
        ),
        pool_agg AS (
            SELECT
                instance_pool_id,
                BOOL_AND(pool_snapshot_missing)                   AS pool_snapshot_missing,
                -- Exclude the synthetic `__pool_overhead__` sentinel: it is a
                -- pool-level bookkeeping row (idle/warm capacity + NULL-cluster
                -- DBU, plan §3.3/§4.4), not a real attached cluster, so counting
                -- it would over-report "Clusters" by one on every pool that has
                -- an overhead row (and mislabel idle-only pools as "1 cluster").
                COUNT(DISTINCT CASE WHEN cluster_id <> '__pool_overhead__'
                                    THEN cluster_id END)          AS cluster_count,
                COUNT(DISTINCT usage_date)                        AS active_days,
                SUM(databricks_cost)                              AS total_databricks_cost,
                SUM(cloud_cost)                                   AS total_cloud_cost,
                SUM(total_cost)                                   AS total_cost
            FROM filtered
            GROUP BY instance_pool_id
        ),
        pool_level AS (
            SELECT
                a.instance_pool_id,
                m.pool_name,
                m.node_type,
                m.min_idle_instances,
                m.max_capacity,
                m.idle_instance_autotermination_minutes,
                a.pool_snapshot_missing,
                m.pool_deleted_at,
                a.cluster_count,
                a.active_days,
                a.total_databricks_cost,
                a.total_cloud_cost,
                a.total_cost
            FROM pool_agg a
            JOIN pool_meta m USING (instance_pool_id)
        )
        SELECT
            instance_pool_id, pool_name, node_type,
            min_idle_instances, max_capacity,
            idle_instance_autotermination_minutes,
            pool_snapshot_missing, pool_deleted_at,
            cluster_count, active_days,
            total_databricks_cost, total_cloud_cost, total_cost
        FROM pool_level
        ORDER BY total_cost DESC
        LIMIT {limit}
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        pools: List[GroupedInstancePool] = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                pools.append(GroupedInstancePool(
                    instance_pool_id=row[0],
                    pool_name=row[1],
                    node_type=row[2],
                    min_idle_instances=int(row[3]) if row[3] is not None else None,
                    max_capacity=int(row[4]) if row[4] is not None else None,
                    idle_instance_autotermination_minutes=int(row[5]) if row[5] is not None else None,
                    pool_snapshot_missing=self._parse_bool(row[6]) or False,
                    pool_deleted_at=self._parse_timestamp(row[7]),
                    cluster_count=int(row[8]) if row[8] is not None else 0,
                    active_days=int(row[9]) if row[9] is not None else 0,
                    total_databricks_cost=float(row[10]) if row[10] is not None else 0.0,
                    total_cloud_cost=float(row[11]) if row[11] is not None else None,
                    total_cost=float(row[12]) if row[12] is not None else 0.0,
                    days=[],
                ))

        return pools

    async def get_instance_pool_details(
        self, pool_id: str
    ) -> InstancePoolDetails:
        """Get pool configuration details for the pool details modal.

        Reads from `system.compute.instance_pools` (most-recent SCD
        snapshot via `max_by(col, change_time)` per field — plan §5.5 /
        CP6). The system table column is `node_type` (NOT `node_type_id`
        — see plan §10) and `preloaded_spark_version` is singular.
        The query intentionally does NOT read `tags['DatabricksInstancePoolCreatorId']`
        because `system.compute.instance_pools.tags` is documented as
        "user-defined tags ... does not include default tags", so the
        auto-applied creator tag is never present there — it would
        return NULL on every row. Creator info is enriched per-request
        via `get_pool_metadata` which calls the Instance Pools REST API.

        When no system-table snapshot exists, returns a sentinel with
        `pool_snapshot_missing=True` and falls back to the REST API for
        name + creator GUID so a deleted-but-still-tracked pool can
        still surface in the modal.
        """
        escaped_pool_id = pool_id.replace("'", "''")

        snapshot_query = f"""
        SELECT
            instance_pool_id,
            max_by(instance_pool_name,                  change_time) AS pool_name,
            max_by(node_type,                           change_time) AS node_type,
            max_by(min_idle_instances,                  change_time) AS min_idle_instances,
            max_by(max_capacity,                        change_time) AS max_capacity,
            max_by(idle_instance_autotermination_minutes, change_time)
                                                                    AS idle_instance_autotermination_minutes,
            max_by(preloaded_spark_version,             change_time) AS preloaded_spark_version,
            max_by(tags,                                change_time) AS custom_tags,
            max_by(delete_time,                         change_time) AS pool_deleted_at
        FROM system.compute.instance_pools
        WHERE instance_pool_id = '{escaped_pool_id}'
        GROUP BY instance_pool_id
        """

        snapshot_row = None
        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=snapshot_query,
            )
            if (
                response.result
                and response.result.data_array
                and len(response.result.data_array) > 0
            ):
                snapshot_row = response.result.data_array[0]
        except Exception as exc:
            logger.error(
                'Error fetching pool snapshot for %s: %s', pool_id, str(exc)
            )

        # Always attempt REST API enrichment — even when the system-table
        # snapshot is missing, a deleted-but-still-tracked pool can
        # surface name + creator GUID through the Instance Pools API
        # (plan CP6 implementation notes).
        rest_pool_name, creator_id = await self.get_pool_metadata(pool_id)

        if snapshot_row is None:
            return InstancePoolDetails(
                instance_pool_id=pool_id,
                pool_name=rest_pool_name,
                pool_creator_id=creator_id,
                pool_snapshot_missing=True,
            )

        custom_tags = self._parse_tags(snapshot_row[7])
        # Prefer the system-table snapshot for the display name (it's the
        # SCD-collapsed source of truth for the rollup pipeline), and
        # fall back to the REST name when the snapshot row carries NULL.
        pool_name = snapshot_row[1] or rest_pool_name

        return InstancePoolDetails(
            instance_pool_id=snapshot_row[0],
            pool_name=pool_name,
            pool_creator_id=creator_id,
            node_type=snapshot_row[2],
            min_idle_instances=int(snapshot_row[3]) if snapshot_row[3] is not None else None,
            max_capacity=int(snapshot_row[4]) if snapshot_row[4] is not None else None,
            idle_instance_autotermination_minutes=int(snapshot_row[5]) if snapshot_row[5] is not None else None,
            preloaded_spark_version=snapshot_row[6],
            custom_tags=custom_tags,
            pool_snapshot_missing=False,
            pool_deleted_at=self._parse_timestamp(snapshot_row[8]),
        )

    async def get_pool_cost_summary(
        self, pool_id: str
    ) -> Optional[dict]:
        """Aggregated cost summary for a single pool over the lookback window.

        Feeds the LLM analyze endpoint (`/api/instance-pools/{id}/analyze`)
        with the pool-specific context plan §CP7 calls out: idle config
        vs observed peak concurrent attached clusters, ratio of distinct
        clusters to active days, and dollar context for the
        recommendations. As of CP7 the pool EC2/EBS cloud cost is joined in
        (plan §4.4/§4.6), so `total_cloud_cost` carries the real summed
        value — `None` only when no pool-day in the window has a cloud row
        yet (plan §5 / decision #3).

        Returns ``None`` only on query failure; an empty-window pool
        returns a zero-valued dict (with `limited_history=True`) so the
        LLM still gets enough scaffolding to produce a structured
        response rather than throwing.
        """
        try:
            escaped_pool_id = pool_id.replace("'", "''")
            lookback_date = (
                date.today() - timedelta(days=LOOKBACK_DAYS)
            ).isoformat()

            query = f"""
            WITH filtered AS (
                SELECT *
                FROM {self.pool_table_name}
                WHERE instance_pool_id = '{escaped_pool_id}'
                  AND usage_date >= '{lookback_date}'
            ),
            day_level AS (
                SELECT
                    usage_date,
                    COUNT(DISTINCT cluster_id) AS clusters_on_day,
                    SUM(databricks_cost)       AS day_databricks_cost,
                    SUM(cloud_cost)            AS day_cloud_cost,
                    SUM(total_cost)            AS day_total_cost
                FROM filtered
                GROUP BY usage_date
            )
            SELECT
                COALESCE(SUM(day_total_cost), 0)       AS total_spend,
                COALESCE(SUM(day_databricks_cost), 0)  AS total_databricks_cost,
                (SELECT COUNT(DISTINCT cluster_id)
                   FROM filtered)                      AS distinct_cluster_count,
                COUNT(*)                               AS active_days,
                COALESCE(MAX(clusters_on_day), 0)      AS peak_concurrent_clusters,
                COALESCE(AVG(day_total_cost), 0)       AS avg_cost_per_pool_day,
                MIN(usage_date)                        AS first_active_date,
                MAX(usage_date)                        AS last_active_date,
                (SELECT COUNT(*) FROM filtered
                   WHERE cluster_id = '__pool_overhead__') AS pool_overhead_rows,
                SUM(day_cloud_cost)                    AS total_cloud_cost
            FROM day_level
            """

            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query,
            )

            if not response.result or not response.result.data_array:
                return {
                    'total_spend': 0.0,
                    'total_databricks_cost': 0.0,
                    'total_cloud_cost': None,
                    'distinct_cluster_count': 0,
                    'active_days': 0,
                    'peak_concurrent_clusters': 0,
                    'avg_cost_per_pool_day': 0.0,
                    'first_active_date': None,
                    'last_active_date': None,
                    'pool_overhead_rows': 0,
                    'lookback_days': LOOKBACK_DAYS,
                    'limited_history': True,
                }

            row = response.result.data_array[0]
            total_spend = float(row[0]) if row[0] is not None else 0.0
            total_databricks_cost = float(row[1]) if row[1] is not None else 0.0
            distinct_cluster_count = int(row[2]) if row[2] is not None else 0
            active_days = int(row[3]) if row[3] is not None else 0

            return {
                'total_spend': total_spend,
                'total_databricks_cost': total_databricks_cost,
                'total_cloud_cost': float(row[9]) if row[9] is not None else None,
                'distinct_cluster_count': distinct_cluster_count,
                'active_days': active_days,
                'peak_concurrent_clusters': int(row[4]) if row[4] is not None else 0,
                'avg_cost_per_pool_day': float(row[5]) if row[5] is not None else 0.0,
                'first_active_date': row[6],
                'last_active_date': row[7],
                'pool_overhead_rows': int(row[8]) if row[8] is not None else 0,
                'lookback_days': LOOKBACK_DAYS,
                'limited_history': active_days < 3,
            }
        except Exception as exc:
            logger.error(
                'Error fetching pool cost summary for %s: %s',
                pool_id,
                str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # Pipeline Compute (plan_dlt_tab.md, CP6)
    #
    # All `usage_metadata.dlt_pipeline_id` spend, dimensioned by
    # `workload_type`. The rollup table `dbspend360_total_pipeline_spends`
    # is keyed `(workspace_id, pipeline_id, usage_date,
    # billing_origin_product)`; `compute_mode` / `cost_basis` /
    # `workload_type` are pre-computed there (plan §3.3/§5.1), so the reads
    # below collapse them deterministically — never the non-deterministic
    # ANY_VALUE the council flagged.
    # ------------------------------------------------------------------

    @staticmethod
    def _pipeline_workload_filter(workload_type: Optional[List[str]]) -> str:
        """Build the optional `AND workload_type IN (...)` chip filter.

        Used by the §5.1/§5.3 `filtered` CTEs. `workload_type` *only ever
        filters* — it never drops rows from staging (plan §3.1); an empty /
        None selection means "all workloads".
        """
        if not workload_type:
            return ''
        escaped = [w.replace("'", "''") for w in workload_type]
        in_list = ', '.join(f"'{w}'" for w in escaped)
        return f'AND workload_type IN ({in_list})'

    def _pipeline_workspace_clause(self, workspace_id: Optional[str]) -> str:
        """Build the optional `AND workspace_id = '...'` scoping clause.

        `pipeline_id` is only unique within a workspace (plan §3.3/§6), so
        the id-keyed reads scope by `workspace_id` when it is supplied.
        """
        if not workspace_id:
            return ''
        return f"AND workspace_id = '{workspace_id.replace(chr(39), chr(39) * 2)}'"

    async def _resolve_pipeline_workspace(
        self, pipeline_id: str, workspace_id: Optional[str]
    ) -> Optional[str]:
        """Resolve the workspace a `pipeline_id` belongs to (plan §6).

        When `workspace_id` is supplied it is honoured verbatim. Otherwise
        the candidate workspaces are gathered from BOTH the rollup table and
        `system.lakeflow.pipelines` (a pipeline can have metadata but no
        in-window spend, or spend but no metadata — plan §3.5), and:

        * 0 candidates  -> returns ``None`` (caller renders the
          `metadata_missing` sentinel; CP6 exit criterion #3 — a made-up id
          must not raise).
        * 1 candidate   -> returns it.
        * >1 candidates -> raises `AmbiguousPipelineError` (router → HTTP
          409) rather than silently picking one.
        """
        if workspace_id:
            return workspace_id

        escaped_id = pipeline_id.replace("'", "''")
        query = f"""
        SELECT DISTINCT workspace_id FROM (
            SELECT workspace_id FROM {self.pipeline_table_name}
            WHERE pipeline_id = '{escaped_id}'
            UNION
            SELECT workspace_id FROM system.lakeflow.pipelines
            WHERE pipeline_id = '{escaped_id}'
        )
        WHERE workspace_id IS NOT NULL
        """
        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        candidates: List[str] = []
        if response.result and response.result.data_array:
            candidates = [
                row[0] for row in response.result.data_array if row[0] is not None
            ]

        if not candidates:
            return None
        if len(candidates) > 1:
            raise AmbiguousPipelineError(pipeline_id, candidates)
        return candidates[0]

    async def get_pipelines_grouped(
        self,
        start_date: date,
        end_date: date,
        search: Optional[str] = None,
        workload_type: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedPipelines:
        """Paginated By-Pipeline rollup for the Pipeline Compute tab.

        Implements plan §5.1. One row per pipeline in the window, with the
        cost-dominant `workload_type` badge computed as a per-workload
        `SUM(total_cost)` sub-aggregate (`wl`) feeding
        `max_by(workload_type, struct(wl_cost, workload_type))` — summing
        first makes the label the workload with the largest TOTAL cost, not
        the product on the single largest row; the struct tiebreak keeps it
        deterministic (alphabetical) on equal cost (plan §3.1). All
        constant-per-pipeline metadata collapses with `MAX(...)`, and
        `compute_mode`/`cost_basis` collapse with explicit
        `COUNT(DISTINCT)`/`MIN=MAX` CASEs — never `ANY_VALUE`.

        `search` matches `pipeline_name` (case-insensitive substring),
        `pipeline_id` (exact), or `created_by` (case-insensitive substring).
        `workload_type` is the optional chip filter (plan §3.1 — it only
        *labels/filters*, never drops). `days` (per-day expansion) is
        enriched via `_get_batch_pipeline_days`.
        """
        workload_filter = self._pipeline_workload_filter(workload_type)

        escaped_search = search.replace("'", "''") if search else None
        search_clause = ''
        if escaped_search:
            search_clause = (
                "WHERE ("
                f"LOWER(COALESCE(pl.pipeline_name, '')) LIKE LOWER('%{escaped_search}%') "
                f"OR pl.pipeline_id = '{escaped_search}' "
                f"OR LOWER(COALESCE(pl.created_by, '')) LIKE LOWER('%{escaped_search}%')"
                ")"
            )

        data_query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.pipeline_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
              {workload_filter}
        ),
        wl AS (
            SELECT workspace_id, pipeline_id, workload_type,
                   SUM(total_cost) AS wl_cost
            FROM filtered
            GROUP BY workspace_id, pipeline_id, workload_type
        ),
        wl_dominant AS (
            SELECT workspace_id, pipeline_id,
                   max_by(workload_type, struct(wl_cost, workload_type)) AS workload_type
            FROM wl
            GROUP BY workspace_id, pipeline_id
        ),
        pipeline_level AS (
            SELECT workspace_id,
                   pipeline_id,
                   MAX(pipeline_name)             AS pipeline_name,
                   MAX(pipeline_type)             AS pipeline_type,
                   MAX(created_by)                AS created_by,
                   MAX(run_as)                    AS run_as,
                   CASE
                     WHEN COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'
                     ELSE MAX(compute_mode)
                   END                            AS compute_mode,
                   CASE
                     WHEN MIN(cost_basis) = MAX(cost_basis) THEN MAX(cost_basis)
                     ELSE 'partial'
                   END                            AS cost_basis,
                   BOOL_OR(metadata_missing)      AS metadata_missing,
                   MAX(pipeline_deleted_at)       AS pipeline_deleted_at,
                   COUNT(DISTINCT usage_date)     AS active_days,
                   SUM(databricks_cost)           AS total_databricks_cost,
                   SUM(cloud_cost)                AS total_cloud_cost,
                   SUM(total_cost)                AS total_cost
            FROM filtered
            GROUP BY workspace_id, pipeline_id
        )
        SELECT pl.workspace_id, pl.pipeline_id, pl.pipeline_name,
               pl.pipeline_type, pl.created_by, pl.run_as,
               pl.compute_mode, pl.cost_basis, pl.metadata_missing,
               pl.pipeline_deleted_at, pl.active_days,
               pl.total_databricks_cost, pl.total_cloud_cost, pl.total_cost,
               wd.workload_type,
               COUNT(*) OVER() AS total_matching
        FROM pipeline_level pl
        JOIN wl_dominant wd USING (workspace_id, pipeline_id)
        {search_clause}
        ORDER BY pl.total_cost DESC
        LIMIT {limit} OFFSET {offset}
        """

        data_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=data_query,
        )

        total_count = 0
        if data_response.result and data_response.result.data_array:
            total_count = int(data_response.result.data_array[0][15])

        grouped: List[GroupedPipeline] = []
        if data_response.result and data_response.result.data_array:
            id_pairs = [
                (row[0], row[1]) for row in data_response.result.data_array
            ]
            days_by_pipeline = await self._get_batch_pipeline_days(
                id_pairs, start_date, end_date, workload_type=workload_type
            )

            for row in data_response.result.data_array:
                workspace_id = row[0]
                pipeline_id = row[1]
                grouped.append(GroupedPipeline(
                    workspace_id=workspace_id,
                    pipeline_id=pipeline_id,
                    pipeline_name=row[2],
                    pipeline_type=row[3],
                    created_by=row[4],
                    run_as=row[5],
                    compute_mode=row[6],
                    cost_basis=row[7],
                    metadata_missing=self._parse_bool(row[8]) or False,
                    pipeline_deleted_at=self._parse_timestamp(row[9]),
                    active_days=int(row[10]) if row[10] is not None else 0,
                    total_databricks_cost=float(row[11]) if row[11] is not None else 0.0,
                    total_cloud_cost=float(row[12]) if row[12] is not None else None,
                    total_cost=float(row[13]) if row[13] is not None else 0.0,
                    workload_type=row[14],
                    days=days_by_pipeline.get((workspace_id, pipeline_id), []),
                ))

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        current_page = (offset // limit) + 1

        return PaginatedPipelines(
            data=grouped,
            total_count=total_count,
            page=current_page,
            per_page=limit,
            total_pages=total_pages,
            has_next=current_page < total_pages,
            has_previous=current_page > 1,
        )

    async def _get_batch_pipeline_days(
        self,
        id_pairs: List[Tuple[str, str]],
        start_date: date,
        end_date: date,
        workload_type: Optional[List[str]] = None,
    ) -> Dict[Tuple[str, str], List[PipelineDailySpend]]:
        """Fetch the per-day expansion for a batch of pipelines.

        Implements plan §5.2. The rollup is at product grain (plan §3.3), so
        this read sums across `billing_origin_product` within each
        `(workspace_id, pipeline_id, usage_date)` before nesting into
        `GroupedPipeline.days` — the UI still sees exactly one row per
        pipeline-day, and the §9 invariant "sum of `days[].total_cost` ==
        the pipeline's `total_cost`" is therefore structural.

        `workload_type` MUST mirror the chip filter applied by the calling
        `get_pipelines_grouped` query: the row total is computed over the
        filtered `workload_type IN (...)` slice, so the per-day breakdown has
        to apply the same predicate or the days will not sum to the row total
        (plan §9 #11). Omitting it would re-include every workload's spend and
        overstate the drill-down for multi-workload pipelines.

        Keyed on `(workspace_id, pipeline_id)` because `pipeline_id` is only
        unique within a workspace (plan §3.3); a bare `pipeline_id IN (...)`
        filter is used in the query (it is the selective predicate) and the
        rows are bucketed back onto the right workspace in Python.
        """
        if not id_pairs:
            return {}

        pipeline_ids = sorted({pid for _, pid in id_pairs})
        in_clause = ', '.join(
            f"'{pid.replace(chr(39), chr(39) * 2)}'" for pid in pipeline_ids
        )
        workload_filter = self._pipeline_workload_filter(workload_type)

        query = f"""
        SELECT workspace_id,
               pipeline_id,
               usage_date,
               SUM(databricks_cost)                        AS databricks_cost,
               CASE WHEN MIN(cost_basis) = MAX(cost_basis) THEN MAX(cost_basis)
                    ELSE 'partial' END                     AS cost_basis,
               SUM(cloud_cost)                             AS cloud_cost,
               SUM(total_cost)                             AS total_cost
        FROM {self.pipeline_table_name}
        WHERE pipeline_id IN ({in_clause})
          AND usage_date >= '{start_date.isoformat()}'
          AND usage_date <= '{end_date.isoformat()}'
          {workload_filter}
        GROUP BY workspace_id, pipeline_id, usage_date
        ORDER BY pipeline_id, usage_date
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        result: Dict[Tuple[str, str], List[PipelineDailySpend]] = {}
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                key = (row[0], row[1])
                result.setdefault(key, []).append(PipelineDailySpend(
                    usage_date=date.fromisoformat(row[2]),
                    databricks_cost=float(row[3]) if row[3] is not None else 0.0,
                    cost_basis=row[4],
                    cloud_cost=float(row[5]) if row[5] is not None else None,
                    total_cost=float(row[6]) if row[6] is not None else 0.0,
                ))

        return result

    async def get_top_pipelines(
        self,
        start_date: date,
        end_date: date,
        limit: int = 5,
        workload_type: Optional[List[str]] = None,
    ) -> List[GroupedPipeline]:
        """Get top N most expensive pipelines in the window.

        Pipeline-grain analogue of `get_top_instance_pools`. Returns flat
        `GroupedPipeline` rows with `days=[]` — this endpoint powers a
        top-N card and intentionally skips the per-day enrichment query for
        cost reasons (mirrors the other tabs' top-N pattern). The
        cost-dominant `workload_type` badge uses the same sum-then-`max_by`
        shape as `get_pipelines_grouped` (plan §3.1/§5.1).

        `workload_type` mirrors the chip filter applied to the KPI strip and
        table so the Top-5 card narrows in lock-step (plan §3.1); an empty /
        None selection means "all workloads".
        """
        workload_filter = self._pipeline_workload_filter(workload_type)
        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.pipeline_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
              {workload_filter}
        ),
        wl AS (
            SELECT workspace_id, pipeline_id, workload_type,
                   SUM(total_cost) AS wl_cost
            FROM filtered
            GROUP BY workspace_id, pipeline_id, workload_type
        ),
        wl_dominant AS (
            SELECT workspace_id, pipeline_id,
                   max_by(workload_type, struct(wl_cost, workload_type)) AS workload_type
            FROM wl
            GROUP BY workspace_id, pipeline_id
        ),
        pipeline_level AS (
            SELECT workspace_id,
                   pipeline_id,
                   MAX(pipeline_name)             AS pipeline_name,
                   MAX(pipeline_type)             AS pipeline_type,
                   MAX(created_by)                AS created_by,
                   MAX(run_as)                    AS run_as,
                   CASE
                     WHEN COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'
                     ELSE MAX(compute_mode)
                   END                            AS compute_mode,
                   CASE
                     WHEN MIN(cost_basis) = MAX(cost_basis) THEN MAX(cost_basis)
                     ELSE 'partial'
                   END                            AS cost_basis,
                   BOOL_OR(metadata_missing)      AS metadata_missing,
                   MAX(pipeline_deleted_at)       AS pipeline_deleted_at,
                   COUNT(DISTINCT usage_date)     AS active_days,
                   SUM(databricks_cost)           AS total_databricks_cost,
                   SUM(cloud_cost)                AS total_cloud_cost,
                   SUM(total_cost)                AS total_cost
            FROM filtered
            GROUP BY workspace_id, pipeline_id
        )
        SELECT pl.workspace_id, pl.pipeline_id, pl.pipeline_name,
               pl.pipeline_type, pl.created_by, pl.run_as,
               pl.compute_mode, pl.cost_basis, pl.metadata_missing,
               pl.pipeline_deleted_at, pl.active_days,
               pl.total_databricks_cost, pl.total_cloud_cost, pl.total_cost,
               wd.workload_type
        FROM pipeline_level pl
        JOIN wl_dominant wd USING (workspace_id, pipeline_id)
        ORDER BY pl.total_cost DESC
        LIMIT {limit}
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        pipelines: List[GroupedPipeline] = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                pipelines.append(GroupedPipeline(
                    workspace_id=row[0],
                    pipeline_id=row[1],
                    pipeline_name=row[2],
                    pipeline_type=row[3],
                    created_by=row[4],
                    run_as=row[5],
                    compute_mode=row[6],
                    cost_basis=row[7],
                    metadata_missing=self._parse_bool(row[8]) or False,
                    pipeline_deleted_at=self._parse_timestamp(row[9]),
                    active_days=int(row[10]) if row[10] is not None else 0,
                    total_databricks_cost=float(row[11]) if row[11] is not None else 0.0,
                    total_cloud_cost=float(row[12]) if row[12] is not None else None,
                    total_cost=float(row[13]) if row[13] is not None else 0.0,
                    workload_type=row[14],
                    days=[],
                ))

        return pipelines

    async def get_pipeline_summary_metrics(
        self,
        start_date: date,
        end_date: date,
        workload_type: Optional[List[str]] = None,
    ) -> PipelineSummaryMetrics:
        """Get summary metrics for the Pipeline Compute tab KPI strip.

        Implements plan §5.3. The pipeline-count split is exhaustive of
        THREE buckets (`serverless` + `classic` + `mixed` ==
        `total_pipelines`) so mode-switchers land in `mixed` and are never
        double-counted; the `$` split is likewise three buckets summing to
        `total_spend` so the summary footnote stays exact when mixed rows
        exist. `metadata_unavailable` counts only pipelines whose
        cost-dominant `workload_type` is in `METADATA_BEARING_WORKLOADS`
        (Vector Search etc. excluded — plan §3.5). The per-`workload_type`
        `$` breakdown is computed by a second small query and is EXACT
        because `billing_origin_product` is in the rollup grain (plan
        §3.1/§5.3 — no dominant-product approximation).
        """
        workload_filter = self._pipeline_workload_filter(workload_type)
        metadata_bearing_list = ', '.join(
            f"'{w}'" for w in METADATA_BEARING_WORKLOADS
        )

        query = f"""
        WITH filtered AS (
            SELECT *
            FROM {self.pipeline_table_name}
            WHERE usage_date >= '{start_date.isoformat()}'
              AND usage_date <= '{end_date.isoformat()}'
              {workload_filter}
        ),
        wl AS (
            SELECT workspace_id, pipeline_id, workload_type,
                   SUM(total_cost) AS wl_cost
            FROM filtered
            GROUP BY workspace_id, pipeline_id, workload_type
        ),
        pipe_wl AS (
            SELECT workspace_id, pipeline_id,
                   max_by(workload_type, struct(wl_cost, workload_type)) AS workload_type
            FROM wl
            GROUP BY workspace_id, pipeline_id
        ),
        pipe AS (
            SELECT workspace_id, pipeline_id,
                   CASE WHEN COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'
                        ELSE MAX(compute_mode) END AS compute_mode,
                   BOOL_OR(metadata_missing)       AS metadata_missing,
                   SUM(total_cost)                 AS pipe_cost,
                   SUM(databricks_cost)            AS pipe_databricks_cost,
                   SUM(cloud_cost)                 AS pipe_cloud_cost,
                   SUM(CASE WHEN compute_mode='serverless' THEN total_cost ELSE 0 END) AS serverless_cost,
                   SUM(CASE WHEN compute_mode='classic'    THEN total_cost ELSE 0 END) AS classic_cost,
                   SUM(CASE WHEN compute_mode='mixed'      THEN total_cost ELSE 0 END) AS mixed_cost
            FROM filtered
            GROUP BY workspace_id, pipeline_id
        )
        SELECT
            COUNT(*)                                                      AS total_pipelines,
            SUM(CASE WHEN p.compute_mode='serverless' THEN 1 ELSE 0 END)  AS serverless_pipelines,
            SUM(CASE WHEN p.compute_mode='classic'    THEN 1 ELSE 0 END)  AS classic_pipelines,
            SUM(CASE WHEN p.compute_mode='mixed'      THEN 1 ELSE 0 END)  AS mixed_pipelines,
            SUM(CASE WHEN p.metadata_missing AND pw.workload_type IN ({metadata_bearing_list})
                     THEN 1 ELSE 0 END)                                   AS metadata_unavailable,
            COALESCE(SUM(p.pipe_cost), 0)                                 AS total_spend,
            COALESCE(SUM(p.serverless_cost), 0)                           AS serverless_spend,
            COALESCE(SUM(p.classic_cost), 0)                             AS classic_spend,
            COALESCE(SUM(p.mixed_cost), 0)                               AS mixed_spend,
            COALESCE(SUM(p.pipe_databricks_cost), 0)                      AS total_databricks_cost,
            SUM(p.pipe_cloud_cost)                                        AS total_cloud_cost
        FROM pipe p
        JOIN pipe_wl pw USING (workspace_id, pipeline_id)
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        date_range_days = (end_date - start_date).days + 1

        # Per-workload $ breakdown — exact because billing_origin_product is
        # in the rollup grain (plan §3.1/§5.3).
        breakdown_query = f"""
        SELECT workload_type, SUM(total_cost) AS wl_cost
        FROM {self.pipeline_table_name}
        WHERE usage_date >= '{start_date.isoformat()}'
          AND usage_date <= '{end_date.isoformat()}'
          {workload_filter}
        GROUP BY workload_type
        ORDER BY wl_cost DESC
        """
        breakdown_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=breakdown_query,
        )
        workload_breakdown: Dict[str, float] = {}
        if breakdown_response.result and breakdown_response.result.data_array:
            for row in breakdown_response.result.data_array:
                if row[0] is not None:
                    workload_breakdown[row[0]] = (
                        float(row[1]) if row[1] is not None else 0.0
                    )

        if response.result and response.result.data_array:
            row = response.result.data_array[0]
            return PipelineSummaryMetrics(
                total_pipelines=int(row[0]) if row[0] is not None else 0,
                serverless_pipelines=int(row[1]) if row[1] is not None else 0,
                classic_pipelines=int(row[2]) if row[2] is not None else 0,
                mixed_pipelines=int(row[3]) if row[3] is not None else 0,
                metadata_unavailable=int(row[4]) if row[4] is not None else 0,
                total_spend=float(row[5]) if row[5] is not None else 0.0,
                serverless_spend=float(row[6]) if row[6] is not None else 0.0,
                classic_spend=float(row[7]) if row[7] is not None else 0.0,
                mixed_spend=float(row[8]) if row[8] is not None else 0.0,
                total_databricks_cost=float(row[9]) if row[9] is not None else 0.0,
                total_cloud_cost=float(row[10]) if row[10] is not None else None,
                workload_breakdown=workload_breakdown,
                date_range_days=date_range_days,
            )

        return PipelineSummaryMetrics(
            total_pipelines=0,
            serverless_pipelines=0,
            classic_pipelines=0,
            mixed_pipelines=0,
            metadata_unavailable=0,
            total_spend=0.0,
            serverless_spend=0.0,
            classic_spend=0.0,
            mixed_spend=0.0,
            total_databricks_cost=0.0,
            total_cloud_cost=None,
            workload_breakdown=workload_breakdown,
            date_range_days=date_range_days,
        )

    async def get_pipeline_details(
        self, pipeline_id: str, workspace_id: Optional[str] = None
    ) -> PipelineDetails:
        """Get pipeline configuration details for the details modal.

        Reads config straight from `system.lakeflow.pipelines` (most-recent
        SCD snapshot via QUALIFY ROW_NUMBER() per `(workspace_id,
        pipeline_id)` — plan §5.5/§3.4). No REST API, no GUID resolution:
        `created_by`/`run_as` are human-readable system-table values.
        `workload_type`/`compute_mode`/`cost_basis` are collapsed in from the
        rollup so the modal renders the workload badge and DBU-only caveat
        consistently with the list.

        `workspace_id` scopes the reads when supplied; otherwise the
        workspace is resolved across the rollup + system table and an
        `AmbiguousPipelineError` (router → 409) is raised if the id spans
        >1 workspace (plan §6). When no snapshot row exists, returns a
        sentinel with `metadata_missing=True` and config fields None — a
        made-up id must not raise (CP6 exit criterion #3).
        """
        resolved_workspace = await self._resolve_pipeline_workspace(
            pipeline_id, workspace_id
        )
        escaped_id = pipeline_id.replace("'", "''")
        workspace_clause = self._pipeline_workspace_clause(resolved_workspace)

        snapshot_query = f"""
        SELECT workspace_id, pipeline_id, name AS pipeline_name,
               pipeline_type, created_by, run_as, tags,
               delete_time AS pipeline_deleted_at
        FROM system.lakeflow.pipelines
        WHERE pipeline_id = '{escaped_id}'
          {workspace_clause}
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
        """

        snapshot_row = None
        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=snapshot_query,
            )
            if (
                response.result
                and response.result.data_array
                and len(response.result.data_array) > 0
            ):
                snapshot_row = response.result.data_array[0]
        except Exception as exc:
            logger.error(
                'Error fetching pipeline snapshot for %s: %s',
                pipeline_id, str(exc),
            )

        # Collapse the rollup's pre-computed dimensions for this pipeline so
        # the modal can show the workload badge + DBU-only caveat. No date
        # window — the modal describes the pipeline, not a window slice.
        workload_type = None
        compute_mode = None
        cost_basis = None
        dims_query = f"""
        WITH r AS (
            SELECT * FROM {self.pipeline_table_name}
            WHERE pipeline_id = '{escaped_id}'
              {workspace_clause}
        ),
        wl AS (
            SELECT workload_type, SUM(total_cost) AS wl_cost
            FROM r GROUP BY workload_type
        )
        SELECT
            (SELECT max_by(workload_type, struct(wl_cost, workload_type)) FROM wl) AS workload_type,
            CASE WHEN COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'
                 ELSE MAX(compute_mode) END AS compute_mode,
            CASE WHEN MIN(cost_basis) = MAX(cost_basis) THEN MAX(cost_basis)
                 ELSE 'partial' END AS cost_basis
        FROM r
        """
        try:
            dims_response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=dims_query,
            )
            if dims_response.result and dims_response.result.data_array:
                drow = dims_response.result.data_array[0]
                workload_type = drow[0]
                compute_mode = drow[1]
                cost_basis = drow[2]
        except Exception as exc:
            logger.error(
                'Error fetching pipeline dimensions for %s: %s',
                pipeline_id, str(exc),
            )

        if snapshot_row is None:
            return PipelineDetails(
                workspace_id=resolved_workspace or '',
                pipeline_id=pipeline_id,
                workload_type=workload_type,
                compute_mode=compute_mode,
                cost_basis=cost_basis,
                metadata_missing=True,
            )

        return PipelineDetails(
            workspace_id=snapshot_row[0],
            pipeline_id=snapshot_row[1],
            pipeline_name=snapshot_row[2],
            pipeline_type=snapshot_row[3],
            created_by=snapshot_row[4],
            run_as=snapshot_row[5],
            workload_type=workload_type,
            compute_mode=compute_mode,
            cost_basis=cost_basis,
            tags=self._parse_tags(snapshot_row[6]),
            metadata_missing=False,
            pipeline_deleted_at=self._parse_timestamp(snapshot_row[7]),
        )

    async def get_pipeline_cost_summary(
        self, pipeline_id: str, workspace_id: Optional[str] = None
    ) -> Optional[dict]:
        """Aggregated cost summary for a single pipeline over the lookback.

        Feeds the LLM analyze endpoint (`/api/pipelines/{id}/analyze`) with
        the `workload_type` + `cost_basis` context plan §4.1 requires so the
        model never gives confidently-wrong advice on incomplete numbers. As
        of CP2 the classic EC2/EBS cloud cost is joined in (plan §3.2), so
        `total_cloud_cost` carries the real summed value — `None` only when
        the pipeline is fully serverless (no separate VM line); the prompt's
        `cost_basis` caveat still covers the serverless / partial gap.

        `workspace_id` scopes the read when supplied; otherwise resolved
        across workspaces (raises `AmbiguousPipelineError` on collision —
        plan §6). Returns ``None`` only on query failure; an empty-window
        pipeline returns a zero-valued dict (with `limited_history=True`)
        so the LLM still gets scaffolding rather than throwing.
        """
        try:
            resolved_workspace = await self._resolve_pipeline_workspace(
                pipeline_id, workspace_id
            )
            escaped_id = pipeline_id.replace("'", "''")
            workspace_clause = self._pipeline_workspace_clause(resolved_workspace)
            lookback_date = (
                date.today() - timedelta(days=LOOKBACK_DAYS)
            ).isoformat()

            query = f"""
            WITH filtered AS (
                SELECT *
                FROM {self.pipeline_table_name}
                WHERE pipeline_id = '{escaped_id}'
                  {workspace_clause}
                  AND usage_date >= '{lookback_date}'
            ),
            wl AS (
                SELECT workload_type, SUM(total_cost) AS wl_cost
                FROM filtered GROUP BY workload_type
            ),
            day_level AS (
                SELECT usage_date,
                       SUM(databricks_cost) AS day_databricks_cost,
                       SUM(cloud_cost)      AS day_cloud_cost,
                       SUM(total_cost)      AS day_total_cost
                FROM filtered
                GROUP BY usage_date
            )
            SELECT
                COALESCE(SUM(day_total_cost), 0)       AS total_spend,
                COALESCE(SUM(day_databricks_cost), 0)  AS total_databricks_cost,
                COUNT(*)                               AS active_days,
                COALESCE(AVG(day_total_cost), 0)       AS avg_cost_per_day,
                MIN(usage_date)                        AS first_active_date,
                MAX(usage_date)                        AS last_active_date,
                (SELECT max_by(workload_type, struct(wl_cost, workload_type))
                   FROM wl)                            AS workload_type,
                (SELECT CASE WHEN COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'
                             ELSE MAX(compute_mode) END FROM filtered) AS compute_mode,
                (SELECT CASE WHEN MIN(cost_basis) = MAX(cost_basis) THEN MAX(cost_basis)
                             ELSE 'partial' END FROM filtered)         AS cost_basis,
                (SELECT COUNT(DISTINCT workload_type) FROM filtered)   AS distinct_workload_count,
                SUM(day_cloud_cost)                    AS total_cloud_cost
            FROM day_level
            """

            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=query,
            )

            if not response.result or not response.result.data_array:
                return {
                    'total_spend': 0.0,
                    'total_databricks_cost': 0.0,
                    'total_cloud_cost': None,
                    'active_days': 0,
                    'avg_cost_per_day': 0.0,
                    'first_active_date': None,
                    'last_active_date': None,
                    'workload_type': None,
                    'compute_mode': None,
                    'cost_basis': None,
                    'distinct_workload_count': 0,
                    'workspace_id': resolved_workspace,
                    'lookback_days': LOOKBACK_DAYS,
                    'limited_history': True,
                }

            row = response.result.data_array[0]
            active_days = int(row[2]) if row[2] is not None else 0

            return {
                'total_spend': float(row[0]) if row[0] is not None else 0.0,
                'total_databricks_cost': float(row[1]) if row[1] is not None else 0.0,
                'total_cloud_cost': float(row[10]) if row[10] is not None else None,
                'active_days': active_days,
                'avg_cost_per_day': float(row[3]) if row[3] is not None else 0.0,
                'first_active_date': row[4],
                'last_active_date': row[5],
                'workload_type': row[6],
                'compute_mode': row[7],
                'cost_basis': row[8],
                'distinct_workload_count': int(row[9]) if row[9] is not None else 0,
                'workspace_id': resolved_workspace,
                'lookback_days': LOOKBACK_DAYS,
                'limited_history': active_days < 3,
            }
        except AmbiguousPipelineError:
            raise
        except Exception as exc:
            logger.error(
                'Error fetching pipeline cost summary for %s: %s',
                pipeline_id,
                str(exc),
            )
            return None

    @staticmethod
    def _parse_bool(raw):
        """Parse a Spark BOOLEAN value returned by Statement Execution.

        CRITICAL: the Statement Execution API serializes BOOLEAN columns
        as the string literals ``'true'`` / ``'false'`` inside
        ``result.data_array``. The earlier ``bool(row[i])`` cast was a
        latent bug — Python's ``bool('false')`` is ``True`` because any
        non-empty string is truthy. That bug surfaced as the CP10 review's
        item #1: ``pool_snapshot_missing`` flipped to TRUE for every row
        whose actual rollup value was ``false``, making /grouped disagree
        with /details and over-counting the orphan KPI.

        Accepts the SQL-string shape (``'true'`` / ``'false'`` /
        ``'TRUE'`` / ``'FALSE'``), already-decoded ``bool``, numeric 0/1,
        and ``None``. Returns ``None`` only when the raw value is
        ``None`` so the caller can preserve nullable semantics.
        """
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            return raw.strip().lower() == 'true'
        return bool(raw)

    @staticmethod
    def _parse_timestamp(raw: Optional[str]):
        """Parse a Spark TIMESTAMP value returned by Statement Execution.

        The Statement Execution API serializes TIMESTAMP columns as ISO
        strings; pydantic's `datetime` field would accept the string but
        normalizing here keeps the wire shape predictable across callers
        and matches what `pool_deleted_at` consumers expect.
        """
        if raw is None or raw == '':
            return None
        from datetime import datetime
        try:
            normalized = raw.replace(' ', 'T') if 'T' not in raw else raw
            return datetime.fromisoformat(normalized)
        except Exception:
            return None

    @staticmethod
    def _parse_tags(raw):
        """Best-effort parse for a Spark MAP<STRING,STRING> column.

        Statement Execution may return MAP columns as JSON-encoded strings
        or, depending on protocol negotiation, as already-decoded dicts.
        Mirrors the defensive parsing in `get_cluster_details` and falls
        back to `{"raw": value}` so the modal can still surface the raw
        payload when the encoding shape changes.
        """
        if raw is None or raw == '':
            return None
        if isinstance(raw, dict):
            return raw
        import json
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {'raw': raw}
        except Exception:
            return {'raw': raw}

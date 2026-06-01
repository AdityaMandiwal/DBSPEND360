import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Literal, Optional, Tuple

from databricks.sdk import WorkspaceClient

from server.models.job_spend import (
    JobSpend, SummaryMetrics, CostBreakdown, PaginatedJobSpends,
    GroupedJob, JobRun, PaginatedGroupedJobs, ClusterDetails,
    OtherCostBreakdownItem, OtherCostBreakdownResponse,
    CoverageTrendPoint, CoverageTrendResponse,
    AllPurposeUserSpend, AllPurposeClusterSpend,
    GroupedAllPurposeCluster, GroupedAllPurposeUser,
    AllPurposeSummaryMetrics,
    PaginatedAllPurposeClusters, PaginatedAllPurposeUsers,
)
from server.config.config_loader import app_config

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 180


class DatabricksService:
    """Service for interacting with Databricks SQL Warehouse."""

    def __init__(self):
        # Check if we're running in Databricks Apps (OAuth available)
        client_id = os.getenv("DATABRICKS_CLIENT_ID")
        host = os.getenv("DATABRICKS_HOST")
        token = os.getenv("DATABRICKS_TOKEN")

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
            raise ValueError("Either DATABRICKS_CLIENT_ID (for OAuth) or both DATABRICKS_HOST and DATABRICKS_TOKEN (for PAT) must be set")

        # Load configuration from environment-specific config files
        self.warehouse_id = app_config.warehouse_id
        self.table_name = app_config.table_name
        self.all_purpose_table_name = app_config.all_purpose_table_name
        self.query_timeout = app_config.query_timeout_seconds
        self.job_name_cache: Dict[str, str] = {}  # Cache for job names

    async def get_job_name(self, job_id: str) -> str:
        """Get job name from Jobs API with caching."""
        if job_id in self.job_name_cache:
            return self.job_name_cache[job_id]

        try:
            # Try to get job details from Jobs API
            job = self.client.jobs.get(job_id=int(job_id))
            job_name = job.settings.name if job.settings and job.settings.name else f"Job {job_id}"
            self.job_name_cache[job_id] = job_name
            return job_name
        except Exception as e:
            # If job doesn't exist or we can't access it, return a default name
            job_name = f"Job {job_id}"
            self.job_name_cache[job_id] = job_name
            return job_name

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
                    coverage_status = "ok"
                elif coverage_pct >= 80:
                    coverage_status = "warning"
                    coverage_warning = (
                        "Moderate unclassified cost detected. "
                        "Review the 'Other' category for potential classification improvements."
                    )
                else:
                    coverage_status = "critical"
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

    async def get_grouped_job_spends(
        self,
        start_date: date,
        end_date: date,
        job_name: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> PaginatedGroupedJobs:
        """Get paginated job spending data grouped by job with run details.

        The job_name parameter is used as a general search term that matches
        against both job name (from system.lakeflow.jobs) and job ID.
        """

        escaped_search = job_name.replace("'", "''") if job_name else None
        search_clause = ""
        if escaped_search:
            search_clause = f"WHERE (j.job_id LIKE '%{escaped_search}%' OR LOWER(COALESCE(lj.name, '')) LIKE LOWER('%{escaped_search}%'))"

        base_cte = f"""
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
        )"""

        data_query = f"""
        {base_cte}
        SELECT
            j.job_id,
            j.total_cloud_cost,
            j.total_databricks_cost,
            j.run_count,
            lj.name,
            COUNT(*) OVER() AS total_matching,
            j.total_compute_cost,
            j.total_storage_cost,
            j.total_network_cost,
            j.total_other_cost
        FROM job_level j
        LEFT JOIN (
            -- system.lakeflow.jobs is an SCD table that retains one row per
            -- (job_id, name, change_time) snapshot. SELECT DISTINCT job_id, name
            -- would keep every historical name for a renamed job and fan the
            -- aggregated upstream row out into duplicates. Collapse to the most
            -- recent name per job_id so this join is exactly 1:1.
            SELECT job_id, MAX_BY(name, change_time) AS name
            FROM system.lakeflow.jobs
            GROUP BY job_id
        ) lj
        ON j.job_id = lj.job_id
        {search_clause}
        ORDER BY (j.total_cloud_cost + j.total_databricks_cost) DESC
        LIMIT {limit} OFFSET {offset}
        """

        data_response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=data_query
        )

        total_count = 0
        if data_response.result and data_response.result.data_array:
            total_count = int(data_response.result.data_array[0][5])

        grouped_jobs = []
        if data_response.result and data_response.result.data_array:
            job_ids = [row[0] for row in data_response.result.data_array]
            runs_by_job = await self._get_batch_job_runs(job_ids, start_date, end_date, runs_per_job=10)

            for row in data_response.result.data_array:
                job_id = row[0]
                total_cloud_cost = float(row[1])
                total_databricks_cost = float(row[2])
                run_count = int(row[3])

                grouped_job = GroupedJob(
                    job_id=job_id,
                    job_name=row[4],
                    run_count=run_count,
                    total_cloud_cost=total_cloud_cost,
                    total_databricks_cost=total_databricks_cost,
                    total_compute_cost=float(row[6]) if row[6] is not None else None,
                    total_storage_cost=float(row[7]) if row[7] is not None else None,
                    total_network_cost=float(row[8]) if row[8] is not None else None,
                    total_other_cost=float(row[9]) if row[9] is not None else None,
                    runs=runs_by_job.get(job_id, [])
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
        in_clause = ", ".join(f"'{jid}'" for jid in escaped_ids)

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
                    tags = {"raw": row[10]} if row[10] else None

                try:
                    if row[11]:  # aws_attributes
                        aws_attributes = json.loads(row[11])
                except:
                    aws_attributes = {"raw": row[11]} if row[11] else None

                try:
                    if row[12]:  # azure_attributes
                        azure_attributes = json.loads(row[12])
                except:
                    azure_attributes = {"raw": row[12]} if row[12] else None

                try:
                    if row[13]:  # gcp_attributes
                        gcp_attributes = json.loads(row[13])
                except:
                    gcp_attributes = {"raw": row[13]} if row[13] else None

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
                    enable_elastic_disk=bool(row[9]) if row[9] is not None else None,
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
            logger.error("Error fetching cluster details for %s: %s", cluster_id, str(e))
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
            return "high"
        if filtered_runs >= 10:
            return "emerging"
        if filtered_runs >= 3:
            return "limited"
        return "none"

    @staticmethod
    def _is_permission_error(exc: Exception) -> bool:
        """Detect missing-grant errors so we can fall back gracefully."""
        msg = str(exc).lower()
        keywords = (
            "permission denied",
            "insufficient_permissions",
            "insufficient permissions",
            "table or view not found",
            "table_or_view_not_found",
            "does not have",
            "access denied",
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
        if current_state is not None and current_state != "SUCCEEDED":
            return None, None
        if (
            current_cost is None
            or reference_cost is None
            or reference_cost <= MIN_REFERENCE_THRESHOLD
        ):
            return None, None

        pct = ((current_cost - reference_cost) / reference_cost) * 100
        if pct > 0:
            text = f"+{pct:.1f}% above {reference_label}"
        elif pct < 0:
            text = f"{pct:.1f}% below {reference_label}"
        else:
            text = f"at {reference_label}"
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
                        "Falling back to unfiltered historical stats for job %s "
                        "(system.lakeflow.job_run_timeline not accessible): %s",
                        job_id, str(exc),
                    )
                    return None
                raise

            # Statement may also fail server-side with status=FAILED.
            status = getattr(response, "status", None)
            if status is not None and getattr(status, "error", None) is not None:
                err_msg = getattr(status.error, "message", "") or ""
                if self._is_permission_error(Exception(err_msg)):
                    logger.warning(
                        "Falling back to unfiltered historical stats for job %s "
                        "(system.lakeflow.job_run_timeline not accessible): %s",
                        job_id, err_msg,
                    )
                    return None

            if not response.result or not response.result.data_array:
                return {
                    "total_runs": 0,
                    "limited_history": True,
                    "confidence_tier": "none",
                    "state_filter_applied": True,
                    "current_run_state": None,
                    "total_runs_unfiltered": 0,
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
                "median" if median_cost is not None else "average"
            )
            comparison, comparison_pct = self._build_comparison(
                current_cost=current_cost,
                reference_cost=reference_cost if total_runs > 0 else None,
                reference_label=reference_label,
                current_state=current_state,
            )

            result: dict = {
                "total_runs": total_runs,
                "total_runs_unfiltered": total_runs_unfiltered,
                "limited_history": total_runs < 3,
                "confidence_tier": self._confidence_tier(total_runs),
                "state_filter_applied": True,
                "current_run_state": current_state,
                "current_cost": current_cost,
                "current_cloud_cost": (
                    float(row[11]) if row[11] is not None else None
                ),
                "current_databricks_cost": (
                    float(row[12]) if row[12] is not None else None
                ),
                "comparison": comparison,
                "comparison_pct": comparison_pct,
                "comparison_reference": (
                    reference_label if comparison is not None else None
                ),
            }

            if total_runs > 0:
                result.update({
                    "avg_cost": avg_cost,
                    "median_cost": median_cost,
                    "p90_cost": p90_cost,
                    "min_cost": float(row[4]) if row[4] is not None else 0.0,
                    "max_cost": float(row[5]) if row[5] is not None else 0.0,
                    "stddev_cost": stddev_cost,
                    "avg_cloud_pct": float(row[7]) if row[7] is not None else 0.0,
                    "data_start": row[8],
                    "data_end": row[9],
                    "last_run_cost": (
                        float(row[13]) if row[13] is not None else None
                    ),
                })

            return result

        except Exception as e:
            if self._is_permission_error(e):
                logger.warning(
                    "Falling back to unfiltered historical stats for job %s "
                    "(system.lakeflow.job_run_timeline not accessible): %s",
                    job_id, str(e),
                )
                return None
            logger.error(
                "Error fetching filtered historical stats for job %s: %s",
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
                    "total_runs": 0,
                    "limited_history": True,
                    "confidence_tier": "none",
                    "state_filter_applied": False,
                    "current_run_state": None,
                    "total_runs_unfiltered": 0,
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
                "median" if median_cost is not None else "average"
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
                "total_runs": total_runs,
                "total_runs_unfiltered": total_runs,
                "limited_history": total_runs < 3,
                "confidence_tier": self._confidence_tier(total_runs),
                "state_filter_applied": False,
                "current_run_state": None,
                "current_cost": current_cost,
                "current_cloud_cost": (
                    float(row[11]) if row[11] is not None else None
                ),
                "current_databricks_cost": (
                    float(row[12]) if row[12] is not None else None
                ),
                "comparison": comparison,
                "comparison_pct": comparison_pct,
                "comparison_reference": (
                    reference_label if comparison is not None else None
                ),
            }

            if total_runs > 0:
                result.update({
                    "avg_cost": avg_cost,
                    "median_cost": median_cost,
                    "p90_cost": p90_cost,
                    "min_cost": float(row[4]) if row[4] is not None else 0.0,
                    "max_cost": float(row[5]) if row[5] is not None else 0.0,
                    "stddev_cost": stddev_cost,
                    "avg_cloud_pct": float(row[7]) if row[7] is not None else 0.0,
                    "data_start": row[8],
                    "data_end": row[9],
                    "last_run_cost": (
                        float(row[13]) if row[13] is not None else None
                    ),
                })

            return result

        except Exception as e:
            logger.error(
                "Error fetching unfiltered historical stats for job %s: %s",
                job_id, str(e),
            )
            return None

    async def get_cluster_cost_summary(
        self,
        cluster_id: str,
        cluster_kind: Literal["job", "all_purpose"] = "job",
    ) -> Optional[dict]:
        """Get aggregated cost summary for a cluster over the lookback window.

        For ``cluster_kind="job"`` (default) groups by ``(job_id, run_id)``
        against ``dbspend360_total_job_spends`` — the existing job-cluster
        path. The default value preserves every existing call site
        byte-identically; do not change it without auditing them.

        For ``cluster_kind="all_purpose"`` groups by ``(user_id, usage_date)``
        against ``dbspend360_total_all_purpose_spends`` — the natural grain
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
        if cluster_kind == "all_purpose":
            return await self._get_cluster_cost_summary_all_purpose(cluster_id)
        return await self._get_cluster_cost_summary_job(cluster_id)

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
                    "total_spend": 0.0,
                    "total_cloud_cost": 0.0,
                    "total_databricks_cost": 0.0,
                    "cloud_pct": 0.0,
                    "databricks_pct": 0.0,
                    "distinct_job_count": 0,
                    "total_run_count": 0,
                    "avg_cost_per_run": 0.0,
                    "first_active_date": None,
                    "last_active_date": None,
                    "limited_history": True,
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
                "total_spend": total_spend,
                "total_cloud_cost": total_cloud_cost,
                "total_databricks_cost": total_databricks_cost,
                "cloud_pct": cloud_pct,
                "databricks_pct": databricks_pct,
                "distinct_job_count": int(row[3]),
                "total_run_count": total_run_count,
                "avg_cost_per_run": float(row[5]),
                "first_active_date": row[6],
                "last_active_date": row[7],
                "limited_history": total_run_count < 3,
            }

        except Exception as e:
            logger.error(
                "Error fetching cluster cost summary for %s: %s",
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
                    "total_spend": 0.0,
                    "total_cloud_cost": 0.0,
                    "total_databricks_cost": 0.0,
                    "cloud_pct": 0.0,
                    "databricks_pct": 0.0,
                    "distinct_job_count": 0,
                    "distinct_user_count": 0,
                    "total_run_count": 0,
                    "avg_cost_per_run": 0.0,
                    "first_active_date": None,
                    "last_active_date": None,
                    "limited_history": True,
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
                "total_spend": total_spend,
                "total_cloud_cost": total_cloud_cost,
                "total_databricks_cost": total_databricks_cost,
                "cloud_pct": cloud_pct,
                "databricks_pct": databricks_pct,
                # No job concept on all-purpose clusters; kept at 0 so the
                # shared LLM prompt builder doesn't KeyError on the job path's
                # `distinct_job_count` access.
                "distinct_job_count": 0,
                "distinct_user_count": distinct_user_count,
                "total_run_count": total_run_count,
                "avg_cost_per_run": float(row[5]) if row[5] is not None else 0.0,
                "first_active_date": row[6],
                "last_active_date": row[7],
                "limited_history": total_run_count < 3,
            }

        except Exception as e:
            logger.error(
                "Error fetching all-purpose cluster cost summary for %s: %s",
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

        breakdown_table = f"{schema_name}.dbspend360_other_cost_breakdown"

        where_parts = [
            f"cost_incurred_date >= '{start_date.isoformat()}'",
            f"cost_incurred_date <= '{end_date.isoformat()}'",
        ]
        if cluster_id:
            escaped = cluster_id.replace("'", "''")
            where_parts.append(f"cluster_id = '{escaped}'")

        where_clause = " AND ".join(where_parts)

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
                        service_name=row[0] or "Unknown",
                        source_system=row[1] or "Unknown",
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
            logger.error("Error fetching other cost breakdown: %s", str(e))
            return OtherCostBreakdownResponse(
                items=[], total_other_cost=0.0,
                start_date=start_date, end_date=end_date,
            )

    async def get_classification_coverage_trend(
        self,
        limit: int = 30,
    ) -> CoverageTrendResponse:
        """Get classification coverage trend from the audit log.

        Parses `classification_coverage=XX.X%` from the message column
        of successful cloud cost explorer runs.
        """
        schema_name = app_config.schema_name
        if not schema_name:
            return CoverageTrendResponse(data=[])

        audit_table = f"{schema_name}.dbspend360_audit_log"

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
          AND message LIKE '%classification_coverage=%'
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
            logger.error("Error fetching coverage trend: %s", str(e))
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
        search_clause = ""
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
        ORDER BY (c.total_cloud_cost + c.total_databricks_cost) DESC
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
                    owner_user_id=row[1] or "__unknown__",
                    data_security_mode=row[2],
                    active_days=int(row[3]) if row[3] is not None else 0,
                    total_cloud_cost=float(row[4]) if row[4] is not None else 0.0,
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
        search_clause = ""
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
        ORDER BY (total_cloud_cost + total_databricks_cost) DESC
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
                user_id = row[0] or "__unknown__"
                grouped.append(GroupedAllPurposeUser(
                    user_id=user_id,
                    cluster_count=int(row[1]) if row[1] is not None else 0,
                    user_active_days=int(row[2]) if row[2] is not None else 0,
                    total_cloud_cost=float(row[3]) if row[3] is not None else 0.0,
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
        ORDER BY (c.total_cloud_cost + c.total_databricks_cost) DESC
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
                    owner_user_id=row[1] or "__unknown__",
                    data_security_mode=row[2],
                    active_days=int(row[3]) if row[3] is not None else 0,
                    total_cloud_cost=float(row[4]) if row[4] is not None else 0.0,
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
        ORDER BY (total_cloud_cost + total_databricks_cost) DESC
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
                    user_id=row[0] or "__unknown__",
                    cluster_count=int(row[1]) if row[1] is not None else 0,
                    user_active_days=int(row[2]) if row[2] is not None else 0,
                    total_cloud_cost=float(row[3]) if row[3] is not None else 0.0,
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
        in_clause = ", ".join(f"'{cid}'" for cid in escaped_ids)

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
                             (SUM(cloud_cost) + SUM(databricks_cost)) DESC
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
                    user_id=row[1] or "__unknown__",
                    usage_date=date.fromisoformat(row[2]),
                    cloud_cost=float(row[3]) if row[3] is not None else 0.0,
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
        in_clause = ", ".join(f"'{uid}'" for uid in escaped_ids)

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
                    ORDER BY (cloud_cost + databricks_cost) DESC, cluster_id
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
        ORDER BY r.user_id, (r.cloud_cost + r.databricks_cost) DESC
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query,
        )

        result: Dict[str, List[AllPurposeClusterSpend]] = {}
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                user_id = row[0] or "__unknown__"
                spend = AllPurposeClusterSpend(
                    cluster_id=row[1],
                    cluster_name=row[2],
                    user_id=user_id,
                    data_security_mode=row[3],
                    cluster_active_days=int(row[4]) if row[4] is not None else 0,
                    cloud_cost=float(row[5]) if row[5] is not None else 0.0,
                    databricks_cost=float(row[6]) if row[6] is not None else 0.0,
                    compute_cost=float(row[7]) if row[7] is not None else None,
                    storage_cost=float(row[8]) if row[8] is not None else None,
                    network_cost=float(row[9]) if row[9] is not None else None,
                    other_cost=float(row[10]) if row[10] is not None else None,
                )
                result.setdefault(user_id, []).append(spend)

        return result
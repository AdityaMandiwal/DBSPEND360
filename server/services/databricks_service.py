import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from databricks.sdk import WorkspaceClient

from server.models.job_spend import JobSpend, SummaryMetrics, CostBreakdown, PaginatedJobSpends, GroupedJob, JobRun, PaginatedGroupedJobs, ClusterDetails
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
            jobs.name as job_name
        FROM {self.table_name} a LEFT OUTER JOIN system.lakeflow.jobs jobs ON a.job_id = jobs.job_id
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
                ###job_name = await self.get_job_name(job_id)

                job_spend = JobSpend(
                    cluster_id=row[0],
                    ec2_cost=float(row[1]),
                    job_id=job_id,
                    job_name=row[6],
                    run_id=row[3],
                    usage_date=date.fromisoformat(row[4]),
                    databricks_cost=float(row[5])
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
        """Get summary metrics for the specified date range."""

        query = f"""
        SELECT
            COUNT(*) as total_jobs,
            SUM(cloud_cost + databricks_cost) as total_spend,
            AVG(cloud_cost + databricks_cost) as avg_cost,
            MAX(cloud_cost + databricks_cost) as max_cost,
            MIN(cloud_cost + databricks_cost) as min_cost,
            SUM(cloud_cost) as total_ec2_cost,
            SUM(databricks_cost) as total_databricks_cost
        FROM {self.table_name}
        WHERE usage_date >= '{start_date.isoformat()}' AND usage_date <= '{end_date.isoformat()}'
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        if response.result and response.result.data_array:
            row = response.result.data_array[0]
            date_range_days = (end_date - start_date).days + 1

            return SummaryMetrics(
                total_jobs=int(row[0]) if row[0] else 0,
                total_spend=float(row[1]) if row[1] else 0.0,
                average_cost=float(row[2]) if row[2] else 0.0,
                max_cost=float(row[3]) if row[3] else 0.0,
                min_cost=float(row[4]) if row[4] else 0.0,
                total_ec2_cost=float(row[5]) if row[5] else 0.0,
                total_databricks_cost=float(row[6]) if row[6] else 0.0,
                date_range_days=date_range_days
            )

        # Return empty metrics if no data
        return SummaryMetrics(
            total_jobs=0,
            total_spend=0.0,
            average_cost=0.0,
            max_cost=0.0,
            min_cost=0.0,
            total_ec2_cost=0.0,
            total_databricks_cost=0.0,
            date_range_days=(end_date - start_date).days + 1
        )

    async def get_job_cost_breakdown(self, job_id: str, run_id: str) -> Optional[CostBreakdown]:
        """Get detailed cost breakdown for a specific job run, aggregated by run_id."""

        # Escape single quotes to prevent SQL injection
        escaped_job_id = job_id.replace("'", "''")
        escaped_run_id = run_id.replace("'", "''")

        query = f"""
        SELECT
            job_id,
            run_id,
            cluster_id,
            usage_date,
            SUM(cloud_cost) as total_ec2_cost,
            SUM(databricks_cost) as total_databricks_cost
        FROM {self.table_name}
        WHERE job_id = '{escaped_job_id}' AND run_id = '{escaped_run_id}'
        GROUP BY job_id, run_id, cluster_id, usage_date
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        if response.result and response.result.data_array:
            row = response.result.data_array[0]
            ec2_cost = float(row[4])
            databricks_cost = float(row[5])

            return CostBreakdown(
                job_id=row[0],
                run_id=row[1],
                cluster_id=row[2],
                usage_date=date.fromisoformat(row[3]),
                ec2_cost=ec2_cost,
                databricks_cost=databricks_cost,
                total_cost=ec2_cost + databricks_cost
            )

        return None

    async def get_top_jobs(self, start_date: date, end_date: date, limit: int = 5) -> List[JobSpend]:
        """Get top N most expensive jobs for the date range."""

        query = f"""
        SELECT
            a.cluster_id,
            a.cloud_cost,
            a.job_id,
            a.run_id,
            a.usage_date,
            a.databricks_cost, 
            jobs.name
        FROM {self.table_name} a LEFT OUTER JOIN system.lakeflow.jobs jobs ON a.job_id = jobs.job_id
        WHERE a.usage_date >= '{start_date.isoformat()}' AND a.usage_date <= '{end_date.isoformat()}'
        ORDER BY (a.cloud_cost + a.databricks_cost) DESC
        LIMIT {limit}
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=query
        )

        jobs = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                job_id = row[2]
                #job_name = await self.get_job_name(job_id)

                job_spend = JobSpend(
                    cluster_id=row[0],
                    ec2_cost=float(row[1]),
                    job_id=job_id,
                    job_name=row[6],
                    run_id=row[3],
                    usage_date=date.fromisoformat(row[4]),
                    databricks_cost=float(row[5])
                )
                jobs.append(job_spend)

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
                SUM(databricks_cost) AS databricks_cost
            FROM filtered
            GROUP BY job_id, run_id
        ),
        job_level AS (
            SELECT
                job_id,
                SUM(cloud_cost) AS total_ec2_cost,
                SUM(databricks_cost) AS total_databricks_cost,
                COUNT(*) AS run_count
            FROM run_level
            GROUP BY job_id
        )"""

        data_query = f"""
        {base_cte}
        SELECT
            j.job_id,
            j.total_ec2_cost,
            j.total_databricks_cost,
            j.run_count,
            lj.name,
            COUNT(*) OVER() AS total_matching
        FROM job_level j
        LEFT JOIN (
            SELECT DISTINCT job_id, name
            FROM system.lakeflow.jobs
        ) lj
        ON j.job_id = lj.job_id
        {search_clause}
        ORDER BY (j.total_ec2_cost + j.total_databricks_cost) DESC
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
                total_ec2_cost = float(row[1])
                total_databricks_cost = float(row[2])
                run_count = int(row[3])

                grouped_job = GroupedJob(
                    job_id=job_id,
                    job_name=row[4],
                    run_count=run_count,
                    total_ec2_cost=total_ec2_cost,
                    total_databricks_cost=total_databricks_cost,
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
                SUM(cloud_cost) as total_ec2_cost,
                SUM(databricks_cost) as total_databricks_cost,
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
               total_ec2_cost, total_databricks_cost
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
                    ec2_cost=float(row[5]),
                    databricks_cost=float(row[6])
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
            SUM(cloud_cost) as total_ec2_cost,
            SUM(databricks_cost) as total_databricks_cost
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
                    ec2_cost=float(row[4]),
                    databricks_cost=float(row[5])
                )
                runs.append(run)

        return runs

    async def get_cluster_details(self, cluster_id: str) -> Optional[ClusterDetails]:
        """Get cluster configuration details from system.compute.clusters."""

        try:
            # Escape single quotes to prevent SQL injection
            escaped_cluster_id = cluster_id.replace("'", "''")

            # Query the system.compute.clusters table for cluster details
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
                dbr_version,
                data_security_mode
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

                # Parse tags and aws_attributes as JSON if they exist
                tags = None
                aws_attributes = None

                try:
                    if row[10]:  # tags
                        import json
                        tags = json.loads(row[10])
                except:
                    tags = {"raw": row[10]} if row[10] else None

                try:
                    if row[11]:  # aws_attributes
                        import json
                        aws_attributes = json.loads(row[11])
                except:
                    aws_attributes = {"raw": row[11]} if row[11] else None

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
                    dbr_version=row[12],
                    data_security_mode=row[13]
                )

            return None

        except Exception as e:
            logger.error("Error fetching cluster details for %s: %s", cluster_id, str(e))
            return None

    async def get_job_historical_stats(
        self, job_id: str, current_run_id: str
    ) -> Optional[dict]:
        """Get historical cost statistics for a job, excluding the current run from baseline.

        Pre-aggregates by run_id (a run may span multiple rows), then computes
        baseline stats, current run cost, and comparison vs average.

        Returns:
            dict with baseline metrics and comparison, or None on failure.
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
                return {"total_runs": 0, "limited_history": True}

            row = response.result.data_array[0]
            total_runs = int(row[0]) if row[0] else 0
            avg_cost = float(row[1]) if row[1] else 0.0
            current_cost = float(row[10]) if row[10] is not None else None

            comparison: Optional[str] = None
            comparison_pct: Optional[float] = None
            MIN_AVG_COST_THRESHOLD = 0.01
            if current_cost is not None and total_runs > 0 and avg_cost > MIN_AVG_COST_THRESHOLD:
                comparison_pct = ((current_cost - avg_cost) / avg_cost) * 100
                if comparison_pct > 0:
                    comparison = f"+{comparison_pct:.1f}% above average"
                elif comparison_pct < 0:
                    comparison = f"{comparison_pct:.1f}% below average"
                else:
                    comparison = "at average"

            result: dict = {
                "total_runs": total_runs,
                "limited_history": total_runs < 3,
                "current_cost": current_cost,
                "current_cloud_cost": (
                    float(row[11]) if row[11] is not None else None
                ),
                "current_databricks_cost": (
                    float(row[12]) if row[12] is not None else None
                ),
                "comparison": comparison,
                "comparison_pct": comparison_pct,
            }

            if total_runs > 0:
                median_cost = float(row[2]) if row[2] is not None else None
                p90_cost = float(row[3]) if row[3] is not None else None
                stddev_cost = float(row[6]) if row[6] is not None else None

                if total_runs < 2:
                    stddev_cost = None
                if total_runs < 3:
                    median_cost = None
                    p90_cost = None

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
                "Error fetching historical stats for job %s: %s",
                job_id, str(e),
            )
            return None

    async def get_cluster_cost_summary(
        self, cluster_id: str
    ) -> Optional[dict]:
        """Get aggregated cost summary for a cluster over the lookback window.

        Groups by (job_id, run_id) to avoid skewed aggregation from
        multi-row runs, then computes totals, splits, and averages.

        Returns:
            dict with cost breakdown, or None on failure.
        """
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
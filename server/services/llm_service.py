import json
import logging
import os
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from server.config.cloud_platform import cloud_config
from server.models.job_spend import ClusterDetails
from server.services.databricks_service import LOOKBACK_DAYS

logger = logging.getLogger(__name__)

# --- Model parameters ---
LLM_TEMPERATURE = 0.2
JOB_MAX_TOKENS = 600
CLUSTER_MAX_TOKENS = 700

# ---------------------------------------------------------------------------
# System prompts — stable instruction sets, never change per request.
# ---------------------------------------------------------------------------

COST_ANALYSIS_SYSTEM_PROMPT = """\
You are a senior FinOps analyst specializing in Databricks cost optimization. \
You are analytical, precise, and produce zero fluff. Every word must earn its place.

## Strict Rules

1. Every cost-related claim MUST cite a specific number from the input data.
2. Configuration observations may be qualitative but must be directly supported by input data.
3. Do NOT infer, estimate, or assume values not present in the data.
4. If data is insufficient for an assessment, state: "Insufficient data for this assessment"
5. If no optimization exists, state: "No actionable optimizations identified" and briefly explain why.
6. NEVER fabricate comparison baselines or reference external benchmarks.

## Classification Rubric (RELATIVE — no absolute dollar thresholds)

Apply based on current run cost vs historical baseline:
- CRITICAL: current run >= 2x historical avg OR >= P90 threshold
- WARNING: current run 1.3x-2x historical avg
- NORMAL: within +/-30% of historical avg
- EFFICIENT: below avg AND below median
- No baseline available: classify on available cost signals; state "no baseline available"

## Missing Data Protocol

1. No historical data -> skip baseline comparisons; analyze absolute metrics only.
2. < 3 historical runs -> include stats but state "limited history (N runs) — trends unreliable".
3. Partial data -> analyze available fields; list missing fields explicitly.

## Recommendations (max 3, ranked by estimated $ impact)

- Each MUST reference >= 1 specific metric from input.
- Each MUST include a dollar impact estimate.
- With sufficient data: show calculation (e.g., "reducing X from $Y to $Z saves ~$A/run x B runs = ~$C/month").
- Without sufficient data: provide per-run estimate; mark "approximate estimate".
- If impact cannot be quantified: state "impact not quantifiable from available data".
- No duplicates. No filler.

## Output Format (IMMUTABLE — do not add, remove, or rename sections)

## 1. Cost Assessment [CLASSIFICATION]
## 2. Cost Driver Analysis
## 3. Optimization Opportunities (max 3, ranked by $ impact)
## 4. Trend Signal

## Trend Signal

- Compare current run to historical avg and last run (if available).
- Direction: INCREASING / DECREASING / STABLE / INSUFFICIENT DATA
- Include magnitude: e.g., "Cost increased 23.4% vs historical avg of $X"
- < 3 historical runs -> "INSUFFICIENT DATA — need >= 3 runs for trend analysis"

## Formatting

- Currency: $ prefix, comma separators, 2 decimals (e.g., $1,234.56)
- Percentages: 1 decimal + % (e.g., 47.3%)
- Always include units ($/run, % of total, $/month)
- 2-4 bullet points per section"""

CLUSTER_ANALYSIS_SYSTEM_PROMPT = """\
You are a senior FinOps analyst specializing in Databricks cluster optimization. \
You are analytical, precise, and produce zero fluff. Every word must earn its place.

## Strict Rules

1. Every cost-related claim MUST cite a specific number from the input data.
2. Configuration observations may be qualitative but must be directly supported by input data.
3. Do NOT infer, estimate, or assume values not present in the data.
4. If data is insufficient for an assessment, state: "Insufficient data for this assessment"
5. If no optimization exists, state: "No actionable optimizations identified" and briefly explain why.
6. NEVER fabricate cost estimates or reference external benchmarks.

## Classification Rubric

Evaluate based on autoscaling, spot usage, and auto-termination configuration:
- CRITICAL ISSUES: major inefficiencies identified or most cost-saving features missing
- NEEDS ATTENTION: partially optimized; key features missing or misconfigured
- WELL-OPTIMIZED: most cost-saving features enabled and properly configured

Auto-termination applies ONLY to interactive (all-purpose) clusters. For JOB
clusters (`Cluster Type: JOB`) the lifecycle is bound to the run — the cluster
terminates automatically when the run ends. Treat auto-termination as
not applicable for JOB clusters: do NOT flag it as missing, do NOT recommend
enabling it, and do NOT factor it into the rating.

## Missing Data Protocol

1. No cost data -> analyze configuration only; note "no spend data available for $ impact estimates".
2. Partial configuration -> analyze available fields; list missing fields explicitly.

## Recommendations (max 3, ranked by estimated $ impact)

- Each MUST reference >= 1 specific configuration or cost metric from input.
- Each MUST include a dollar impact estimate when cost data is available.
- Without cost data: describe qualitative impact; state "dollar impact requires cost data".
- No duplicates. No filler.
- For JOB clusters, do NOT recommend enabling auto-termination — it is N/A by design.

## Output Format (IMMUTABLE — do not add, remove, or rename sections)

## 1. Overall Rating [CLASSIFICATION]
## 2. Right-Sizing Assessment
## 3. Cost Savings Opportunities (max 3, ranked by $ impact)
## 4. Idle Waste Risk
## 5. Configuration Gaps

## Section 4 — Idle Waste Risk

- For JOB clusters: write exactly "Not applicable — ephemeral job cluster
  terminates on run completion." and nothing else for this section.
- For interactive clusters: assess idle-waste risk using
  `Auto-termination` and runtime/utilisation signals.

## Formatting

- Currency: $ prefix, comma separators, 2 decimals (e.g., $1,234.56)
- Percentages: 1 decimal + % (e.g., 47.3%)
- Always include units ($/run, % of total, $/month)
- 2-4 bullet points per section"""


class LLMService:
    """Service for LLM-powered cost and configuration analysis."""

    def __init__(self) -> None:
        client_id = os.getenv("DATABRICKS_CLIENT_ID")
        host = os.getenv("DATABRICKS_HOST")
        token = os.getenv("DATABRICKS_TOKEN")

        if client_id:
            self.client = WorkspaceClient()
        elif host and token:
            self.client = WorkspaceClient(host=host, token=token)
        else:
            raise ValueError(
                "Either DATABRICKS_CLIENT_ID (for OAuth) or both "
                "DATABRICKS_HOST and DATABRICKS_TOKEN (for PAT) must be set"
            )
        self.model_name = "databricks-claude-sonnet-4"

    # ------------------------------------------------------------------
    # Public analysis methods
    # ------------------------------------------------------------------

    async def analyze_job_costs(
        self,
        job_id: str,
        run_id: str,
        cloud_cost: float,
        databricks_cost: float,
        total_cost: float,
        cluster_id: Optional[str] = None,
        usage_date: Optional[str] = None,
        job_name: Optional[str] = None,
        historical_stats: Optional[dict] = None,
    ) -> str:
        """Analyze job run costs using LLM with historical context.

        Args:
            job_id: The Databricks job ID.
            run_id: The job run ID.
            cloud_cost: Cloud infrastructure cost for this run.
            databricks_cost: Databricks platform cost for this run.
            total_cost: Total cost (cloud + databricks).
            cluster_id: Optional cluster ID (kept for signature compat).
            usage_date: Optional usage date (kept for signature compat).
            job_name: Human-readable job name.
            historical_stats: Pre-computed baseline from get_job_historical_stats.

        Returns:
            LLM-generated analysis, or structured fallback on failure.
        """
        try:
            user_message = self._build_job_user_message(
                job_id=job_id,
                cloud_cost=cloud_cost,
                databricks_cost=databricks_cost,
                total_cost=total_cost,
                job_name=job_name,
                historical_stats=historical_stats,
            )

            response = self.client.serving_endpoints.query(
                name=self.model_name,
                messages=[
                    ChatMessage(
                        role=ChatMessageRole.SYSTEM,
                        content=COST_ANALYSIS_SYSTEM_PROMPT,
                    ),
                    ChatMessage(
                        role=ChatMessageRole.USER,
                        content=user_message,
                    ),
                ],
                max_tokens=JOB_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )

            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content.strip()

            return self._build_job_fallback(cloud_cost, databricks_cost, total_cost)

        except Exception as e:
            logger.error("Error in LLM job cost analysis: %s", str(e))
            return self._build_job_fallback(cloud_cost, databricks_cost, total_cost)

    async def analyze_cluster_configuration(
        self,
        cluster_details: ClusterDetails,
        cost_summary: Optional[dict] = None,
    ) -> str:
        """Analyze cluster configuration using LLM with cost context.

        Args:
            cluster_details: Cluster config from system.compute.clusters.
            cost_summary: Pre-computed cost summary from get_cluster_cost_summary.

        Returns:
            LLM-generated analysis, or structured fallback on failure.
        """
        try:
            user_message = self._build_cluster_user_message(
                cluster_details, cost_summary
            )

            response = self.client.serving_endpoints.query(
                name=self.model_name,
                messages=[
                    ChatMessage(
                        role=ChatMessageRole.SYSTEM,
                        content=CLUSTER_ANALYSIS_SYSTEM_PROMPT,
                    ),
                    ChatMessage(
                        role=ChatMessageRole.USER,
                        content=user_message,
                    ),
                ],
                max_tokens=CLUSTER_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )

            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content.strip()

            return self._build_cluster_fallback(cluster_details, cost_summary)

        except Exception as e:
            logger.error("Error in LLM cluster analysis: %s", str(e))
            return self._build_cluster_fallback(cluster_details, cost_summary)

    # ------------------------------------------------------------------
    # User-message builders (data only — no instructions)
    # ------------------------------------------------------------------

    def _build_job_user_message(
        self,
        job_id: str,
        cloud_cost: float,
        databricks_cost: float,
        total_cost: float,
        job_name: Optional[str],
        historical_stats: Optional[dict],
    ) -> str:
        """Assemble the data-only USER message for job cost analysis."""
        cloud_pct = (cloud_cost / total_cost * 100) if total_cost > 0 else 0.0
        dbr_pct = (databricks_cost / total_cost * 100) if total_cost > 0 else 0.0
        label = job_name or f"Job {job_id}"

        lines: list[str] = [
            "## Current Run",
            f"- Job: {label}",
            f"- Total Cost: ${total_cost:,.2f}",
            f"- Cloud Cost: ${cloud_cost:,.2f} ({cloud_pct:.1f}%)",
            f"- Databricks Cost: ${databricks_cost:,.2f} ({dbr_pct:.1f}%)",
        ]

        if historical_stats is not None and historical_stats.get("total_runs", 0) > 0:
            self._append_historical_section(lines, historical_stats)
        elif historical_stats is not None:
            lines.extend(["", "## Historical Baseline"])
            lines.append("No historical data available for this job.")
        else:
            lines.extend(["", "## Historical Baseline"])
            lines.append("Historical data unavailable.")

        return "\n".join(lines)

    def _append_historical_section(
        self, lines: list[str], stats: dict
    ) -> None:
        """Append historical baseline and comparison sections to the message."""
        total_runs: int = stats.get("total_runs", 0)
        limited = stats.get("limited_history", False)
        limited_note = (
            f" [LIMITED — {total_runs} run{'s' if total_runs != 1 else ''}]"
            if limited else ""
        )
        data_start = stats.get("data_start", "N/A")
        data_end = stats.get("data_end", "N/A")

        def _fmt(val, suffix: str = "") -> str:
            if val is None:
                return "N/A"
            return f"${val:,.2f}{suffix}"

        avg_cost = stats.get("avg_cost")
        median_cost = stats.get("median_cost")
        p90_cost = stats.get("p90_cost")
        stddev_cost = stats.get("stddev_cost")
        min_cost = stats.get("min_cost")
        max_cost = stats.get("max_cost")
        avg_cloud_pct = stats.get("avg_cloud_pct")

        lines.append("")
        lines.append(
            f"## Historical Baseline "
            f"({total_runs} runs, {data_start} to {data_end}){limited_note}"
        )
        lines.append(
            f"- Avg: {_fmt(avg_cost, '/run')} | "
            f"Median: {_fmt(median_cost, '/run')}"
        )
        lines.append(
            f"- P90: {_fmt(p90_cost, '/run')} | "
            f"StdDev: {_fmt(stddev_cost)}"
        )
        lines.append(
            f"- Range: {_fmt(min_cost)} – {_fmt(max_cost)}"
        )
        cloud_pct_str = f"{avg_cloud_pct:.1f}%" if avg_cloud_pct is not None else "N/A"
        lines.append(
            f"- Avg Cloud Cost Share: {cloud_pct_str}"
        )

        comparison = stats.get("comparison")
        last_run_cost = stats.get("last_run_cost")

        if comparison is not None:
            lines.extend(["", "## Current vs Baseline"])
            lines.append(f"- Deviation: {comparison}")
            if last_run_cost is not None:
                lines.append(f"- Last Run Cost: ${last_run_cost:,.2f}")

    def _build_cluster_user_message(
        self,
        cluster: ClusterDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Assemble the data-only USER message for cluster analysis."""
        if cluster.min_autoscale_workers is not None:
            autoscale = (
                f"Autoscaling: {cluster.min_autoscale_workers}"
                f"–{cluster.max_autoscale_workers} workers"
            )
        elif cluster.worker_count is not None:
            autoscale = f"Fixed: {cluster.worker_count} workers"
        else:
            autoscale = "Not specified"

        auto_term = self._format_auto_termination(cluster)

        if cluster.enable_elastic_disk is not None:
            elastic = "Enabled" if cluster.enable_elastic_disk else "Disabled"
        else:
            elastic = "Not specified"

        provider_label, provider_availability, spot_bid_pct = (
            self._extract_provider_attributes(cluster)
        )

        cluster_type_line = self._format_cluster_type_line(cluster)

        lines: list[str] = [
            cluster_type_line,
            "",
            "## Cluster Configuration",
            f"- Driver: {cluster.driver_node_type or 'Not specified'}",
            f"- Worker: {cluster.worker_node_type or 'Not specified'}",
            f"- Scaling: {autoscale}",
            f"- Auto-termination: {auto_term}",
            f"- Elastic Disk: {elastic}",
            f"- DBR Version: {cluster.dbr_version or 'Not specified'}",
            f"- Security Mode: {cluster.data_security_mode or 'Not specified'}",
            f"- {provider_label} Availability: {provider_availability}",
            f"- Spot Bid: {spot_bid_pct}",
        ]

        tags_str = self._filter_tags(cluster.tags)
        lines.extend(["", "## Tags", tags_str])

        lines.append("")
        if cost_summary is not None and cost_summary.get("total_run_count", 0) > 0:
            lines.append(f"## Cost Summary ({LOOKBACK_DAYS}-day window)")
            lines.append(f"- Total Spend: ${cost_summary['total_spend']:,.2f}")
            lines.append(
                f"- Cloud: ${cost_summary['total_cloud_cost']:,.2f} "
                f"({cost_summary['cloud_pct']:.1f}%) | "
                f"Databricks: ${cost_summary['total_databricks_cost']:,.2f} "
                f"({cost_summary['databricks_pct']:.1f}%)"
            )
            lines.append(
                f"- Jobs: {cost_summary['distinct_job_count']} distinct | "
                f"Runs: {cost_summary['total_run_count']} total"
            )
            lines.append(
                f"- Avg Cost/Run: ${cost_summary['avg_cost_per_run']:,.2f}"
            )
            first = cost_summary.get("first_active_date", "N/A")
            last = cost_summary.get("last_active_date", "N/A")
            lines.append(f"- Active Period: {first} to {last}")
        elif cost_summary is not None:
            lines.append("## Cost Summary")
            lines.append("No cost data available for this cluster.")
        else:
            lines.append("## Cost Summary")
            lines.append("Cost data unavailable.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Structured fallbacks (never expose raw exceptions)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_job_fallback(
        cloud_cost: float,
        databricks_cost: float,
        total_cost: float,
    ) -> str:
        """Return structured fallback matching the normal LLM section format."""
        cloud_pct = (cloud_cost / total_cost * 100) if total_cost > 0 else 0.0
        dbr_pct = (databricks_cost / total_cost * 100) if total_cost > 0 else 0.0
        dominant = "Cloud" if cloud_pct >= dbr_pct else "Databricks"
        return (
            "## 1. Cost Assessment [DATA ONLY]\n"
            f"- Total Cost: ${total_cost:,.2f}\n"
            f"- Cloud Cost: ${cloud_cost:,.2f} ({cloud_pct:.1f}%)\n"
            f"- Databricks Cost: ${databricks_cost:,.2f} ({dbr_pct:.1f}%)\n"
            f"- Automated classification unavailable\n\n"
            "## 2. Cost Driver Analysis\n"
            f"- {dominant} costs represent the larger share at "
            f"{max(cloud_pct, dbr_pct):.1f}% of total spend\n"
            f"- Detailed analysis unavailable\n\n"
            "## 3. Optimization Opportunities\n"
            "- Automated recommendations unavailable\n\n"
            "## 4. Trend Signal\n"
            "- INSUFFICIENT DATA \u2014 automated analysis could not be generated"
        )

    @staticmethod
    def _build_cluster_fallback(
        cluster_details: ClusterDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Return structured fallback matching the normal LLM section format."""
        auto_term = LLMService._format_auto_termination(cluster_details)
        driver = cluster_details.driver_node_type or "N/A"
        worker = cluster_details.worker_node_type or "N/A"

        lines = [
            "## 1. Overall Rating [DATA ONLY]",
            f"- Driver: {driver}",
            f"- Worker: {worker}",
            f"- Auto-termination: {auto_term}",
            "- Automated classification unavailable",
            "",
            "## 2. Right-Sizing Assessment",
        ]
        if cost_summary and isinstance(cost_summary.get("total_spend"), (int, float)) and cost_summary["total_spend"] > 0:
            lines.append(f"- Total Spend: ${cost_summary['total_spend']:,.2f}")
            lines.append(f"- Runs: {cost_summary.get('total_run_count', 'N/A')}")
            lines.append(f"- Avg Cost/Run: ${cost_summary.get('avg_cost_per_run', 0):,.2f}")
        else:
            lines.append("- No cost data available for sizing assessment")
        lines.extend([
            "",
            "## 3. Cost Savings Opportunities",
            "- Automated recommendations unavailable",
            "",
            "## 4. Idle Waste Risk",
        ])
        if cluster_details.is_job_cluster:
            lines.append(
                "- Not applicable \u2014 ephemeral job cluster terminates "
                "on run completion."
            )
        else:
            lines.append(f"- Auto-termination: {auto_term}")
            lines.append("- Detailed analysis unavailable")
        lines.extend([
            "",
            "## 5. Configuration Gaps",
            "- Automated analysis could not be generated",
        ])
        return "\n".join(lines)

    @staticmethod
    def _format_auto_termination(cluster: ClusterDetails) -> str:
        """Render the auto-termination field for the LLM message and fallback.

        Job clusters have no idle-shutdown setting because Databricks tears them
        down when the run ends. Returning the literal string ``Disabled`` for
        them leads the model to flag a non-issue, so we render ``N/A
        (ephemeral job cluster, terminates on run end)`` instead.
        """
        if cluster.auto_termination_minutes is not None:
            return f"{cluster.auto_termination_minutes} minutes"
        if cluster.is_job_cluster:
            return "N/A (ephemeral job cluster, terminates on run end)"
        return "Disabled"

    @staticmethod
    def _format_cluster_type_line(cluster: ClusterDetails) -> str:
        """Render the cluster-type preamble shown before ## Cluster Configuration."""
        if cluster.is_job_cluster:
            return (
                "Cluster Type: JOB cluster "
                "(ephemeral, lifecycle-bound to the run — auto-termination N/A)"
            )
        if cluster.cluster_source:
            return (
                f"Cluster Type: {cluster.cluster_source} cluster "
                "(interactive — auto-termination applies)"
            )
        return "Cluster Type: Unknown (cluster_source unavailable)"

    @staticmethod
    def _extract_provider_attributes(
        cluster: ClusterDetails,
    ) -> tuple[str, str, str]:
        """Pick the populated provider-attributes block and read availability/spot keys.

        Returns:
            (provider_label, availability, spot_bid_pct_str) triple. Falls back
            to the configured platform's display name if no attributes block
            is populated on this cluster row.
        """
        availability = "Not specified"
        spot_bid_pct = "Not specified"
        provider_label = cloud_config.platform_display_name

        if cluster.aws_attributes:
            provider_label = "AWS"
            availability = cluster.aws_attributes.get(
                "availability", "Not specified"
            )
            spot_bid = cluster.aws_attributes.get("spot_bid_price_percent")
            if spot_bid is not None:
                spot_bid_pct = f"{spot_bid}%"
        elif cluster.azure_attributes:
            provider_label = "Azure"
            availability = cluster.azure_attributes.get(
                "availability", "Not specified"
            )
            spot_bid = cluster.azure_attributes.get("spot_bid_max_price")
            if spot_bid is not None:
                spot_bid_pct = f"{spot_bid}"
        elif cluster.gcp_attributes:
            provider_label = "GCP"
            availability = cluster.gcp_attributes.get(
                "availability", "Not specified"
            )

        return provider_label, availability, spot_bid_pct

    @staticmethod
    def _filter_tags(tags: Optional[dict]) -> str:
        """Serialize tags, excluding keys starting with 'databricks' (case-insensitive)."""
        if not tags:
            return "No tags"
        filtered = {
            k: v for k, v in tags.items()
            if not k.lower().startswith("databricks")
        }
        if not filtered:
            return "No user-defined tags"
        lines: list[str] = []
        for k, v in filtered.items():
            val = v if isinstance(v, str) else json.dumps(v)
            lines.append(f"- {k}: {val}")
        return "\n".join(lines)

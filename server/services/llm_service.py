import json
import logging
import os
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from server.config.cloud_platform import cloud_config
from server.models.job_spend import (
    ClusterDetails,
    InstancePoolDetails,
    PipelineDetails,
    SqlWarehouseDetails,
)
from server.services.databricks_service import LOOKBACK_DAYS

logger = logging.getLogger(__name__)

# --- Model parameters ---
# Single source of truth for the foundation model the app calls. The UI reads
# the human-readable label from /api/ai-info instead of hard-coding it, so
# swapping the model here updates every "Powered by ..." badge automatically.
DEFAULT_MODEL_NAME = 'databricks-claude-sonnet-4'


def model_display_label(model_name: str) -> str:
    """Turn a serving-endpoint name into a UI label.

    e.g. ``databricks-claude-sonnet-4`` -> ``Claude Sonnet 4``.
    """
    name = model_name
    if name.startswith('databricks-'):
        name = name[len('databricks-') :]
    return ' '.join(part.capitalize() for part in name.split('-') if part)


LLM_TEMPERATURE = 0.2
JOB_MAX_TOKENS = 600
CLUSTER_MAX_TOKENS = 700
INSTANCE_POOL_MAX_TOKENS = 800
PIPELINE_MAX_TOKENS = 800
SQL_WAREHOUSE_MAX_TOKENS = 800

# Auto-stop threshold above which idle DBU waste becomes a reportable cost
# signal (plan §6a). Below it, a warm warehouse is normal interactive-latency
# tuning rather than waste.
SQL_WAREHOUSE_AUTO_STOP_THRESHOLD_MINS = 30

# Mandatory v1 honesty string for DBU-only (classic/mixed) pipeline spend. The
# prompt MUST include it whenever `cost_basis != 'full'` and the structured
# fallback embeds it too, so plan §9 acceptance criterion #14 / CP7 exit
# criterion #4 hold even on LLM failure (plan §3.2 / §4.1).
PIPELINE_DBU_ONLY_CAVEAT = (
    "Databricks DBU cost only — excludes cloud VM cost"
)

# Mandatory honesty string for instance-pool analysis. As of CP8
# (plan_pool_pipeline_ec2_cost.md §4.4) pool EC2/EBS cost — idle + active
# combined — IS joined into the cost summary, so dollar estimates may use total
# cost. The one remaining gap is the idle-vs-active split (deferred to §4.5 via
# `system.compute.instance_events`), so idle-specific VM waste cannot be
# quantified. The prompt MANDATES this phrase and the fallback embeds it too.
POOL_IDLE_SPLIT_CAVEAT = (
    "the idle-vs-active VM cost split is not available yet"
)

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
7. Analysis depth is INDEPENDENT of absolute cost amount. A $0.10 run with a
   full baseline gets the same treatment as a $1,000 run. Never abbreviate or
   skip sections because the absolute dollar amount is small.
8. The `BASELINE_AVAILABLE:` tag inside the Historical Baseline section is
   authoritative. If it reads `YES`, a baseline IS present — you MUST use it
   and you MUST NOT claim "no historical data" or "INSUFFICIENT DATA" in any
   section.
9. NEVER cite industry-average savings percentages (e.g. "spot saves 60-80%")
   or invent annualized dollar ranges not derived from the input numbers.
10. Do NOT recommend "maintain current configuration" or similar non-actions
    as an optimization.

## Classification Rubric (RELATIVE — no absolute dollar thresholds)

Use the MEDIAN as the primary reference (robust to outliers). Avg is secondary.
- CRITICAL: current run >= 2x historical median OR >= P90 threshold
- WARNING: current run 1.3x-2x historical median
- NORMAL: within +/-30% of historical median
- EFFICIENT: below median AND below avg
- BASELINE_AVAILABLE: NO -> classify on available cost signals only;
  state "no baseline available"

## Missing Data Protocol

1. BASELINE_AVAILABLE: NO -> skip baseline comparisons; analyze absolute metrics only.
2. BASELINE_AVAILABLE: YES with < 3 successful runs -> include stats but state
   "limited history (N runs) — trends unreliable".
3. BASELINE_AVAILABLE: YES with >= 3 successful runs -> perform full trend
   analysis. Saying "INSUFFICIENT DATA" or "no historical runs available" is
   FORBIDDEN in this case.
4. Partial data -> analyze available fields; list missing fields explicitly.

## Recommendations (max 3, ranked by estimated $ impact)

- Each MUST reference >= 1 specific metric from input.
- Each MUST include a dollar impact estimate derived from input numbers, or
  state "impact not quantifiable from available data".
- With sufficient data: show calculation (e.g., "reducing X from $Y to $Z saves ~$A/run x B runs = ~$C/month").
- If classification is EFFICIENT or NORMAL and no concrete lever exists, write
  exactly: "No actionable optimizations identified" plus one short reason.
- No duplicates. No filler.

## Output Format (IMMUTABLE — do not add, remove, or rename sections)

## 1. Cost Assessment [CLASSIFICATION]
## 2. Cost Driver Analysis
## 3. Optimization Opportunities (max 3, ranked by $ impact)
## 4. Trend Signal

## Trend Signal

- Compare current run to historical median (primary) and last successful run.
- Direction: INCREASING / DECREASING / STABLE / INSUFFICIENT DATA
- Include magnitude: e.g., "Cost increased 23.4% vs historical median of $X"
- ONLY use "INSUFFICIENT DATA" when BASELINE_AVAILABLE: NO, or when
  BASELINE_AVAILABLE: YES but successful run count < 3.

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
7. NEVER cite industry-average savings percentages (e.g. "spot saves 60-80%")
   or invent annualized dollar ranges not derived from the input Cost Summary.
8. Configuration Gaps: ONLY list gaps that directly drive cost (autoscaling,
   auto-termination on interactive clusters, availability/spot mode). Do NOT
   list missing tags, governance labels, or chargeback/tracking concerns.
9. If rating is WELL-OPTIMIZED and no concrete lever exists, section 3 must be
   exactly "No actionable optimizations identified" plus one short reason.

## Classification Rubric

Evaluate based on autoscaling, spot usage, and auto-termination configuration:
- CRITICAL ISSUES: only when a concrete cost-driving misconfig is present
  (e.g. auto-termination disabled on interactive with material spend, or
  clearly oversized fixed workers with high avg cost/run). High absolute
  spend alone is NOT CRITICAL.
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
- Dollar impact MUST be derived from input Cost Summary numbers, or state
  "impact not quantifiable from available data" / "dollar impact requires cost data".
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

## Section 5 — Configuration Gaps

- Omit this section's bullets entirely when there are no cost-driving gaps;
  write exactly: "None — no cost-driving configuration gaps identified."
- Missing tags alone must never appear here.

## Formatting

- Currency: $ prefix, comma separators, 2 decimals (e.g., $1,234.56)
- Percentages: 1 decimal + % (e.g., 47.3%)
- Always include units ($/run, % of total, $/month)
- 2-4 bullet points per section"""

INSTANCE_POOL_ANALYSIS_PROMPT = """\
You are a senior FinOps analyst specializing in Databricks instance-pool \
optimization. You are analytical, precise, and produce zero fluff. Every word \
must earn its place.

## Strict Rules

1. Every cost-related claim MUST cite a specific number from the input data.
2. Configuration observations may be qualitative but must be directly supported by input data.
3. Do NOT infer, estimate, or assume values not present in the data.
4. If data is insufficient for an assessment, state: "Insufficient data for this assessment"
5. If no optimization exists, state: "No actionable optimizations identified" and briefly explain why.
6. NEVER fabricate cost estimates or reference external benchmarks.
7. **Cloud-cost scope (MANDATORY).** Pool EC2/EBS VM cost (idle + active
   combined) IS included in the cost summary below as the cloud cost line, so
   dollar-impact estimates MAY use total cost (DBU + EC2/EBS). The one gap is
   that the idle-vs-active VM cost split is not available yet — the cost
   cannot be separated into "wasted idle capacity" vs "actively used"
   dollars. You MUST include the exact phrase "the idle-vs-active VM cost
   split is not available yet" at least once in your output, as a standalone
   caveat bullet under Configuration Gaps or as a parenthetical inside any
   recommendation that touches idle capacity. Do not fabricate an
   idle-specific savings figure.
8. NEVER cite industry-average savings percentages or invent annualized dollar
   ranges not derived from the input Cost Summary.
9. Configuration Gaps (besides the mandatory idle-split caveat): ONLY list
   cost-driving gaps (`min_idle` vs peak, autotermination). Do NOT list
   missing tags or chargeback/tracking concerns.

## Classification Rubric

Evaluate based on idle-instance configuration, autotermination tuning, and the
ratio of distinct attached clusters to active days:
- CRITICAL ISSUES: major inefficiencies (e.g. `min_idle_instances` >> peak
  concurrent attachment, autotermination disabled/excessive on a low-traffic
  pool). High absolute spend alone is NOT CRITICAL.
- NEEDS ATTENTION: partially tuned; one or more knobs misaligned with
  observed workload
- WELL-OPTIMIZED: idle-instance count and autotermination minutes are
  proportionate to observed peak concurrent attached clusters and active-day
  density

## Pool-Specific Signals

- `min_idle_instances` vs `peak_concurrent_clusters` — if min idle persistently
  exceeds peak attachment, the pool is paying to keep warm capacity that is
  never claimed. Quantify the over-provisioning in instances and reference the
  total cost; note the idle-vs-active VM cost split is not available yet, so
  the idle-specific dollar waste cannot be isolated.
- `idle_instance_autotermination_minutes` — long values keep VMs warm
  unnecessarily for sporadic workloads; short values defeat the point of
  pooling under bursty workloads. Cross-reference with `active_days` and
  cluster-fanout.
- `node_type` appropriateness — assess in terms of cluster fanout (high
  distinct-cluster count per active day suggests many short-lived job
  clusters) but acknowledge you don't have per-cluster SKU mix.
- Ratio `distinct_cluster_count / active_days` — high fanout (>10/day on
  average) is a strong signal that the pool is shared substrate for job
  clusters; recommend keeping autotermination low to maximize VM reuse.
- `pool_overhead_rows` — non-zero means some DBU is billed at the pool
  level with no attributable cluster_id (`__pool_overhead__` bucket per
  plan §3.3); call out as accounting noise if it dominates total spend.

## Missing Data Protocol

1. No cost data -> analyze configuration only; note "no spend data available for $ impact estimates".
2. Snapshot missing (`pool_snapshot_missing=true`) -> configuration analysis is
   disabled; report only on cost shape and recommend re-creating the pool with
   tracked metadata if continued use is expected.
3. Partial configuration -> analyze available fields; list missing fields explicitly.

## Recommendations (max 3, ranked by estimated $ impact)

- Each MUST reference >= 1 specific configuration or cost metric from input.
- Dollar impact MUST be derived from input Cost Summary numbers (total cost
  MAY be used); do NOT fabricate idle-specific VM savings (the idle-vs-active
  split is not available yet). If impact cannot be quantified, say so.
- Without cost data: describe qualitative impact; state "dollar impact requires cost data".
- No duplicates. No filler.

## Output Format (IMMUTABLE — do not add, remove, or rename sections)

## 1. Overall Rating [CLASSIFICATION]
## 2. Right-Sizing Assessment
## 3. Cost Savings Opportunities (max 3, ranked by $ impact)
## 4. Idle Waste Risk
## 5. Configuration Gaps

## Section 4 — Idle Waste Risk

- Assess using `min_idle_instances`, `idle_instance_autotermination_minutes`,
  `peak_concurrent_clusters`, and `active_days`. Always conclude this section
  with an explicit reminder that the idle-vs-active VM cost split is not
  available yet, so idle waste cannot be quantified in dollars.

## Formatting

- Currency: $ prefix, comma separators, 2 decimals (e.g., $1,234.56)
- Percentages: 1 decimal + % (e.g., 47.3%)
- Always include units ($/day, % of total, $/month)
- 2-4 bullet points per section"""

PIPELINE_ANALYSIS_PROMPT = """\
You are a senior FinOps analyst specializing in Databricks declarative / \
serverless pipeline compute (Lakeflow Declarative Pipelines, DBSQL \
materialized views & streaming tables, online tables, vector search, model \
serving, AI functions). You are analytical, precise, and produce zero fluff. \
Every word must earn its place.

## Scope Note (read first)

This tab covers ALL `usage_metadata.dlt_pipeline_id` spend — it is NOT
DLT-only. The `Workload Type` field tells you what this pipeline actually is
(e.g. DBSQL Materialized View, Online Table, Vector Search). Tailor your
analysis to that workload; do NOT assume it is a DLT pipeline.

## Strict Rules

1. Every cost-related claim MUST cite a specific number from the input data.
2. Configuration observations may be qualitative but must be directly supported by input data.
3. Do NOT infer, estimate, or assume values not present in the data.
4. If data is insufficient for an assessment, state: "Insufficient data for this assessment"
5. If no optimization exists, state: "No actionable optimizations identified" and briefly explain why.
6. NEVER fabricate cost estimates or reference external benchmarks.
7. **Cost-basis honesty (MANDATORY, conditional).** The input carries a
   `Cost Basis` field:
   - `full` (serverless): the DBU rate already bundles infrastructure, so the
     figure IS the complete cost. Do NOT add a cloud-VM caveat and do NOT
     recommend cloud-VM / instance-type changes — there is no separate VM line.
   - `dbu_only` (classic) or `partial` (mixed): the figure EXCLUDES separate
     cloud VM cost. You MUST include the exact phrase
     "excludes cloud VM cost" at least once (as a standalone caveat bullet
     under Configuration Gaps or as a parenthetical inside any recommendation),
     all dollar-impact estimates MUST be treated as DBU-only, and you MUST NOT
     invent cloud-VM savings figures.
8. NEVER cite industry-average savings percentages or invent annualized dollar
   ranges not derived from the input Cost Summary.
9. Do NOT recommend changing refresh/schedule/trigger frequency unless schedule
   or trigger fields appear in the input. Without them, limit cadence comments
   to observed active-day density and spend/day.
10. Configuration Gaps: ONLY cost-driving or mandatory cost-basis caveats.
    Do NOT list missing tags or chargeback/tracking concerns.

## Classification Rubric

Evaluate based on spend concentration, active-day density, and workload type:
- CRITICAL ISSUES: only when spend/day and active-day density show a clear
  waste signal in the input. High absolute spend alone is NOT CRITICAL.
- NEEDS ATTENTION: partially optimizable; cadence or compute mode worth review.
- WELL-OPTIMIZED: spend proportionate to active days and workload type with no
  obvious waste signal.

## Pipeline-Specific Signals

- `Compute Mode` (serverless / classic / mixed) — serverless cost is complete;
  classic carries an invisible-in-v1 cloud VM line (see rule 7).
- Spend per active day (`Total Spend / Active Days`) — high per-day cost on a
  materialized view suggests an aggressive refresh cadence.
- `Distinct Workload Types` > 1 — the pipeline_id spans multiple products;
  note that the badge reflects the cost-dominant one.
- Metadata-missing (`Metadata Available: No`) — configuration analysis is
  limited; report on cost shape only and note metadata is unavailable.

## Missing Data Protocol

1. No cost data -> analyze configuration only; note "no spend data available for $ impact estimates".
2. Metadata missing -> configuration analysis disabled; report on cost shape only.
3. Partial configuration -> analyze available fields; list missing fields explicitly.

## Recommendations (max 3, ranked by estimated $ impact)

- Each MUST reference >= 1 specific configuration or cost metric from input.
- Dollar impact MUST be derived from input numbers, or state impact is not
  quantifiable. For `dbu_only` / `partial`: estimates are DBU-only.
- For `full` (serverless): do NOT recommend cloud-VM / node-type changes.
- Without cost data: describe qualitative impact; state "dollar impact requires cost data".
- No duplicates. No filler.

## Output Format (IMMUTABLE — do not add, remove, or rename sections)

## 1. Overall Rating [CLASSIFICATION]
## 2. Right-Sizing Assessment
## 3. Cost Savings Opportunities (max 3, ranked by $ impact)
## 4. Idle Waste Risk
## 5. Configuration Gaps

## Section 4 — Idle Waste Risk

- For serverless workloads: assess refresh / run cadence vs active-day density;
  there is no idle VM to waste, so frame this as "scheduling efficiency".
- For classic / mixed workloads: assess idle compute and conclude with the
  reminder that cloud VM cost (and any idle VM waste) is not visible in v1.

## Section 5 — Configuration Gaps

- Omit filler; if no cost-driving gaps (and no mandatory cost-basis caveat),
  write exactly: "None — no cost-driving configuration gaps identified."

## Formatting

- Currency: $ prefix, comma separators, 2 decimals (e.g., $1,234.56)
- Percentages: 1 decimal + % (e.g., 47.3%)
- Always include units ($/day, % of total, $/month)
- 2-4 bullet points per section"""

SQL_WAREHOUSE_ANALYSIS_PROMPT = """\
You are a senior FinOps analyst specializing in Databricks SQL Warehouse \
optimization (Classic, Pro, and Serverless SQL). You are analytical, precise, \
and produce zero fluff. Every word must earn its place.

## Cost Model (read first)

All three SQL Warehouse types run on Databricks-managed compute. There are NO
customer-visible cloud VMs and no separate cloud infrastructure line — the DBU
figure IS the complete cost. Therefore:

- Do NOT add a cloud-VM or cloud-infrastructure caveat of any kind, and do NOT
  imply the reported spend is partial, DBU-only, or missing a cost component.
- Do NOT recommend instance-type, node-type, spot, or VM-level changes — no
  such knob exists for SQL Warehouses.
- Every optimization lever is a DBU lever: warehouse size, cluster scaling
  range, auto-stop tuning, and query efficiency.

## Strict Rules

1. Every cost-related claim MUST cite a specific number from the input data.
2. Configuration observations may be qualitative but must be directly supported by input data.
3. Do NOT infer, estimate, or assume values not present in the data.
4. If data is insufficient for an assessment, state: "Insufficient data for this assessment"
5. If no optimization exists, state: "No actionable optimizations identified" and briefly explain why.
6. NEVER fabricate cost estimates or reference external benchmarks.
7. NEVER cite industry-average savings percentages (e.g. "auto-stop saves
   30-50%") or invent annualized dollar ranges not derived from the input
   Cost Summary.
8. Do NOT comment on query text, table layout, Z-ORDER, or partitioning
   specifics — no query-level telemetry is in the input. Query-efficiency
   advice must stay at the level the data supports.
9. Configuration Gaps: ONLY list gaps that directly drive DBU cost (auto-stop
   timeout, warehouse size vs spend shape, min/max cluster range). Do NOT list
   missing tags, governance labels, or chargeback/tracking concerns.
10. Do NOT recommend "maintain current configuration" or similar non-actions.

## Classification Rubric

Evaluate on auto-stop tuning, size/scaling configuration, and spend shape
(spend per active day vs active-day density):
- CRITICAL ISSUES: a concrete cost-driving misconfiguration is present (e.g.
  auto-stop disabled, or a long auto-stop on a warehouse active on few days).
  High absolute spend alone is NOT CRITICAL.
- NEEDS ATTENTION: partially tuned; one or more knobs misaligned with the
  observed spend shape.
- WELL-OPTIMIZED: auto-stop, size, and cluster range are proportionate to the
  observed spend and active-day density.

## Warehouse-Type Tailoring (MANDATORY — use the `Warehouse Type` field)

- SERVERLESS: compute starts in seconds and stops automatically, so sizing and
  auto-stop have limited leverage. Focus on DBU consumed per active day and
  query-side efficiency: result-cache and Delta-cache reuse, avoiding repeated
  full scans, predicate pushdown / filter selectivity, and reducing query
  complexity and redundant refreshes. Do NOT recommend cluster-count changes
  as the primary lever.
- PRO: focus on warehouse size right-sizing, auto-stop tuning, and the
  `min_clusters` / `max_clusters` scaling range. A `min_clusters` above 1 keeps
  paid capacity warm continuously — quantify against total spend and active
  days. Query-efficiency levers apply secondarily.
- CLASSIC: same levers as Pro, AND note that Classic lacks the Pro/Serverless
  query-performance features, so migrating to Pro or Serverless may reduce DBU
  for the same workload. Frame this as a directional option, not a quantified
  saving, unless the input numbers support a figure.
- Unknown type: analyze auto-stop and spend shape only; state that
  type-specific recommendations require the warehouse type.

## Auto-Stop Analysis (warehouse-specific signal)

- `Auto-Stop` above 30 minutes is a cost signal: the warehouse bills DBU while
  idle waiting for the timeout. Flag it explicitly, tie it to the observed
  spend per active day, and recommend a shorter timeout.
- `Auto-Stop: Disabled` (or 0) means the warehouse never stops on its own —
  treat as the strongest idle-waste signal available.
- Very short auto-stop values trade idle DBU for cold-start latency on the
  next query. Mention that trade-off when recommending a reduction; do not
  recommend a value below 5 minutes.
- Cross-reference auto-stop against `Active Days` — a long timeout on a
  warehouse that is active on few days wastes proportionally more.

## Missing Data Protocol

1. No cost data -> analyze configuration only; note "no spend data available for $ impact estimates".
2. Metadata missing (`Metadata Available: No`) -> configuration analysis is
   disabled; report on cost shape only and say metadata is unavailable.
3. Partial configuration -> analyze available fields; list missing fields explicitly.

## Output Format (IMMUTABLE — do not add, remove, or rename sections)

## 1. Overall Rating [CLASSIFICATION]
## 2. Right-Sizing Assessment
## 3. Cost Optimization
## 4. Configuration Gaps
## 5. Recommendations (max 3, ranked by $ impact)

## Section 2 — Right-Sizing Assessment

- Assess `Warehouse Size` and the `min_clusters` / `max_clusters` range against
  total spend, active days, and avg cost per active day.
- For SERVERLESS: state that size and cluster range are managed, and assess
  DBU consumed per active day instead.

## Section 3 — Cost Optimization

- Identify where the DBU is going and which levers exist, per the
  warehouse-type tailoring above. Include the auto-stop assessment here.
- State explicitly that DBU is the complete cost for this warehouse — there is
  no separate cloud component to optimize.

## Section 4 — Configuration Gaps

- Omit filler; if no cost-driving gaps exist, write exactly:
  "None — no cost-driving configuration gaps identified."

## Section 5 — Recommendations

- Max 3, ranked by estimated $ impact. No duplicates.
- Each MUST reference >= 1 specific configuration or cost metric from input.
- Dollar impact MUST be derived from input Cost Summary numbers, or state
  "impact not quantifiable from available data" / "dollar impact requires cost data".
- If the rating is WELL-OPTIMIZED and no concrete lever exists, write exactly
  "No actionable optimizations identified" plus one short reason.

## Formatting

- Currency: $ prefix, comma separators, 2 decimals (e.g., $1,234.56)
- Percentages: 1 decimal + % (e.g., 47.3%)
- Always include units ($/day, % of total, $/month)
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
        self.model_name = DEFAULT_MODEL_NAME

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

    async def analyze_instance_pool_costs(
        self,
        pool_details: InstancePoolDetails,
        cost_summary: Optional[dict] = None,
    ) -> str:
        """Analyze instance-pool configuration + cost shape via LLM.

        Sibling of ``analyze_cluster_configuration`` but bound to
        ``INSTANCE_POOL_ANALYSIS_PROMPT`` and the pool-specific
        signals plan §CP7 calls out (idle config vs observed peak
        concurrent attachment, autotermination tuning, cluster-fanout
        ratio). As of CP8 (plan_pool_pipeline_ec2_cost.md §4.4) pool EC2/EBS
        cost is in the cost summary, so the prompt MANDATES the remaining
        ``POOL_IDLE_SPLIT_CAVEAT`` (idle-vs-active split not available yet)
        rather than the old "DBU-only" caveat.

        Args:
            pool_details: Pool snapshot + REST-resolved creator GUID
                from ``DatabricksService.get_instance_pool_details``.
            cost_summary: Pre-computed cost shape from
                ``DatabricksService.get_pool_cost_summary``. ``None``
                renders the "no cost data" branch of the prompt.

        Returns:
            LLM-generated analysis text, or a structured fallback on
            failure (the fallback also carries the idle-split caveat so the
            honesty guarantee holds even on error).
        """
        try:
            user_message = self._build_pool_user_message(
                pool_details, cost_summary
            )

            response = self.client.serving_endpoints.query(
                name=self.model_name,
                messages=[
                    ChatMessage(
                        role=ChatMessageRole.SYSTEM,
                        content=INSTANCE_POOL_ANALYSIS_PROMPT,
                    ),
                    ChatMessage(
                        role=ChatMessageRole.USER,
                        content=user_message,
                    ),
                ],
                max_tokens=INSTANCE_POOL_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )

            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content.strip()

            return self._build_pool_fallback(pool_details, cost_summary)

        except Exception as e:
            logger.error("Error in LLM instance-pool analysis: %s", str(e))
            return self._build_pool_fallback(pool_details, cost_summary)

    async def analyze_pipeline_costs(
        self,
        pipeline_details: PipelineDetails,
        cost_summary: Optional[dict] = None,
    ) -> str:
        """Analyze declarative-pipeline cost shape + workload via LLM.

        Sibling of ``analyze_instance_pool_costs`` but bound to
        ``PIPELINE_ANALYSIS_PROMPT``. The single prompt handles every workload
        type (DLT / DBSQL MV / online table / vector search / ...) with no
        per-product branching (plan §4.1 bug-surface control); the model
        tailors itself off the ``Workload Type`` field in the message.

        The ``Cost Basis`` context is the correctness-critical input: the
        prompt MUST add the DBU-only caveat (``excludes cloud VM cost``) when
        ``cost_basis != 'full'`` and MUST NOT add it for serverless
        (``full``) pipelines (plan §3.2 / CP7 exit criterion #4 / §9 #14).
        The structured fallback honours the same conditional so the invariant
        holds on LLM failure.

        Args:
            pipeline_details: Snapshot + dimensions from
                ``DatabricksService.get_pipeline_details``.
            cost_summary: Pre-computed cost shape from
                ``DatabricksService.get_pipeline_cost_summary``. ``None``
                renders the "no cost data" branch of the prompt.

        Returns:
            LLM-generated analysis text, or a structured fallback on failure.
        """
        try:
            user_message = self._build_pipeline_user_message(
                pipeline_details, cost_summary
            )

            response = self.client.serving_endpoints.query(
                name=self.model_name,
                messages=[
                    ChatMessage(
                        role=ChatMessageRole.SYSTEM,
                        content=PIPELINE_ANALYSIS_PROMPT,
                    ),
                    ChatMessage(
                        role=ChatMessageRole.USER,
                        content=user_message,
                    ),
                ],
                max_tokens=PIPELINE_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )

            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content.strip()

            return self._build_pipeline_fallback(pipeline_details, cost_summary)

        except Exception as e:
            logger.error("Error in LLM pipeline analysis: %s", str(e))
            return self._build_pipeline_fallback(pipeline_details, cost_summary)

    async def analyze_sql_warehouse_costs(
        self,
        warehouse_details: SqlWarehouseDetails,
        cost_summary: Optional[dict] = None,
    ) -> str:
        """Analyze SQL warehouse cost shape + configuration via LLM.

        Sibling of ``analyze_pipeline_costs`` but bound to
        ``SQL_WAREHOUSE_ANALYSIS_PROMPT``. The single prompt covers all three
        warehouse types (Classic / Pro / Serverless) and tailors itself off the
        ``Warehouse Type`` field rather than branching per type.

        DBU is the complete cost for managed-compute warehouses (plan Q4), so
        unlike Pipeline there is no cost gap to disclaim: the prompt forbids a
        cloud-VM caveat and forbids VM-level recommendations, since no such
        knob exists. The warehouse-specific angle is instead auto-stop tuning
        (``auto_stop_mins`` above
        ``SQL_WAREHOUSE_AUTO_STOP_THRESHOLD_MINS`` is idle DBU waste).

        Args:
            warehouse_details: Config snapshot from
                ``DatabricksService.get_sql_warehouse_details``.
            cost_summary: Pre-computed cost shape from
                ``DatabricksService.get_sql_warehouse_cost_summary``. ``None``
                renders the "no cost data" branch of the prompt.

        Returns:
            LLM-generated analysis text, or a structured fallback on failure.
        """
        try:
            user_message = self._build_sql_warehouse_user_message(
                warehouse_details, cost_summary
            )

            response = self.client.serving_endpoints.query(
                name=self.model_name,
                messages=[
                    ChatMessage(
                        role=ChatMessageRole.SYSTEM,
                        content=SQL_WAREHOUSE_ANALYSIS_PROMPT,
                    ),
                    ChatMessage(
                        role=ChatMessageRole.USER,
                        content=user_message,
                    ),
                ],
                max_tokens=SQL_WAREHOUSE_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )

            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content.strip()

            return self._build_sql_warehouse_fallback(
                warehouse_details, cost_summary
            )

        except Exception as e:
            logger.error("Error in LLM SQL warehouse analysis: %s", str(e))
            return self._build_sql_warehouse_fallback(
                warehouse_details, cost_summary
            )

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
            lines.append("BASELINE_AVAILABLE: NO")
            lines.append("No successful historical runs available for this job.")
            total_unfiltered = historical_stats.get("total_runs_unfiltered", 0)
            if total_unfiltered > 0:
                lines.append(
                    f"- {total_unfiltered} run(s) found in the lookback window, "
                    f"but none completed successfully."
                )
            current_state = historical_stats.get("current_run_state")
            if current_state and current_state != "SUCCEEDED":
                state_label = current_state.replace("_", " ").title()
                lines.append(f"- Current run state: {state_label}.")
        else:
            lines.extend(["", "## Historical Baseline"])
            lines.append("BASELINE_AVAILABLE: NO")
            lines.append("Historical data unavailable.")

        return "\n".join(lines)

    def _append_historical_section(
        self, lines: list[str], stats: dict
    ) -> None:
        """Append historical baseline and comparison sections to the message."""
        total_runs: int = stats.get("total_runs", 0)
        total_runs_unfiltered: int = stats.get(
            "total_runs_unfiltered", total_runs
        )
        confidence_tier: str = stats.get("confidence_tier", "none")
        state_filter_applied: bool = stats.get("state_filter_applied", False)
        current_run_state = stats.get("current_run_state")
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

        # Header reflects which runs are in the baseline and how confident
        # the trend is. The LLM uses this to calibrate its language
        # ("high confidence" trend vs. "indicative" vs. "not enough data").
        if state_filter_applied:
            scope = f"{total_runs} successful runs"
            if total_runs_unfiltered > total_runs:
                excluded = total_runs_unfiltered - total_runs
                scope += (
                    f"; {excluded} non-successful run"
                    f"{'s' if excluded != 1 else ''} excluded"
                )
        else:
            scope = f"{total_runs} runs (cancelled/failed included)"

        tier_note = {
            "high": "[HIGH CONFIDENCE]",
            "emerging": "[EMERGING TREND]",
            "limited": "[LIMITED HISTORY]",
            "none": "[INSUFFICIENT HISTORY]",
        }.get(confidence_tier, "")

        lines.append("")
        lines.append(
            f"## Historical Baseline ({scope}, {data_start} to {data_end}) "
            f"{tier_note}".rstrip()
        )
        # Explicit, unmissable tag — the system prompt is bound to this token.
        # When this reads YES, the LLM MUST perform full trend analysis.
        lines.append(
            f"BASELINE_AVAILABLE: YES ({total_runs} successful run"
            f"{'s' if total_runs != 1 else ''})"
        )

        if not state_filter_applied:
            lines.append(
                "- NOTE: `system.lakeflow.job_run_timeline` is not accessible, "
                "so cancelled/failed runs may be skewing this baseline. "
                "Grant SELECT on that table for accurate trends."
            )

        lines.append(
            f"- Median: {_fmt(median_cost, '/run')} | "
            f"Avg: {_fmt(avg_cost, '/run')}"
        )
        lines.append(
            f"- P90: {_fmt(p90_cost, '/run')} | "
            f"StdDev: {_fmt(stddev_cost)}"
        )
        lines.append(
            f"- Range: {_fmt(min_cost)} – {_fmt(max_cost)}"
        )
        cloud_pct_str = (
            f"{avg_cloud_pct:.1f}%" if avg_cloud_pct is not None else "N/A"
        )
        lines.append(
            f"- Avg Cloud Cost Share: {cloud_pct_str}"
        )

        comparison = stats.get("comparison")
        last_run_cost = stats.get("last_run_cost")

        lines.extend(["", "## Current vs Baseline"])
        if current_run_state and current_run_state != "SUCCEEDED":
            # The current run didn't complete cleanly; a deviation % is
            # meaningless. Surface the state so the LLM can call it out.
            state_label = current_run_state.replace("_", " ").title()
            lines.append(
                f"- Current run state: {state_label} "
                f"(comparison vs baseline skipped — partial cost not "
                f"comparable to successful runs)."
            )
        elif comparison is not None:
            ref = stats.get("comparison_reference", "median")
            lines.append(f"- Deviation vs {ref}: {comparison}")
        elif confidence_tier == "none":
            lines.append(
                "- Not enough successful runs in the lookback window to "
                "compute a reliable deviation."
            )
        else:
            lines.append("- Deviation: not available.")

        if last_run_cost is not None:
            lines.append(f"- Last Successful Run Cost: ${last_run_cost:,.2f}")

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

    def _build_pool_user_message(
        self,
        pool: InstancePoolDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Assemble the data-only USER message for instance-pool analysis.

        Renders the pool config block, the v1 attribution preamble (snapshot
        state + creator GUID rendering rules from plan §3.4 / §3.5), and the
        cost shape over the configured lookback window. The system prompt's
        v1 cloud-cost caveat is restated as a `Notes` bullet so the model
        cannot miss it.
        """
        if pool.pool_snapshot_missing:
            snapshot_state = (
                "Snapshot missing — `system.compute.instance_pools` has no "
                "row for this pool (deleted before retention, or located in "
                "another region). DBU cost is still accurate; configuration "
                "fields below may be NULL."
            )
        elif pool.pool_deleted_at is not None:
            snapshot_state = (
                f"Deleted on {pool.pool_deleted_at.date().isoformat()} — "
                "metadata reflects the configuration at the delete time."
            )
        else:
            snapshot_state = "Active"

        if pool.pool_creator_id:
            creator_line = (
                f"- Creator ID: {pool.pool_creator_id} "
                "(GUID only — v1 does not resolve to email)"
            )
        else:
            creator_line = "- Creator ID: Unknown (REST API enrichment returned no tag)"

        def _fmt_int(v):
            return str(v) if v is not None else "Not specified"

        custom_tags_str = self._filter_tags(pool.custom_tags)

        lines: list[str] = [
            f"Pool Snapshot State: {snapshot_state}",
            "",
            "## Pool Configuration",
            f"- Pool Name: {pool.pool_name or f'Pool {pool.instance_pool_id}'}",
            f"- Node Type: {pool.node_type or 'Not specified'}",
            f"- Min Idle Instances: {_fmt_int(pool.min_idle_instances)}",
            f"- Max Capacity: {_fmt_int(pool.max_capacity)}",
            (
                "- Idle Autotermination: "
                f"{_fmt_int(pool.idle_instance_autotermination_minutes)} minutes"
            ),
            f"- Preloaded Spark Version: {pool.preloaded_spark_version or 'Not specified'}",
            creator_line,
            "",
            "## Custom Tags",
            custom_tags_str,
            "",
        ]

        if (
            cost_summary is not None
            and cost_summary.get("active_days", 0) > 0
        ):
            lookback = cost_summary.get("lookback_days", LOOKBACK_DAYS)
            lines.append(f"## Cost Summary ({lookback}-day window)")
            lines.append(
                f"- Total Spend (DBU + EC2/EBS): ${cost_summary['total_spend']:,.2f}"
            )
            lines.append(
                f"- Databricks Cost (DBU): ${cost_summary['total_databricks_cost']:,.2f}"
            )
            pool_cloud = cost_summary.get("total_cloud_cost")
            if pool_cloud is not None:
                lines.append(
                    f"- Cloud VM Cost (EC2/EBS, idle + active combined): "
                    f"${pool_cloud:,.2f}"
                )
            else:
                lines.append(
                    "- Cloud VM Cost (EC2/EBS): not available for this window "
                    "(no pool-tag cloud row landed yet)"
                )
            lines.append(
                f"- Distinct Clusters Attached: {cost_summary['distinct_cluster_count']}"
            )
            lines.append(
                f"- Active Days: {cost_summary['active_days']}"
            )
            lines.append(
                f"- Peak Concurrent Clusters (max distinct on any single day): "
                f"{cost_summary['peak_concurrent_clusters']}"
            )
            ratio = (
                cost_summary["distinct_cluster_count"]
                / cost_summary["active_days"]
                if cost_summary["active_days"] > 0 else 0.0
            )
            lines.append(
                f"- Cluster Fanout (distinct_clusters / active_days): {ratio:.2f}"
            )
            lines.append(
                f"- Avg Cost / Pool-Day: "
                f"${cost_summary['avg_cost_per_pool_day']:,.2f}"
            )
            first = cost_summary.get("first_active_date") or "N/A"
            last = cost_summary.get("last_active_date") or "N/A"
            lines.append(f"- Active Period: {first} to {last}")
            overhead = cost_summary.get("pool_overhead_rows", 0)
            if overhead:
                lines.append(
                    f"- Pool-Overhead Rows: {overhead} "
                    "(DBU billed at pool level with no attributable cluster_id)"
                )
            if cost_summary.get("limited_history"):
                lines.append(
                    "- NOTE: limited history (<3 active days) — trend "
                    "signals are unreliable."
                )
        elif cost_summary is not None:
            lines.append(f"## Cost Summary ({LOOKBACK_DAYS}-day window)")
            lines.append(
                "No spend data available for this pool in the lookback window."
            )
        else:
            lines.append("## Cost Summary")
            lines.append("Cost data unavailable.")

        lines.extend([
            "",
            "## Notes",
            "- Cloud-cost scope: pool EC2/EBS VM cost (idle + active combined) "
            "is included above, so dollar-impact estimates may use total cost. "
            f"However, {POOL_IDLE_SPLIT_CAVEAT}, so idle-specific VM waste "
            "cannot be quantified.",
        ])

        return "\n".join(lines)

    @staticmethod
    def _pipeline_effective_cost_basis(
        pipeline: PipelineDetails,
        cost_summary: Optional[dict],
    ) -> Optional[str]:
        """Resolve the cost_basis that governs the DBU-only caveat.

        Prefer the window-scoped value from the cost summary (it reflects the
        rows actually in the lookback) and fall back to the pipeline snapshot's
        dimension. ``None`` when neither is known (e.g. a made-up id) — the
        caveat is then NOT forced, since we cannot claim the spend is classic.
        """
        if cost_summary and cost_summary.get("cost_basis"):
            return cost_summary["cost_basis"]
        return pipeline.cost_basis

    @staticmethod
    def _pipeline_caveat_applies(cost_basis: Optional[str]) -> bool:
        """True when the DBU-only caveat MUST appear (classic / mixed spend)."""
        return cost_basis in ("dbu_only", "partial")

    def _build_pipeline_user_message(
        self,
        pipeline: PipelineDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Assemble the data-only USER message for pipeline analysis.

        Renders the workload/compute/cost-basis context, the §3.5 metadata
        state, owner attribution, and the cost shape over the lookback window.
        When the spend is classic/mixed the v1 DBU-only caveat is restated as a
        `Notes` bullet so the model cannot miss it; when serverless it states
        the figure is complete so the model does not falsely caveat it.
        """
        cost_basis = self._pipeline_effective_cost_basis(pipeline, cost_summary)
        workload_type = (
            (cost_summary or {}).get("workload_type")
            or pipeline.workload_type
            or "Unknown"
        )
        compute_mode = (
            (cost_summary or {}).get("compute_mode")
            or pipeline.compute_mode
            or "Unknown"
        )

        if pipeline.metadata_missing:
            metadata_state = (
                "Metadata not available — `system.lakeflow.pipelines` has no "
                "row for this pipeline (normal for Vector Search / cross-region "
                "/ retention edge). DBU cost is still accurate; configuration "
                "fields below may be NULL."
            )
        elif pipeline.pipeline_deleted_at is not None:
            metadata_state = (
                f"Deleted on {pipeline.pipeline_deleted_at.date().isoformat()} "
                "— metadata reflects the configuration at delete time."
            )
        else:
            metadata_state = "Active"

        lines: list[str] = [
            f"Metadata State: {metadata_state}",
            f"Metadata Available: {'No' if pipeline.metadata_missing else 'Yes'}",
            "",
            "## Pipeline Configuration",
            f"- Pipeline Name: {pipeline.pipeline_name or f'Pipeline {pipeline.pipeline_id}'}",
            f"- Workload Type: {workload_type}",
            f"- Compute Mode: {compute_mode}",
            f"- Cost Basis: {cost_basis or 'Unknown'}",
            f"- Pipeline Type: {pipeline.pipeline_type or 'Unknown'}",
            f"- Created By: {pipeline.created_by or 'Unknown'}",
            f"- Run As: {pipeline.run_as or 'Unknown'}",
        ]

        tags_str = self._filter_tags(pipeline.tags)
        lines.extend(["", "## Tags", tags_str, ""])

        if cost_summary is not None and cost_summary.get("active_days", 0) > 0:
            lookback = cost_summary.get("lookback_days", LOOKBACK_DAYS)
            lines.append(f"## Cost Summary ({lookback}-day window)")
            lines.append(
                f"- Total Spend (DBU): ${cost_summary['total_spend']:,.2f}"
            )
            lines.append(
                f"- Databricks Cost: ${cost_summary['total_databricks_cost']:,.2f}"
            )
            lines.append(f"- Active Days: {cost_summary['active_days']}")
            lines.append(
                f"- Avg Cost / Active Day: ${cost_summary['avg_cost_per_day']:,.2f}"
            )
            lines.append(
                "- Distinct Workload Types: "
                f"{cost_summary.get('distinct_workload_count', 1)}"
            )
            first = cost_summary.get("first_active_date") or "N/A"
            last = cost_summary.get("last_active_date") or "N/A"
            lines.append(f"- Active Period: {first} to {last}")
            if cost_summary.get("limited_history"):
                lines.append(
                    "- NOTE: limited history (<3 active days) — trend "
                    "signals are unreliable."
                )
        elif cost_summary is not None:
            lines.append(f"## Cost Summary ({LOOKBACK_DAYS}-day window)")
            lines.append(
                "No spend data available for this pipeline in the lookback "
                "window."
            )
        else:
            lines.append("## Cost Summary")
            lines.append("Cost data unavailable.")

        lines.append("")
        lines.append("## Notes")
        if self._pipeline_caveat_applies(cost_basis):
            lines.append(
                f"- v1 cost-basis caveat: this is {PIPELINE_DBU_ONLY_CAVEAT}. "
                "All dollar-impact estimates must use DBU cost only; do not "
                "invent cloud-VM savings."
            )
        else:
            lines.append(
                "- Cost basis is serverless (full): the DBU figure is the "
                "complete cost — there is no separate cloud VM line, so do "
                "NOT add a cloud-VM caveat or recommend node-type changes."
            )

        return "\n".join(lines)

    @staticmethod
    def _format_auto_stop(warehouse: SqlWarehouseDetails) -> str:
        """Render `auto_stop_mins` for the LLM message and fallback.

        A zero/negative value means auto-stop is off — the warehouse bills DBU
        until stopped by hand, which is the strongest idle-waste signal we can
        read. Values above ``SQL_WAREHOUSE_AUTO_STOP_THRESHOLD_MINS`` are
        annotated so the model reports the idle-waste angle instead of having
        to rediscover the threshold from the prompt alone (plan §6a).
        """
        mins = warehouse.auto_stop_mins
        if mins is None:
            return "Not specified"
        if mins <= 0:
            return "Disabled (warehouse never stops on its own)"
        if mins > SQL_WAREHOUSE_AUTO_STOP_THRESHOLD_MINS:
            return (
                f"{mins} minutes (above the "
                f"{SQL_WAREHOUSE_AUTO_STOP_THRESHOLD_MINS}-minute threshold — "
                "idle DBU cost signal)"
            )
        return f"{mins} minutes"

    def _build_sql_warehouse_user_message(
        self,
        warehouse: SqlWarehouseDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Assemble the data-only USER message for SQL warehouse analysis.

        Renders the same three-state metadata preamble as the pipeline builder
        (active / deleted / metadata-unavailable), the warehouse config block,
        and the cost shape over the lookback window. The `Notes` section
        restates that DBU is the complete cost so the model does not invent a
        cloud-VM caveat — the mirror image of the pipeline builder, which must
        add one for classic spend.
        """
        warehouse_type = (
            (cost_summary or {}).get("warehouse_type")
            or warehouse.warehouse_type
            or "Unknown"
        )

        if warehouse.metadata_missing:
            metadata_state = (
                "Metadata not available — `system.compute.warehouses` has no "
                "row for this warehouse (common: ~77% of warehouses, e.g. "
                "deleted before retention or cross-region). DBU cost is still "
                "accurate; configuration fields below may be NULL."
            )
        elif warehouse.warehouse_deleted_at is not None:
            metadata_state = (
                f"Deleted on "
                f"{warehouse.warehouse_deleted_at.date().isoformat()} — "
                "metadata reflects the configuration at delete time."
            )
        else:
            metadata_state = "Active"

        def _fmt_int(v):
            return str(v) if v is not None else "Not specified"

        warehouse_name = (
            warehouse.warehouse_name
            or (cost_summary or {}).get("warehouse_name")
            or f"Warehouse {warehouse.warehouse_id}"
        )

        lines: list[str] = [
            f"Metadata State: {metadata_state}",
            f"Metadata Available: {'No' if warehouse.metadata_missing else 'Yes'}",
            "",
            "## Warehouse Configuration",
            f"- Warehouse Name: {warehouse_name}",
            f"- Warehouse Type: {warehouse_type}",
            f"- Warehouse Size: {warehouse.warehouse_size or 'Not specified'}",
            f"- Creator ID: {warehouse.creator_id or 'Unknown'}",
            f"- Auto-Stop: {self._format_auto_stop(warehouse)}",
            f"- Min Clusters: {_fmt_int(warehouse.min_clusters)}",
            f"- Max Clusters: {_fmt_int(warehouse.max_clusters)}",
        ]

        tags_str = self._filter_tags(warehouse.tags)
        lines.extend(["", "## Tags", tags_str, ""])

        if cost_summary is not None and cost_summary.get("active_days", 0) > 0:
            lookback = cost_summary.get("lookback_days", LOOKBACK_DAYS)
            lines.append(f"## Cost Summary ({lookback}-day window)")
            lines.append(
                f"- Total Cost (DBU — complete cost): "
                f"${cost_summary['total_cost']:,.2f}"
            )
            lines.append(
                f"- Databricks Cost (DBU): "
                f"${cost_summary['total_dbu_cost']:,.2f}"
            )
            lines.append(f"- Active Days: {cost_summary['active_days']}")
            lines.append(
                f"- Avg Cost / Active Day: "
                f"${cost_summary['avg_daily_cost']:,.2f}"
            )
            lines.append(f"- Warehouse Type (from spend rows): {warehouse_type}")
            if cost_summary["active_days"] < 3:
                lines.append(
                    "- NOTE: limited history (<3 active days) — trend "
                    "signals are unreliable."
                )
        elif cost_summary is not None:
            lines.append("## Cost Summary")
            lines.append(
                "No spend data available for this warehouse in the lookback "
                "window."
            )
        else:
            lines.append("## Cost Summary")
            lines.append("Cost data unavailable.")

        lines.extend([
            "",
            "## Notes",
            "- Cost scope: DBU is the COMPLETE cost for managed-compute SQL "
            "warehouses (Classic, Pro, and Serverless alike). There is no "
            "separate cloud VM line and no missing cost component, so do NOT "
            "add a cloud-cost caveat and do NOT recommend instance-type, "
            "node-type, or spot changes — no such setting exists.",
            f"- Auto-stop above {SQL_WAREHOUSE_AUTO_STOP_THRESHOLD_MINS} "
            "minutes is a reportable idle-DBU cost signal.",
        ])

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
    def _build_pool_fallback(
        pool_details: InstancePoolDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Return structured fallback for instance-pool analysis.

        CP8 requires the ``POOL_IDLE_SPLIT_CAVEAT`` (idle-vs-active split not
        available yet) to appear in the analysis output. We embed it under
        Configuration Gaps so the assertion holds even when the LLM call
        itself fails.
        """
        pool_name = (
            pool_details.pool_name
            or f"Pool {pool_details.instance_pool_id}"
        )
        node_type = pool_details.node_type or "N/A"
        min_idle = (
            str(pool_details.min_idle_instances)
            if pool_details.min_idle_instances is not None else "N/A"
        )
        max_cap = (
            str(pool_details.max_capacity)
            if pool_details.max_capacity is not None else "N/A"
        )
        autoterm = (
            f"{pool_details.idle_instance_autotermination_minutes} minutes"
            if pool_details.idle_instance_autotermination_minutes is not None
            else "N/A"
        )

        lines = [
            "## 1. Overall Rating [DATA ONLY]",
            f"- Pool: {pool_name}",
            f"- Node Type: {node_type}",
            f"- Min Idle: {min_idle} | Max Capacity: {max_cap}",
            f"- Idle Autotermination: {autoterm}",
            "- Automated classification unavailable",
            "",
            "## 2. Right-Sizing Assessment",
        ]
        if (
            cost_summary
            and isinstance(cost_summary.get("total_spend"), (int, float))
            and cost_summary["total_spend"] > 0
        ):
            lines.append(
                f"- Total Spend (DBU + EC2/EBS): ${cost_summary['total_spend']:,.2f}"
            )
            pool_cloud = cost_summary.get("total_cloud_cost")
            if pool_cloud is not None:
                lines.append(
                    f"- Cloud VM Cost (EC2/EBS): ${pool_cloud:,.2f}"
                )
            lines.append(
                f"- Distinct Clusters: "
                f"{cost_summary.get('distinct_cluster_count', 'N/A')}"
            )
            lines.append(
                f"- Active Days: {cost_summary.get('active_days', 'N/A')}"
            )
            lines.append(
                f"- Peak Concurrent Clusters: "
                f"{cost_summary.get('peak_concurrent_clusters', 'N/A')}"
            )
        else:
            lines.append("- No cost data available for sizing assessment")
        lines.extend([
            "",
            "## 3. Cost Savings Opportunities",
            "- Automated recommendations unavailable",
            "",
            "## 4. Idle Waste Risk",
            f"- Idle Autotermination: {autoterm}",
            "- Detailed analysis unavailable. Note: pool EC2/EBS cost is "
            f"included in totals, but {POOL_IDLE_SPLIT_CAVEAT}.",
            "",
            "## 5. Configuration Gaps",
            "- Automated analysis could not be generated",
            f"- Reminder: {POOL_IDLE_SPLIT_CAVEAT}; idle-specific VM waste "
            "cannot be quantified.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _build_pipeline_fallback(
        pipeline_details: PipelineDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Return structured fallback for pipeline analysis.

        Honours the same conditional caveat as the prompt: the
        ``excludes cloud VM cost`` string is embedded ONLY when the effective
        cost_basis is classic/mixed, so plan §9 #14 / CP7 exit criterion #4
        hold even when the LLM call fails — and a serverless pipeline does not
        get a false caveat.
        """
        cost_basis = LLMService._pipeline_effective_cost_basis(
            pipeline_details, cost_summary
        )
        caveat_applies = LLMService._pipeline_caveat_applies(cost_basis)
        pipeline_name = (
            pipeline_details.pipeline_name
            or f"Pipeline {pipeline_details.pipeline_id}"
        )
        workload_type = pipeline_details.workload_type or "Unknown"
        compute_mode = pipeline_details.compute_mode or "Unknown"

        lines = [
            "## 1. Overall Rating [DATA ONLY]",
            f"- Pipeline: {pipeline_name}",
            f"- Workload Type: {workload_type}",
            f"- Compute Mode: {compute_mode}",
            f"- Cost Basis: {cost_basis or 'Unknown'}",
            "- Automated classification unavailable",
            "",
            "## 2. Right-Sizing Assessment",
        ]
        if (
            cost_summary
            and isinstance(cost_summary.get("total_spend"), (int, float))
            and cost_summary["total_spend"] > 0
        ):
            lines.append(
                f"- Total Spend (DBU): ${cost_summary['total_spend']:,.2f}"
            )
            lines.append(
                f"- Active Days: {cost_summary.get('active_days', 'N/A')}"
            )
            lines.append(
                f"- Avg Cost/Day: "
                f"${cost_summary.get('avg_cost_per_day', 0):,.2f}"
            )
        else:
            lines.append("- No cost data available for sizing assessment")
        lines.extend([
            "",
            "## 3. Cost Savings Opportunities",
            "- Automated recommendations unavailable",
            "",
            "## 4. Idle Waste Risk",
        ])
        if caveat_applies:
            lines.append(
                "- Detailed analysis unavailable. Note: this figure is "
                f"{PIPELINE_DBU_ONLY_CAVEAT}."
            )
        else:
            lines.append(
                "- Detailed analysis unavailable. Serverless DBU cost is the "
                "complete cost (no separate cloud VM line)."
            )
        lines.extend([
            "",
            "## 5. Configuration Gaps",
            "- Automated analysis could not be generated",
        ])
        if caveat_applies:
            lines.append(f"- Reminder: {PIPELINE_DBU_ONLY_CAVEAT}.")
        return "\n".join(lines)

    @staticmethod
    def _build_sql_warehouse_fallback(
        warehouse_details: SqlWarehouseDetails,
        cost_summary: Optional[dict],
    ) -> str:
        """Return structured fallback for SQL warehouse analysis.

        Mirrors the prompt's five-section format so the modal renders the same
        shape on LLM failure. Deliberately carries no cost caveat: DBU is the
        complete cost here, so the pipeline/pool honesty strings must NOT leak
        into this tab.
        """
        warehouse_name = (
            warehouse_details.warehouse_name
            or (cost_summary or {}).get("warehouse_name")
            or f"Warehouse {warehouse_details.warehouse_id}"
        )
        warehouse_type = (
            (cost_summary or {}).get("warehouse_type")
            or warehouse_details.warehouse_type
            or "Unknown"
        )
        auto_stop = LLMService._format_auto_stop(warehouse_details)
        size = warehouse_details.warehouse_size or "N/A"
        min_clusters = (
            str(warehouse_details.min_clusters)
            if warehouse_details.min_clusters is not None else "N/A"
        )
        max_clusters = (
            str(warehouse_details.max_clusters)
            if warehouse_details.max_clusters is not None else "N/A"
        )

        lines = [
            "## 1. Overall Rating [DATA ONLY]",
            f"- Warehouse: {warehouse_name}",
            f"- Type: {warehouse_type} | Size: {size}",
            f"- Auto-Stop: {auto_stop}",
            f"- Min Clusters: {min_clusters} | Max Clusters: {max_clusters}",
            "- Automated classification unavailable",
            "",
            "## 2. Right-Sizing Assessment",
        ]
        if (
            cost_summary
            and isinstance(cost_summary.get("total_cost"), (int, float))
            and cost_summary["total_cost"] > 0
        ):
            lines.append(
                f"- Total Cost (DBU — complete cost): "
                f"${cost_summary['total_cost']:,.2f}"
            )
            lines.append(
                f"- Active Days: {cost_summary.get('active_days', 'N/A')}"
            )
            lines.append(
                f"- Avg Cost/Day: "
                f"${cost_summary.get('avg_daily_cost', 0):,.2f}"
            )
        else:
            lines.append("- No cost data available for sizing assessment")
        lines.extend([
            "",
            "## 3. Cost Optimization",
            "- Detailed analysis unavailable. DBU is the complete cost for "
            "managed-compute SQL warehouses — there is no separate cloud "
            "component to optimize.",
            f"- Auto-Stop: {auto_stop}",
            "",
            "## 4. Configuration Gaps",
            "- Automated analysis could not be generated",
            "",
            "## 5. Recommendations",
            "- Automated recommendations unavailable",
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

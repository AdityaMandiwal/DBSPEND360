from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, computed_field
from server.config.cloud_platform import cloud_config


class JobSpend(BaseModel):
  """Data model for Databricks job spending records."""

  cluster_id: str
  cloud_cost: float
  job_id: str
  job_name: Optional[str] = None
  run_id: str
  usage_date: date
  databricks_cost: float
  compute_cost: Optional[float] = None
  storage_cost: Optional[float] = None
  network_cost: Optional[float] = None
  other_cost: Optional[float] = None

  @computed_field
  @property
  def total_cost(self) -> float:
    """Calculate total cost as sum of cloud and Databricks costs."""
    return self.cloud_cost + self.databricks_cost

  @computed_field
  @property
  def cloud_percentage(self) -> float:
    """Calculate cloud cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.cloud_cost / self.total_cost) * 100

  @computed_field
  @property
  def databricks_percentage(self) -> float:
    """Calculate Databricks cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.databricks_cost / self.total_cost) * 100


class JobSpendFilter(BaseModel):
  """Filter parameters for job spend queries."""

  start_date: date
  end_date: date
  job_name: Optional[str] = None
  limit: int = Field(default=50, ge=1, le=1000)
  offset: int = Field(default=0, ge=0)


class SummaryMetrics(BaseModel):
  """Summary metrics for job spending data."""

  total_jobs: int
  total_spend: float
  average_cost: float
  max_cost: float
  min_cost: float
  total_cloud_cost: float
  total_databricks_cost: float
  total_compute_cost: Optional[float] = None
  total_storage_cost: Optional[float] = None
  total_network_cost: Optional[float] = None
  total_other_cost: Optional[float] = None
  classification_coverage_pct: Optional[float] = None
  coverage_status: Optional[str] = None
  coverage_warning: Optional[str] = None
  dbu_in_non_covered_workspaces: float = 0.0
  date_range_days: int


class CostBreakdown(BaseModel):
  """Cost breakdown for individual job."""

  job_id: str
  run_id: str
  cluster_id: str
  usage_date: date
  end_date: Optional[date] = None
  cloud_cost: float
  databricks_cost: float
  total_cost: float
  compute_cost: Optional[float] = None
  storage_cost: Optional[float] = None
  network_cost: Optional[float] = None
  other_cost: Optional[float] = None
  cost_split: list[dict[str, Any]] = Field(default_factory=list)

  def __init__(self, **data):
    super().__init__(**data)
    labels = cloud_config.get_cost_breakdown_labels()
    compute = data.get('compute_cost')
    storage = data.get('storage_cost')
    network = data.get('network_cost')
    other = data.get('other_cost')
    has_segmented = compute is not None

    if has_segmented:
      split = [
        {'name': 'Compute', 'value': float(compute or 0), 'color': '#3b82f6'},
        {'name': 'Storage', 'value': float(storage or 0), 'color': '#22c55e'},
        {'name': 'Network', 'value': float(network or 0), 'color': '#f59e0b'},
      ]
      other_val = float(other or 0)
      if other_val > 0:
        split.append({'name': 'Other', 'value': other_val, 'color': '#6b7280'})
      split.append(
        {
          'name': 'Databricks (DBU)',
          'value': float(data.get('databricks_cost', 0)),
          'color': '#ef4444',
        }
      )
      self.cost_split = split
    else:
      self.cost_split = [
        {'name': labels['compute_cost'], 'value': self.cloud_cost, 'color': '#3b82f6'},
        {
          'name': labels['databricks_cost'],
          'value': float(data.get('databricks_cost', 0)),
          'color': '#ef4444',
        },
      ]


class JobRun(BaseModel):
  """Individual job run details."""

  run_id: str
  cluster_id: str
  start_date: date
  end_date: date
  cloud_cost: float
  databricks_cost: float
  compute_cost: Optional[float] = None
  storage_cost: Optional[float] = None
  network_cost: Optional[float] = None
  other_cost: Optional[float] = None
  workspace_covered: bool = True

  @computed_field
  @property
  def total_cost(self) -> float:
    """Calculate total cost as sum of cloud and Databricks costs."""
    return self.cloud_cost + self.databricks_cost

  @computed_field
  @property
  def cloud_percentage(self) -> float:
    """Calculate cloud cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.cloud_cost / self.total_cost) * 100

  @computed_field
  @property
  def databricks_percentage(self) -> float:
    """Calculate Databricks cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.databricks_cost / self.total_cost) * 100


class GroupedJob(BaseModel):
  """Grouped job data with aggregated costs and (optional) run details.

  `runs` may be empty when the consumer only needs job-level totals (e.g. the
  "Top N Costliest Jobs" card on the dashboard, which renders a flat list and
  deliberately skips the per-run enrichment query to keep the endpoint cheap).
  Callers that need a per-run drill-down read from `runs`; callers that only
  care about totals can ignore it.
  """

  job_id: str
  job_name: Optional[str] = None
  run_count: int
  total_cloud_cost: float
  total_databricks_cost: float
  total_compute_cost: Optional[float] = None
  total_storage_cost: Optional[float] = None
  total_network_cost: Optional[float] = None
  total_other_cost: Optional[float] = None
  workspace_covered: bool = True
  runs: list[JobRun]

  @computed_field
  @property
  def total_cost(self) -> float:
    """Calculate total cost across all runs."""
    return self.total_cloud_cost + self.total_databricks_cost

  @computed_field
  @property
  def cloud_percentage(self) -> float:
    """Calculate cloud cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.total_cloud_cost / self.total_cost) * 100

  @computed_field
  @property
  def databricks_percentage(self) -> float:
    """Calculate Databricks cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.total_databricks_cost / self.total_cost) * 100


class PaginatedJobSpends(BaseModel):
  """Paginated response for job spends."""

  data: list[JobSpend]
  total_count: int
  page: int
  per_page: int
  total_pages: int
  has_next: bool
  has_previous: bool


class PaginatedGroupedJobs(BaseModel):
  """Paginated response for grouped jobs."""

  data: list[GroupedJob]
  total_count: int
  page: int
  per_page: int
  total_pages: int
  has_next: bool
  has_previous: bool


class CostAnalysis(BaseModel):
  """LLM-generated cost analysis for a job run."""

  job_id: str
  run_id: str
  analysis: str
  timestamp: str = Field(default_factory=lambda: date.today().isoformat())


class ClusterDetails(BaseModel):
  """Cluster configuration details from system.compute.clusters."""

  cluster_id: str
  cluster_name: Optional[str] = None
  cluster_source: Optional[str] = None
  owned_by: Optional[str] = None
  create_time: Optional[str] = None
  driver_node_type: Optional[str] = None
  worker_node_type: Optional[str] = None
  worker_count: Optional[int] = None
  min_autoscale_workers: Optional[int] = None
  max_autoscale_workers: Optional[int] = None
  auto_termination_minutes: Optional[int] = None
  enable_elastic_disk: Optional[bool] = None
  tags: Optional[dict] = None
  aws_attributes: Optional[dict] = None
  azure_attributes: Optional[dict] = None
  gcp_attributes: Optional[dict] = None
  dbr_version: Optional[str] = None
  data_security_mode: Optional[str] = None

  @property
  def is_job_cluster(self) -> bool:
    """Return True when this row represents a job (ephemeral) cluster.

    `system.compute.clusters.cluster_source` is `JOB` for clusters spun up
    for a single job run; for those, `auto_termination_minutes` is NULL by
    design because the cluster lifecycle is bound to the run.
    """
    return (self.cluster_source or '').upper() == 'JOB'


class ClusterAnalysis(BaseModel):
  """LLM-generated cluster configuration analysis."""

  cluster_id: str
  analysis: str
  timestamp: str = Field(default_factory=lambda: date.today().isoformat())


class CloudPlatformInfo(BaseModel):
  """Cloud platform configuration information."""

  platform: str
  compute_service: str
  compute_display_name: str
  platform_display_name: str


class OtherCostBreakdownItem(BaseModel):
  """Single service contributing to other_cost."""

  service_name: str
  cost: float
  percentage: float
  source_system: str


class OtherCostBreakdownResponse(BaseModel):
  """Response for other cost breakdown drilldown."""

  items: list[OtherCostBreakdownItem]
  total_other_cost: float
  start_date: date
  end_date: date


class FeatureFlagsResponse(BaseModel):
  """Feature flags exposed to the frontend."""

  enable_cost_analysis: bool
  enable_cluster_analysis: bool
  enable_export: bool
  enable_job_dbu_breakdown: bool


class JobProductBreakdownItem(BaseModel):
  """Single billing product contributing to a job's DBU cost."""

  billing_origin_product: str
  label: str
  cost: float
  percentage: float


class JobProductBreakdownResponse(BaseModel):
  """Read-time DBU breakdown by billing_origin_product for one job."""

  job_id: str
  start_date: date
  end_date: date
  items: list[JobProductBreakdownItem]
  total_cost: float
  rollup_databricks_cost: Optional[float] = None
  has_multiple_products: bool
  is_estimate: bool = True
  unpriced_warning: Optional[str] = None


# ---------------------------------------------------------------------------
# All-Purpose cluster models
#
# Wire-level types for the All-Purpose Clusters tab. Source table is
# `dbspend360_total_all_purpose_spends`, keyed `(cluster_id, user_id, usage_date)`
# with `user_id` derived from `system.compute.clusters.owned_by` (see plan
# §3.2). Under v1 owner attribution every (cluster_id, usage_date) resolves to
# exactly one user_id; the (user_id, ...) key shape is preserved for v2
# multi-user attribution forward compatibility.
# ---------------------------------------------------------------------------


class AllPurposeUserSpend(BaseModel):
  """Per-day cost contribution within an all-purpose cluster grouping.

  Drill-down sub-row inside `GroupedAllPurposeCluster.users`. Under v1 owner
  attribution there is exactly one user per (cluster_id, usage_date), so
  this row collapses to a single calendar day's cost on the cluster owned by
  that user. Forward-compatible with v2 multi-user attribution where the
  same cluster-day can fan out to multiple users.
  """

  cluster_id: str
  user_id: str
  usage_date: date
  # NULL when no cloud (EC2/EBS) row matched this cluster-day — e.g. it ran
  # on an instance pool (machines tagged DatabricksInstancePoolId, not
  # ClusterId) or Cost Explorer hasn't landed. The UI renders None as "—".
  cloud_cost: Optional[float] = None
  databricks_cost: float
  compute_cost: Optional[float] = None
  storage_cost: Optional[float] = None
  network_cost: Optional[float] = None
  other_cost: Optional[float] = None
  workspace_covered: bool = True

  @computed_field
  @property
  def total_cost(self) -> float:
    """Calculate total cost as sum of cloud and Databricks costs."""
    return (self.cloud_cost or 0.0) + self.databricks_cost

  @computed_field
  @property
  def cloud_percentage(self) -> float:
    """Calculate cloud cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return ((self.cloud_cost or 0.0) / self.total_cost) * 100

  @computed_field
  @property
  def databricks_percentage(self) -> float:
    """Calculate Databricks cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.databricks_cost / self.total_cost) * 100


class AllPurposeClusterSpend(BaseModel):
  """Per-cluster cost contribution within a user grouping.

  Drill-down sub-row inside `GroupedAllPurposeUser.clusters`. Aggregates a
  user's cost on a single cluster across the queried date window;
  `cluster_active_days` is `COUNT(DISTINCT usage_date)` for that
  `(user_id, cluster_id)` pair. `data_security_mode` is denormalized so the
  UI can render the attribution-quality badge ("Dedicated" / "Shared" /
  "Legacy" / "Unknown") next to the cluster name without a second lookup.
  """

  cluster_id: str
  cluster_name: Optional[str] = None
  user_id: str
  cluster_active_days: int
  # NULL when no cloud row matched this user's cluster — the UI renders "—".
  cloud_cost: Optional[float] = None
  databricks_cost: float
  compute_cost: Optional[float] = None
  storage_cost: Optional[float] = None
  network_cost: Optional[float] = None
  other_cost: Optional[float] = None
  data_security_mode: Optional[str] = None
  workspace_covered: bool = True

  @computed_field
  @property
  def total_cost(self) -> float:
    """Calculate total cost as sum of cloud and Databricks costs."""
    return (self.cloud_cost or 0.0) + self.databricks_cost

  @computed_field
  @property
  def cloud_percentage(self) -> float:
    """Calculate cloud cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return ((self.cloud_cost or 0.0) / self.total_cost) * 100

  @computed_field
  @property
  def databricks_percentage(self) -> float:
    """Calculate Databricks cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.databricks_cost / self.total_cost) * 100


class GroupedAllPurposeCluster(BaseModel):
  """Cluster-level rollup for the By-Cluster sub-tab.

  One row per all-purpose cluster within the queried window. `users` is the
  per-day drill-down expansion (under v1: one user per day, the cluster
  owner). `data_security_mode` drives the UI attribution-quality badge.
  `cluster_name` may be NULL when the `system.compute.clusters` snapshot row
  is missing (cluster deleted before October 2023, see plan §10); the UI
  falls back to `Cluster {cluster_id}` in that case.
  """

  cluster_id: str
  cluster_name: Optional[str] = None
  owner_user_id: str
  data_security_mode: Optional[str] = None
  active_days: int
  # NULL when no cloud row matched this cluster — the UI renders "—".
  total_cloud_cost: Optional[float] = None
  total_databricks_cost: float
  total_compute_cost: Optional[float] = None
  total_storage_cost: Optional[float] = None
  total_network_cost: Optional[float] = None
  total_other_cost: Optional[float] = None
  workspace_covered: bool = True
  users: list[AllPurposeUserSpend] = Field(default_factory=list)

  @computed_field
  @property
  def total_cost(self) -> float:
    """Calculate total cost across all users on this cluster."""
    return (self.total_cloud_cost or 0.0) + self.total_databricks_cost

  @computed_field
  @property
  def cloud_percentage(self) -> float:
    """Calculate cloud cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return ((self.total_cloud_cost or 0.0) / self.total_cost) * 100

  @computed_field
  @property
  def databricks_percentage(self) -> float:
    """Calculate Databricks cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.total_databricks_cost / self.total_cost) * 100


class GroupedAllPurposeUser(BaseModel):
  """User-level rollup for the By-User (chargeback) sub-tab.

  One row per cluster owner within the queried window. `clusters` lists the
  per-cluster drill-down rows (one entry per (user_id, cluster_id) pair).
  `user_active_days` is `COUNT(DISTINCT usage_date)` from the raw rows
  (not summed across clusters — a user active on multiple clusters on the
  same day must not double-count; see plan §5.2).
  """

  user_id: str
  cluster_count: int
  user_active_days: int
  # NULL when none of this user's clusters had a matching cloud row — the UI
  # renders "—".
  total_cloud_cost: Optional[float] = None
  total_databricks_cost: float
  total_compute_cost: Optional[float] = None
  total_storage_cost: Optional[float] = None
  total_network_cost: Optional[float] = None
  total_other_cost: Optional[float] = None
  workspace_covered: bool = True
  clusters: list[AllPurposeClusterSpend] = Field(default_factory=list)

  @computed_field
  @property
  def total_cost(self) -> float:
    """Calculate total cost across all clusters this user owns."""
    return (self.total_cloud_cost or 0.0) + self.total_databricks_cost

  @computed_field
  @property
  def cloud_percentage(self) -> float:
    """Calculate cloud cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return ((self.total_cloud_cost or 0.0) / self.total_cost) * 100

  @computed_field
  @property
  def databricks_percentage(self) -> float:
    """Calculate Databricks cost as percentage of total."""
    if self.total_cost == 0:
      return 0.0
    return (self.total_databricks_cost / self.total_cost) * 100


class AllPurposeSummaryMetrics(BaseModel):
  """Summary metrics for the All-Purpose tab KPI strip.

  `avg_cost_per_cluster_day` / `max_cost_per_cluster_day` /
  `min_cost_per_cluster_day` are computed at the (cluster_id, user_id,
  usage_date) grain (see plan §5.3) — not per cluster overall — so the
  "average" is interpretable as "what does a single day on a single cluster
  cost on average".
  """

  total_clusters: int
  total_users: int
  total_spend: float
  avg_cost_per_cluster_day: float
  max_cost_per_cluster_day: float
  min_cost_per_cluster_day: float
  total_cloud_cost: float
  total_databricks_cost: float
  total_compute_cost: Optional[float] = None
  total_storage_cost: Optional[float] = None
  total_network_cost: Optional[float] = None
  total_other_cost: Optional[float] = None
  date_range_days: int
  dbu_in_non_covered_workspaces: float = 0.0


class PaginatedAllPurposeClusters(BaseModel):
  """Paginated response for the By-Cluster sub-tab."""

  data: list[GroupedAllPurposeCluster]
  total_count: int
  page: int
  per_page: int
  total_pages: int
  has_next: bool
  has_previous: bool


class PaginatedAllPurposeUsers(BaseModel):
  """Paginated response for the By-User sub-tab."""

  data: list[GroupedAllPurposeUser]
  total_count: int
  page: int
  per_page: int
  total_pages: int
  has_next: bool
  has_previous: bool


# ---------------------------------------------------------------------------
# Instance Pool models
#
# Wire-level types for the Instance Pools tab. Source table is
# `dbspend360_total_pool_spends`, keyed `(instance_pool_id, cluster_id,
# usage_date)`. Two-level drill-down: pool row -> per-day expansion ->
# per-cluster expansion (see plan §3.3, §5.2).
#
# As of CP7 (plan §4.4/§4.6) pool EC2/EBS `cloud_cost` is joined in from
# `dbspend360_pool_cloud_cost_explorer` and surfaced at the pool and per-day
# level; it is `None` only when no pool-tag cloud row exists yet (plan §5 /
# decision #3). Per-cluster sub-rows keep `cloud_cost = None` because pool VM
# cost is pool-level, not attributable to a specific attached cluster (AWS
# tags pool instances `DatabricksInstancePoolId`, not `ClusterId`).
# `total_cost` is a plain field rather than a computed_field because the §5.2
# service-layer rollup increments it directly during day-level aggregation,
# and `cloud_cost = None` would otherwise force NoneType arithmetic in a
# computed expression.
#
# Creator info is intentionally absent from list-shape models. The
# `system.compute.instance_pools.tags` column excludes default tags so the
# auto-applied `DatabricksInstancePoolCreatorId` is not visible there;
# `pool_creator_id` is resolved per-request via the Instance Pools REST API
# in `InstancePoolDetails` only (plan §3.4, §4.1, CP6). GUID -> email
# resolution is deferred to v2 (plan §13).
# ---------------------------------------------------------------------------


class InstancePoolClusterSpend(BaseModel):
  """Per-cluster cost contribution within a pool's per-day expansion.

  Drill-down sub-row inside `InstancePoolDailySpend.clusters`. One entry
  per cluster that attached to the pool on a given `usage_date`.
  `cluster_id == '__pool_overhead__'` represents pool-level bootstrap
  charges that have no attributable cluster (plan §3.3 edge case); the UI
  renders that row as italicized "Pool overhead". `cloud_cost` is `None` on
  real per-cluster rows even after CP7: pool EC2/EBS is pool-level, not
  attributable to a specific attached cluster (AWS tags pool instances
  `DatabricksInstancePoolId`, not `ClusterId`), so the UI renders "—" there.
  The one exception is the `__pool_overhead__` row itself, which DOES carry
  the pool EC2/EBS `cloud_cost` — that is where the pool VM cost genuinely
  lands, so surfacing it makes the row's `total_cost` break down visibly as
  `databricks_cost + cloud_cost` instead of a Total with no components
  (issue #3). The pool/day-level EC2 figure is still the authoritative one.
  """

  cluster_id: str
  databricks_cost: float
  cloud_cost: Optional[float] = None
  total_cost: float = 0.0


class InstancePoolDailySpend(BaseModel):
  """Per-day cost contribution within an instance pool grouping.

  Drill-down sub-row inside `GroupedInstancePool.days`. `clusters` is the
  second-level expansion (plan §3.3) listing per-cluster contributions for
  that day, sorted DESC by `total_cost` (per the §5.2 SQL ORDER BY).
  `cluster_count_on_day` equals `len(clusters)` by construction in the
  service-layer rollup. `cloud_cost` is the pool EC2/EBS cost for the day
  (CP7, plan §4.4) — summed from the `__pool_overhead__` row where the pool
  VM cost lands — and is `None` when no cloud row exists for the day (UI
  renders "—", §5); `total_cost` is plumbed straight through from the SQL
  projection rather than computed (see module docstring rationale).
  """

  usage_date: date
  cluster_count_on_day: int
  databricks_cost: float
  cloud_cost: Optional[float] = None
  total_cost: float = 0.0
  clusters: list[InstancePoolClusterSpend] = Field(default_factory=list)


class GroupedInstancePool(BaseModel):
  """Pool-level rollup for the By-Pool list view.

  One row per instance pool within the queried window. `days` is the
  first-level drill-down expansion (plan §3.3). `pool_snapshot_missing`
  and `pool_deleted_at` together encode the three-state badge from plan
  §3.5: active (both falsy), "Deleted YYYY-MM-DD" (`pool_deleted_at`
  populated, missing flag false), "Snapshot missing" (missing flag true,
  `pool_deleted_at` NULL). `pool_name` falls back to `Pool {pool_id}` in
  the snapshot-missing path (plan §5.5). No creator field — creator info
  is modal-only via the REST API in v1 (plan §3.4, §4.1).
  """

  instance_pool_id: str
  pool_name: Optional[str] = None
  node_type: Optional[str] = None
  min_idle_instances: Optional[int] = None
  max_capacity: Optional[int] = None
  idle_instance_autotermination_minutes: Optional[int] = None
  pool_snapshot_missing: bool = False
  pool_deleted_at: Optional[datetime] = None
  cluster_count: int
  active_days: int
  total_databricks_cost: float
  total_cloud_cost: Optional[float] = None
  total_cost: float
  workspace_covered: bool = True
  days: list[InstancePoolDailySpend] = Field(default_factory=list)


class InstancePoolSummaryMetrics(BaseModel):
  """Summary metrics for the Instance Pools tab KPI strip.

  `avg_cost_per_pool_day` / `max_cost_per_pool_day` /
  `min_cost_per_pool_day` are computed at the (instance_pool_id,
  usage_date) grain (plan §5.3) so "average" reads as "what does a single
  day on a single pool cost on average". `orphaned_pools` is the count of
  distinct pools with `pool_snapshot_missing = TRUE`, surfaced as a KPI so
  operators can spot lost-metadata churn at a glance (plan §10 risk).
  `total_cloud_cost` is the summed pool EC2/EBS cost over the window (CP7,
  plan §4.4/§4.6); it stays optional and is `None` only when no pool-day in
  the window carries a cloud row yet, so the KPI is hidden rather than
  showing a misleading `$0` (plan §5 / decision #3).
  """

  total_pools: int
  total_clusters: int
  orphaned_pools: int
  total_spend: float
  avg_cost_per_pool_day: float
  max_cost_per_pool_day: float
  min_cost_per_pool_day: float
  total_databricks_cost: float
  total_cloud_cost: Optional[float] = None
  date_range_days: int
  dbu_in_non_covered_workspaces: float = 0.0


class InstancePoolDailyTrendPoint(BaseModel):
  """One calendar day of aggregate pool spend for the trend sparkline.

  `total_cost` is covered-workspace pool spend (DBU + cloud) for that day,
  zero-filled when no pool rows landed. Used by `/api/instance-pools/daily-trend`.
  """

  usage_date: date
  total_cost: float = 0.0


class InstancePoolDetails(BaseModel):
  """Pool configuration details for the pool details modal.

  Sourced from `system.compute.instance_pools` (most-recent SCD snapshot
  via `max_by(col, change_time)` per field — see plan §5.5 / CP6).
  `pool_creator_id` carries the GUID resolved per-request by
  `DatabricksService.get_pool_metadata`, which reads
  `default_tags['DatabricksInstancePoolCreatorId']` from the Instance Pools
  REST API response. None when the REST API call fails or the pool has no
  creator tag (e.g. workspace-system-created pools). `pool_creator_user_name`
  (email) is intentionally absent in v1 — the SDK's `GetInstancePool`
  dataclass exposes only `default_tags`, and GUID -> email resolution
  requires a second hop through the Workspace users API which is deferred
  to v2 (plan §13).

  `node_type` matches the actual `system.compute.instance_pools` column
  (NOT `node_type_id` — see plan §10 risks row).
  `preloaded_spark_version` is singular (the column is also singular).
  `pool_snapshot_missing=True` indicates no system-table snapshot row was
  found; in that case the modal still attempts the REST API enrichment so
  a deleted-but-still-tracked pool can surface its name and creator GUID
  (plan CP6).
  """

  instance_pool_id: str
  pool_name: Optional[str] = None
  pool_creator_id: Optional[str] = None
  node_type: Optional[str] = None
  min_idle_instances: Optional[int] = None
  max_capacity: Optional[int] = None
  idle_instance_autotermination_minutes: Optional[int] = None
  preloaded_spark_version: Optional[str] = None
  custom_tags: Optional[dict[str, str]] = None
  pool_snapshot_missing: bool = False
  pool_deleted_at: Optional[datetime] = None


class InstancePoolAnalysis(BaseModel):
  """LLM-generated configuration analysis for an instance pool.

  Returned by `/api/instance-pools/{id}/analyze`. As of CP8
  (plan_pool_pipeline_ec2_cost.md §4.4) pool EC2/EBS cost is in the
  summary, so the analysis text now carries only the remaining
  idle-vs-active-split caveat (plan §4.5) rather than the old DBU-only
  caveat. The output structure mirrors `ClusterAnalysis`'s
  config-shape sections (Overall Rating / Right-Sizing / Cost Savings /
  Idle Waste Risk / Configuration Gaps) rather than the run-cost trend
  structure used by `CostAnalysis`.
  """

  instance_pool_id: str
  analysis: str
  timestamp: str = Field(default_factory=lambda: date.today().isoformat())


class PaginatedInstancePools(BaseModel):
  """Paginated response for the By-Pool list view."""

  data: list[GroupedInstancePool]
  total_count: int
  page: int
  per_page: int
  total_pages: int
  has_next: bool
  has_previous: bool


# ---------------------------------------------------------------------------
# Pipeline Compute models
#
# Wire-level types for the Pipeline Compute tab (plan_dlt_tab.md). Source table
# is `dbspend360_total_pipeline_spends`, keyed `(workspace_id, pipeline_id,
# usage_date, billing_origin_product)`. The read collapses the product grain
# away, so the UI sees one row per pipeline (`GroupedPipeline`) with a single
# drill-down to per-day rows (`PipelineDailySpend`); see plan §3.3 / §5.1-5.2.
#
# This tab covers ALL `usage_metadata.dlt_pipeline_id` spend — not just DLT —
# dimensioned by `workload_type` (DLT is only ~25% of it; plan §0/§3.1). The
# three honesty signals are carried as plain fields:
#   - `workload_type`  : friendly label of the cost-dominant workload (badge).
#   - `compute_mode`   : serverless / classic / mixed.
#   - `cost_basis`     : full / dbu_only / partial — which numbers exclude
#                        cloud VM (plan §3.2). `cost_basis = 'full'` <=>
#                        serverless (the 96% majority), so the headline number
#                        is the complete cost for most rows.
#
# Cloud cost (CP2): the classic-cluster EC2/EBS join is live (plan §3.2), so
# `cloud_cost` carries the real `SUM(cloud_cost)` for classic pipeline-days and
# stays `None` for fully-serverless rows (no separate VM line — the UI renders
# "—" + note, §5; `None` means "unknown / not separable", not "$0"). `total_cost`
# is a plain field rather than a computed_field — preserving `None` for unknown
# would force NoneType arithmetic, and the service-layer rollup plumbs
# `total_cost` straight from the SQL projection (mirrors the Instance Pool
# models' rationale).
#
# Owner attribution (`created_by`/`run_as`) comes straight from
# `system.lakeflow.pipelines` — no REST API, no GUID resolution (verified
# 99.94% populated for DLT in plan §0). Absent metadata falls back to None
# ("Unknown" in the UI) with `metadata_missing = True` (plan §3.4/§3.5).
# ---------------------------------------------------------------------------


class PipelineDailySpend(BaseModel):
  """Per-day cost contribution within a pipeline grouping.

  Drill-down sub-row inside `GroupedPipeline.days`. The rollup is at product
  grain (plan §3.3), so the §5.2 read sums across `billing_origin_product`
  within each `usage_date` before the service nests it here — the UI still
  sees exactly one row per pipeline-day. `cost_basis` is collapsed to one
  label for the day ('partial' when the day straddles full + dbu_only).
  `cloud_cost` is the classic EC2/EBS cost for the day (CP2, plan §3.2) and
  is `None` for fully-serverless days (no separate VM line — UI renders "—",
  §5); `total_cost` is plumbed straight through from the SQL projection
  rather than computed.
  """

  usage_date: date
  databricks_cost: float
  cost_basis: str
  cloud_cost: Optional[float] = None
  total_cost: float = 0.0
  workspace_covered: bool = True


class GroupedPipeline(BaseModel):
  """Pipeline-level rollup for the By-Pipeline list view.

  One row per pipeline within the queried window (plan §5.1). `days` is the
  single drill-down expansion (plan §3.3). `workload_type` is the
  cost-dominant workload label across the window (sum-then-`max_by`, not the
  largest single row — plan §3.1). `compute_mode` is
  serverless/classic/mixed and `cost_basis` is full/dbu_only/partial; both
  are pre-computed in the rollup and collapsed deterministically on read.

  `metadata_missing` and `pipeline_deleted_at` encode the plan §3.5
  three-state badge: active (both falsy), "Deleted YYYY-MM-DD"
  (`pipeline_deleted_at` set, flag false), "Metadata not available" (flag
  true, `pipeline_deleted_at` NULL — the *expected* state for Vector Search
  etc., rendered neutral, not alarming). `pipeline_name` falls back to
  `Pipeline {pipeline_id}` in the metadata-missing path (plan §5.5).
  `created_by`/`run_as`/`pipeline_type` are None ("Unknown") when absent.
  `total_cloud_cost` is the summed classic EC2/EBS cost across the window
  (CP2, plan §3.2); `None` when the pipeline is fully serverless (no
  separate VM line — UI renders "—" + note, §5), not `$0`.
  """

  workspace_id: str
  pipeline_id: str
  pipeline_name: Optional[str] = None
  pipeline_type: Optional[str] = None
  created_by: Optional[str] = None
  run_as: Optional[str] = None
  workload_type: str
  compute_mode: str
  cost_basis: str
  metadata_missing: bool = False
  pipeline_deleted_at: Optional[datetime] = None
  active_days: int
  total_databricks_cost: float
  total_cloud_cost: Optional[float] = None
  total_cost: float
  workspace_covered: bool = True
  days: list[PipelineDailySpend] = Field(default_factory=list)


class PipelineSummaryMetrics(BaseModel):
  """Summary metrics for the Pipeline Compute tab KPI strip.

  The pipeline-count split is exhaustive of THREE buckets —
  `serverless_pipelines + classic_pipelines + mixed_pipelines ==
  total_pipelines` — so mode-switching pipelines land in `mixed` and are
  never double-counted (plan §5.3). The `$` split is likewise three buckets
  that sum to `total_spend`: `serverless_spend` (full cost) +
  `classic_spend` (DBU only — excludes cloud VM) + `mixed_spend` (partial),
  so the summary footnote stays exact even when mixed rows exist.

  `workload_breakdown` is the per-`workload_type` `$` map (e.g.
  {"DLT Pipeline": ..., "DBSQL Materialized View": ...}); because
  `billing_origin_product` is kept in the rollup grain it is EXACT and
  reconciles row-for-row with staging (no dominant-product approximation —
  plan §3.1/§5.3). `metadata_unavailable` counts only DLT/SQL/Online-Table
  pipelines that *should* carry a `system.lakeflow.pipelines` snapshot but
  don't — workloads that never have metadata (Vector Search) are excluded so
  the number stays meaningful (plan §3.5). `total_cloud_cost` is the summed
  classic EC2/EBS cost across the window (CP2, plan §3.2); `None` when every
  matched pipeline is fully serverless (no separate VM line — KPI hidden),
  not `$0`.
  """

  total_pipelines: int
  serverless_pipelines: int
  classic_pipelines: int
  mixed_pipelines: int
  metadata_unavailable: int
  total_spend: float
  serverless_spend: float
  classic_spend: float
  mixed_spend: float
  total_databricks_cost: float
  total_cloud_cost: Optional[float] = None
  workload_breakdown: dict[str, float] = Field(default_factory=dict)
  date_range_days: int
  dbu_in_non_covered_workspaces: float = 0.0


class PipelineDetails(BaseModel):
  """Pipeline configuration details for the pipeline details modal.

  Sourced from `system.lakeflow.pipelines` (most-recent SCD snapshot via
  QUALIFY ROW_NUMBER() per (workspace_id, pipeline_id) — plan §5.5 / CP6).
  No REST API and no GUID resolution: `created_by`/`run_as` are the
  human-readable values straight from the system table (plan §3.4).
  `workload_type`/`compute_mode`/`cost_basis` are joined in from the rollup
  so the modal can render the workload badge and the DBU-only caveat
  consistently with the list. `metadata_missing=True` indicates no
  `system.lakeflow.pipelines` row was found (normal for Vector Search /
  cross-region); in that case the config fields fall back to None and the
  modal renders the neutral §3.5 banner.
  """

  workspace_id: str
  pipeline_id: str
  pipeline_name: Optional[str] = None
  pipeline_type: Optional[str] = None
  created_by: Optional[str] = None
  run_as: Optional[str] = None
  workload_type: Optional[str] = None
  compute_mode: Optional[str] = None
  cost_basis: Optional[str] = None
  tags: Optional[dict[str, str]] = None
  metadata_missing: bool = False
  pipeline_deleted_at: Optional[datetime] = None


class PipelineAnalysis(BaseModel):
  """LLM-generated cost analysis for a pipeline.

  Returned by `/api/pipelines/{id}/analyze`. The analysis is fed
  `workload_type` + `cost_basis` context so it never gives confidently-wrong
  advice on incomplete numbers — it MUST state the DBU-only caveat when
  `cost_basis != 'full'` and must not recommend cloud-VM changes on numbers
  it knows are DBU-only (plan §4.1 / CP7).
  """

  pipeline_id: str
  analysis: str
  timestamp: str = Field(default_factory=lambda: date.today().isoformat())


class PaginatedPipelines(BaseModel):
  """Paginated response for the By-Pipeline list view."""

  data: list[GroupedPipeline]
  total_count: int
  page: int
  per_page: int
  total_pages: int
  has_next: bool
  has_previous: bool


class ExcludedWorkspace(BaseModel):
  """Workspace with DBU usage but outside the ingested Azure subscription."""

  workspace_id: str
  workspace_name: Optional[str] = None
  dbu_dollars: float


class ExcludedDbuByTab(BaseModel):
  """Per-tab excluded DBU totals (rollup `workspace_covered = false`)."""

  job: float = 0.0
  all_purpose: float = 0.0
  pipeline: float = 0.0
  pool: float = 0.0


class CoverageSummaryResponse(BaseModel):
  """Aggregate subscription-coverage map for banners and KPI segmentation."""

  covered_subscription_ids: list[str]
  covered_workspace_count: int
  excluded_workspaces: list[ExcludedWorkspace]
  excluded_dbu_by_tab: ExcludedDbuByTab
  currency: str = 'USD'

from datetime import date
from typing import Optional, Any
from pydantic import BaseModel, Field, computed_field
from server.config.cloud_platform import cloud_config


class JobSpend(BaseModel):
    """Data model for Databricks job spending records."""

    cluster_id: str
    ec2_cost: float
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
        """Calculate total cost as sum of EC2 and Databricks costs."""
        return self.ec2_cost + self.databricks_cost

    @computed_field
    @property
    def ec2_percentage(self) -> float:
        """Calculate EC2 cost as percentage of total."""
        if self.total_cost == 0:
            return 0.0
        return (self.ec2_cost / self.total_cost) * 100

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
    total_ec2_cost: float
    total_databricks_cost: float
    total_compute_cost: Optional[float] = None
    total_storage_cost: Optional[float] = None
    total_network_cost: Optional[float] = None
    total_other_cost: Optional[float] = None
    classification_coverage_pct: Optional[float] = None
    coverage_status: Optional[str] = None
    coverage_warning: Optional[str] = None
    date_range_days: int


class CostBreakdown(BaseModel):
    """Cost breakdown for individual job."""

    job_id: str
    run_id: str
    cluster_id: str
    usage_date: date
    end_date: Optional[date] = None
    ec2_cost: float
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
        compute = data.get("compute_cost")
        storage = data.get("storage_cost")
        network = data.get("network_cost")
        other = data.get("other_cost")
        has_segmented = compute is not None

        if has_segmented:
            split = [
                {"name": "Compute", "value": float(compute or 0), "color": "#3b82f6"},
                {"name": "Storage", "value": float(storage or 0), "color": "#22c55e"},
                {"name": "Network", "value": float(network or 0), "color": "#f59e0b"},
            ]
            other_val = float(other or 0)
            if other_val > 0:
                split.append({"name": "Other", "value": other_val, "color": "#6b7280"})
            split.append({"name": "Databricks (DBU)", "value": float(data.get("databricks_cost", 0)), "color": "#ef4444"})
            self.cost_split = split
        else:
            self.cost_split = [
                {"name": labels["compute_cost"], "value": self.ec2_cost, "color": "#3b82f6"},
                {"name": labels["databricks_cost"], "value": float(data.get("databricks_cost", 0)), "color": "#ef4444"},
            ]


class JobRun(BaseModel):
    """Individual job run details."""

    run_id: str
    cluster_id: str
    start_date: date
    end_date: date
    ec2_cost: float
    databricks_cost: float
    compute_cost: Optional[float] = None
    storage_cost: Optional[float] = None
    network_cost: Optional[float] = None
    other_cost: Optional[float] = None

    @computed_field
    @property
    def total_cost(self) -> float:
        """Calculate total cost as sum of EC2 and Databricks costs."""
        return self.ec2_cost + self.databricks_cost

    @computed_field
    @property
    def ec2_percentage(self) -> float:
        """Calculate EC2 cost as percentage of total."""
        if self.total_cost == 0:
            return 0.0
        return (self.ec2_cost / self.total_cost) * 100

    @computed_field
    @property
    def databricks_percentage(self) -> float:
        """Calculate Databricks cost as percentage of total."""
        if self.total_cost == 0:
            return 0.0
        return (self.databricks_cost / self.total_cost) * 100


class GroupedJob(BaseModel):
    """Grouped job data with aggregated costs and run details."""

    job_id: str
    job_name: Optional[str] = None
    run_count: int
    total_ec2_cost: float
    total_databricks_cost: float
    total_compute_cost: Optional[float] = None
    total_storage_cost: Optional[float] = None
    total_network_cost: Optional[float] = None
    total_other_cost: Optional[float] = None
    runs: list[JobRun]

    @computed_field
    @property
    def total_cost(self) -> float:
        """Calculate total cost across all runs."""
        return self.total_ec2_cost + self.total_databricks_cost

    @computed_field
    @property
    def ec2_percentage(self) -> float:
        """Calculate EC2 cost as percentage of total."""
        if self.total_cost == 0:
            return 0.0
        return (self.total_ec2_cost / self.total_cost) * 100

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
    dbr_version: Optional[str] = None
    data_security_mode: Optional[str] = None


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


class CoverageTrendPoint(BaseModel):
    """Single data point for classification coverage over time."""

    report_date: date
    coverage_pct: float


class CoverageTrendResponse(BaseModel):
    """Response for classification coverage trend."""

    data: list[CoverageTrendPoint]
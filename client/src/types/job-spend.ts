export interface JobSpend {
  cluster_id: string;
  cloud_cost: number | null;
  job_id: string;
  job_name?: string;
  run_id: string;
  usage_date: string; // ISO date string
  databricks_cost: number;
  total_cost: number;
  cloud_percentage: number;
  databricks_percentage: number;
  compute_cost?: number | null;
  storage_cost?: number | null;
  network_cost?: number | null;
  other_cost?: number | null;
}

export interface SummaryMetrics {
  total_jobs: number;
  total_spend: number;
  average_cost: number;
  max_cost: number;
  min_cost: number;
  total_cloud_cost: number;
  total_databricks_cost: number;
  covered_cloud_cost: number;
  covered_databricks_cost: number;
  uncovered_cloud_cost: number;
  total_compute_cost?: number | null;
  total_storage_cost?: number | null;
  total_network_cost?: number | null;
  total_other_cost?: number | null;
  classification_coverage_pct?: number | null;
  coverage_status?: string | null;
  coverage_warning?: string | null;
  dbu_in_non_covered_workspaces?: number;
  date_range_days: number;
}

export interface CostBreakdown {
  job_id: string;
  run_id: string;
  cluster_id: string;
  cluster_ids: string[];
  usage_date: string;
  end_date?: string | null;
  cloud_cost: number | null;
  databricks_cost: number;
  total_cost: number;
  covered_cloud_cost: number;
  covered_databricks_cost: number;
  uncovered_cloud_cost: number;
  dbu_in_non_covered_workspaces: number;
  compute_cost?: number | null;
  storage_cost?: number | null;
  network_cost?: number | null;
  other_cost?: number | null;
  cost_split: Array<{
    name: string;
    value: number;
    color: string;
  }>;
}

export interface JobRun {
  run_id: string;
  cluster_id: string;
  cluster_ids: string[];
  start_date: string; // ISO date string
  end_date: string; // ISO date string
  cloud_cost: number | null;
  databricks_cost: number;
  total_cost: number;
  cloud_percentage: number;
  databricks_percentage: number;
  compute_cost?: number | null;
  storage_cost?: number | null;
  network_cost?: number | null;
  other_cost?: number | null;
  workspace_covered?: boolean;
}

export interface GroupedJob {
  job_id: string;
  job_name?: string;
  run_count: number;
  total_cloud_cost: number | null;
  total_databricks_cost: number;
  total_compute_cost?: number | null;
  total_storage_cost?: number | null;
  total_network_cost?: number | null;
  total_other_cost?: number | null;
  workspace_covered?: boolean;
  runs: JobRun[];
  total_cost: number;
  cloud_percentage: number;
  databricks_percentage: number;
}

export interface PaginatedJobSpends {
  data: JobSpend[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface PaginatedGroupedJobs {
  data: GroupedJob[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface DateRange {
  start_date: string; // ISO date string
  end_date: string; // ISO date string
}

export interface FeatureFlagsResponse {
  enable_cost_analysis: boolean;
  enable_cluster_analysis: boolean;
  enable_export: boolean;
  enable_job_dbu_breakdown: boolean;
}

export interface JobProductBreakdownItem {
  billing_origin_product: string;
  label: string;
  cost: number;
  percentage: number;
}

export interface JobProductBreakdownResponse {
  job_id: string;
  start_date: string;
  end_date: string;
  items: JobProductBreakdownItem[];
  total_cost: number;
  rollup_databricks_cost?: number | null;
  has_multiple_products: boolean;
  is_estimate: boolean;
  unpriced_warning?: string | null;
}

export interface DatePreset {
  label: string;
  start_date: string;
  end_date: string;
}

export interface JobSpendFilter {
  start_date: string;
  end_date: string;
  job_name?: string;
  page: number;
  per_page: number;
  // Server-side sort for the grouped-job-spends table. Optional so the
  // simpler /job-spends consumers can keep ignoring it.
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

export interface CostAnalysis {
  job_id: string;
  run_id: string;
  analysis: string;
  timestamp: string;
}

export interface ClusterDetails {
  cluster_id: string;
  cluster_name?: string | null;
  cluster_source?: string | null;
  owned_by?: string;
  create_time?: string;
  driver_node_type?: string;
  worker_node_type?: string;
  worker_count?: number;
  min_autoscale_workers?: number;
  max_autoscale_workers?: number;
  auto_termination_minutes?: number;
  enable_elastic_disk?: boolean;
  tags?: Record<string, any>;
  aws_attributes?: Record<string, any> | null;
  azure_attributes?: Record<string, any> | null;
  gcp_attributes?: Record<string, any> | null;
  dbr_version?: string;
  data_security_mode?: string;
}

export interface ClusterAnalysis {
  cluster_id: string;
  analysis: string;
  timestamp: string;
}

export interface CloudPlatformConfig {
  platform: string;
  compute_service: string;
  compute_display_name: string;
  platform_display_name: string;
}

export interface OtherCostBreakdownItem {
  service_name: string;
  cost: number;
  percentage: number;
  source_system: string;
}

export interface OtherCostBreakdownResponse {
  items: OtherCostBreakdownItem[];
  total_other_cost: number;
  start_date: string;
  end_date: string;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  meta?: {
    filters_applied?: Record<string, any>;
    cache_hit?: boolean;
    query_time_ms?: number;
  };
}

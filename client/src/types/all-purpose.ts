// All-Purpose Clusters wire-level types.
//
// Mirrors the Pydantic models added to `server/models/job_spend.py` in CP5
// (search for "All-Purpose cluster models"). Kept hand-written here in
// `client/src/types/` rather than imported from `@/fastapi_client/models`
// so the UI layer stays decoupled from the auto-generated client (matches
// the precedent set by `client/src/types/job-spend.ts`).
//
// See plan §3 (`docs/plan_all_purpose_clusters_tab.md`) for the data model
// rationale (cluster_source filter, owner attribution, no v1 apportionment).

export interface AllPurposeUserSpend {
  cluster_id: string;
  user_id: string;
  usage_date: string; // ISO date string (YYYY-MM-DD)
  // null = no EC2/EBS row matched this cluster-day (e.g. it ran on an
  // instance pool, or Cost Explorer hasn't landed). Rendered as "—".
  cloud_cost: number | null;
  databricks_cost: number;
  compute_cost?: number | null;
  storage_cost?: number | null;
  network_cost?: number | null;
  other_cost?: number | null;
  total_cost: number;
  cloud_percentage: number;
  databricks_percentage: number;
}

export interface AllPurposeClusterSpend {
  cluster_id: string;
  cluster_name?: string | null;
  user_id: string;
  cluster_active_days: number;
  // null = no EC2/EBS row matched this cluster. Rendered as "—".
  cloud_cost: number | null;
  databricks_cost: number;
  compute_cost?: number | null;
  storage_cost?: number | null;
  network_cost?: number | null;
  other_cost?: number | null;
  data_security_mode?: string | null;
  total_cost: number;
  cloud_percentage: number;
  databricks_percentage: number;
}

export interface GroupedAllPurposeCluster {
  cluster_id: string;
  cluster_name?: string | null;
  owner_user_id: string;
  data_security_mode?: string | null;
  active_days: number;
  // null = no EC2/EBS row matched this cluster. Rendered as "—".
  total_cloud_cost: number | null;
  total_databricks_cost: number;
  total_compute_cost?: number | null;
  total_storage_cost?: number | null;
  total_network_cost?: number | null;
  total_other_cost?: number | null;
  // Drill-down expansion: per-day rows for this cluster. Empty on the
  // /top-clusters endpoint (skipped for cost), populated on /grouped-by-cluster.
  users: AllPurposeUserSpend[];
  total_cost: number;
  cloud_percentage: number;
  databricks_percentage: number;
}

export interface GroupedAllPurposeUser {
  user_id: string;
  cluster_count: number;
  // Distinct days the user was active across ALL clusters in the window.
  // Computed from the raw rows, not summed across clusters — see plan §5.2
  // (summing would double-count days where the user used multiple clusters).
  user_active_days: number;
  // null = none of this user's clusters had a matching EC2/EBS row. "—".
  total_cloud_cost: number | null;
  total_databricks_cost: number;
  total_compute_cost?: number | null;
  total_storage_cost?: number | null;
  total_network_cost?: number | null;
  total_other_cost?: number | null;
  // Drill-down expansion: per-cluster rows for this user. Empty on the
  // /top-users endpoint, populated on /grouped-by-user.
  clusters: AllPurposeClusterSpend[];
  total_cost: number;
  cloud_percentage: number;
  databricks_percentage: number;
}

export interface AllPurposeSummaryMetrics {
  total_clusters: number;
  total_users: number;
  total_spend: number;
  // Statistics computed at the (cluster_id, user_id, usage_date) grain —
  // see plan §5.3. Interpretable as "what does a day on a single cluster cost".
  avg_cost_per_cluster_day: number;
  max_cost_per_cluster_day: number;
  min_cost_per_cluster_day: number;
  total_cloud_cost: number;
  total_databricks_cost: number;
  total_compute_cost?: number | null;
  total_storage_cost?: number | null;
  total_network_cost?: number | null;
  total_other_cost?: number | null;
  date_range_days: number;
}

export interface PaginatedAllPurposeClusters {
  data: GroupedAllPurposeCluster[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface PaginatedAllPurposeUsers {
  data: GroupedAllPurposeUser[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

// Filter shape passed to the paginated endpoints. Parallels
// `JobSpendFilter` in `./job-spend.ts`. `search` is a single free-text field
// that the backend matches against cluster_name + cluster_id + owner_user_id
// (cluster query) or user_id (user query).
export interface AllPurposeFilter {
  start_date: string;
  end_date: string;
  search?: string;
  page: number;
  per_page: number;
}

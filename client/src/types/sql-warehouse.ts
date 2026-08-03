// SQL Warehouses wire-level types.
//
// Mirrors the Pydantic models in `server/models/job_spend.py` (search for
// "SQL Warehouse models"). Hand-written here rather than imported from
// `@/fastapi_client/models` so the UI layer stays decoupled from the
// auto-generated client — same precedent as `./pipeline.ts` and
// `./instance-pool.ts`.
//
// Two structural differences vs. the Pipeline Compute tab
// (`docs/plans/sql-warehouse-costs.md`):
//   - DBU IS the complete cost. All three warehouse types (CLASSIC, PRO,
//     SERVERLESS) run on Databricks-managed compute, so there are no customer
//     VMs to attribute cloud cost to and no cloud-cost field exists anywhere.
//   - `warehouse_id` is account-unique, so nothing is keyed by workspace and
//     there is no cross-workspace disambiguation (no 409 path).

// One row per warehouse-day inside a warehouse's `days` array. The rollup is
// already at `(warehouse_id, usage_date)` grain, so no server-side summing is
// needed before nesting.
export interface SqlWarehouseDailySpend {
  usage_date: string; // ISO date string (YYYY-MM-DD)
  databricks_cost: number;
  total_cost: number;
  warehouse_type?: string | null;
  sku_name?: string | null;
}

// Top-level warehouse row in the By-Warehouse table.
//
// `metadata_missing` + `warehouse_deleted_at` encode the three-state badge:
//   - active                  : both falsy
//   - "Deleted YYYY-MM-DD"    : `warehouse_deleted_at` populated
//   - "Metadata unavailable"  : flag true — the common case (~77% of
//     warehouses have no `system.compute.warehouses` snapshot), so it renders
//     neutral grey, not as a warning. Cost figures stay accurate either way.
export interface GroupedSqlWarehouse {
  warehouse_id: string;
  warehouse_name?: string | null;
  warehouse_type?: string | null; // 'CLASSIC' | 'PRO' | 'SERVERLESS'
  warehouse_size?: string | null;
  creator_id?: string | null;
  auto_stop_mins?: number | null;
  min_clusters?: number | null;
  max_clusters?: number | null;
  metadata_missing: boolean;
  // ISO datetime string when populated.
  warehouse_deleted_at?: string | null;
  active_days: number;
  total_databricks_cost: number;
  total_cost: number;
  workspace_covered?: boolean;
  // Drill-down expansion. Populated on `/grouped`, empty on
  // `/top-warehouses` (which skips the per-day query for cost).
  days: SqlWarehouseDailySpend[];
}

// KPI strip metrics.
//
// Both splits are exhaustive three-bucket splits:
//   classic_warehouses + pro_warehouses + serverless_warehouses ==
//     total_warehouses
//   classic_spend + pro_spend + serverless_spend == total_spend
// `total_spend` equals `total_databricks_cost` by construction — there is no
// cloud component on this tab.
export interface SqlWarehouseSummaryMetrics {
  total_warehouses: number;
  classic_warehouses: number;
  pro_warehouses: number;
  serverless_warehouses: number;
  total_spend: number;
  classic_spend: number;
  pro_spend: number;
  serverless_spend: number;
  total_databricks_cost: number;
  date_range_days: number;
  dbu_in_non_covered_workspaces?: number;
}

// Warehouse configuration for the details modal, denormalized from
// `system.compute.warehouses` into the rollup. `metadata_missing=true` leaves
// every config field null and drives the modal's neutral banner.
export interface SqlWarehouseDetails {
  warehouse_id: string;
  warehouse_name?: string | null;
  warehouse_type?: string | null;
  warehouse_size?: string | null;
  creator_id?: string | null;
  auto_stop_mins?: number | null;
  min_clusters?: number | null;
  max_clusters?: number | null;
  metadata_missing: boolean;
  warehouse_deleted_at?: string | null;
  tags?: Record<string, string> | null;
}

// LLM-generated cost analysis for a single warehouse.
export interface SqlWarehouseAnalysis {
  warehouse_id: string;
  analysis: string;
  timestamp: string;
}

export interface PaginatedSqlWarehouses {
  data: GroupedSqlWarehouse[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

// Filter shape passed to the paginated `/grouped` endpoint. `search` is a
// single free-text field the backend matches against warehouse_name
// (case-insensitive substring) and warehouse_id (exact). There is no
// workload-type chip filter on this tab.
export interface SqlWarehouseFilter {
  start_date: string;
  end_date: string;
  search?: string;
  page: number;
  per_page: number;
}

// React Query hooks for the SQL Warehouses tab.
//
// Mirrors the pipeline hook surface in `./usePipelines.ts` (paginated table +
// adjacent-page prefetch, KPI summary, top-N flat list, per-warehouse details
// + LLM analysis for the modal), minus the `workload_type` chip filter and
// minus the `workspace_id` disambiguation — `warehouse_id` is account-unique.
// Endpoint methods live on `apiClient` (`client/src/lib/api-client.ts`).
//
// See plan §3d (`docs/plans/sql-warehouse-costs.md`).

import { useEffect } from 'react';
import {
  useQuery,
  useQueryClient,
  keepPreviousData,
  type QueryKey,
} from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import { canQueryRange } from '@/lib/utils';
import type { DateRange } from '@/types/job-spend';
import type {
  PaginatedSqlWarehouses,
  SqlWarehouseFilter,
} from '@/types/sql-warehouse';

// Match the staleness window used by the other four tabs so all five behave
// identically when the user pivots between them.
const STALE_TIME_MS = 5 * 60 * 1000;

// Warehouse config (from `system.compute.warehouses`) doesn't shift often;
// align with the cluster/pool/pipeline caches so the modal feels equally
// snappy on second open.
const DETAILS_STALE_TIME_MS = 30 * 60 * 1000;
const ANALYSIS_STALE_TIME_MS = 60 * 60 * 1000;

const groupedQueryKey = (params: SqlWarehouseFilter): QueryKey => [
  'sql-warehouses-grouped',
  params,
];

// Hook: paginated By-Warehouse table (`/api/warehouses/grouped`).
// Adjacent-page prefetch matches `usePipelines` so Next/Previous clicks render
// from cache without a spinner round-trip.
export const useSqlWarehouses = (params: SqlWarehouseFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery<PaginatedSqlWarehouses>({
    queryKey: groupedQueryKey(params),
    queryFn: () => apiClient.getSqlWarehouses(params),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    enabled: canQueryRange(params.start_date, params.end_date),
  });

  const totalPages = query.data?.total_pages ?? 0;
  const currentPage = params.page;

  useEffect(() => {
    if (!query.data || totalPages <= 1) return;

    const adjacent: number[] = [];
    if (currentPage + 1 <= totalPages) adjacent.push(currentPage + 1);
    if (currentPage - 1 >= 1) adjacent.push(currentPage - 1);

    adjacent.forEach((page) => {
      const adjacentParams: SqlWarehouseFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: groupedQueryKey(adjacentParams),
        queryFn: () => apiClient.getSqlWarehouses(adjacentParams),
        staleTime: STALE_TIME_MS,
      });
    });
  }, [
    queryClient,
    query.data,
    totalPages,
    currentPage,
    params.start_date,
    params.end_date,
    params.per_page,
    params.search,
  ]);

  return query;
};

// Hook: KPI strip (`/api/warehouses/summary`).
export const useSqlWarehouseSummary = (dateRange: DateRange) => {
  return useQuery({
    queryKey: ['sql-warehouses-summary', dateRange],
    queryFn: () => apiClient.getSqlWarehouseSummary(dateRange),
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    enabled: canQueryRange(dateRange.start_date, dateRange.end_date),
  });
};

// Hook: top-N most expensive warehouses (`/api/warehouses/top-warehouses`).
// Server caps `limit` at 20. Rows come back flat (`days: []`).
export const useTopSqlWarehouses = (
  dateRange: DateRange,
  limit: number = 5,
) => {
  return useQuery({
    queryKey: ['sql-warehouses-top-warehouses', dateRange, limit],
    queryFn: () => apiClient.getTopSqlWarehouses(dateRange, limit),
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    enabled: canQueryRange(dateRange.start_date, dateRange.end_date),
  });
};

// Hook: warehouse configuration for the details modal
// (`/api/warehouses/{id}/details`). The backend returns a
// `metadata_missing=true` sentinel rather than raising when no rollup row
// exists, so an unknown id renders the neutral banner instead of an error.
export const useSqlWarehouseDetails = (warehouseId: string | null) => {
  return useQuery({
    queryKey: ['sql-warehouse-details', warehouseId],
    queryFn: () => apiClient.getSqlWarehouseDetails(warehouseId!),
    staleTime: DETAILS_STALE_TIME_MS,
    enabled: !!warehouseId,
  });
};

// Hook: LLM-powered warehouse cost analysis
// (`/api/warehouses/{id}/analyze`). `enabled` lets the caller defer the
// (LLM-charging) request until details resolve successfully, so a failed
// lookup never fires analysis.
export const useSqlWarehouseAnalysis = (
  warehouseId: string | null,
  options?: { enabled?: boolean },
) => {
  return useQuery({
    queryKey: ['sql-warehouse-analysis', warehouseId],
    queryFn: () => apiClient.getSqlWarehouseAnalysis(warehouseId!),
    staleTime: ANALYSIS_STALE_TIME_MS,
    enabled: !!warehouseId && (options?.enabled ?? true),
  });
};

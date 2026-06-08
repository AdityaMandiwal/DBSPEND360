// React Query hooks for the All-Purpose Clusters tab.
//
// Mirrors the job-cluster hook surface across `useJobSpends.ts` (simple
// queries) and `useGroupedJobSpends.ts` (paginated + adjacent-page prefetch).
// Endpoint methods live on `apiClient` (`client/src/lib/api-client.ts`).
//
// See plan §4.1 / CP9 (`docs/plan_all_purpose_clusters_tab.md`).

import { useEffect } from 'react';
import {
  useQuery,
  useQueryClient,
  keepPreviousData,
  type QueryKey,
} from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import type { DateRange } from '@/types/job-spend';
import type {
  AllPurposeFilter,
  PaginatedAllPurposeClusters,
  PaginatedAllPurposeUsers,
} from '@/types/all-purpose';

// Match the staleness window used by the job-cluster hooks so the two tabs
// behave identically when the user pivots between them.
const STALE_TIME_MS = 5 * 60 * 1000;

const byClusterQueryKey = (params: AllPurposeFilter): QueryKey => [
  'all-purpose-grouped-by-cluster',
  params,
];

const byUserQueryKey = (params: AllPurposeFilter): QueryKey => [
  'all-purpose-grouped-by-user',
  params,
];

// Hook: paginated By-Cluster table (`/api/all-purpose/grouped-by-cluster`).
// Adjacent-page prefetch matches `useGroupedJobSpends` so Next/Previous
// clicks render from cache without a spinner round-trip.
export const useAllPurposeClustersByCluster = (params: AllPurposeFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery<PaginatedAllPurposeClusters>({
    queryKey: byClusterQueryKey(params),
    queryFn: () => apiClient.getAllPurposeGroupedByCluster(params),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    enabled: !!(params.start_date && params.end_date),
  });

  const totalPages = query.data?.total_pages ?? 0;
  const currentPage = params.page;

  useEffect(() => {
    if (!query.data || totalPages <= 1) return;

    const adjacent: number[] = [];
    if (currentPage + 1 <= totalPages) adjacent.push(currentPage + 1);
    if (currentPage - 1 >= 1) adjacent.push(currentPage - 1);

    adjacent.forEach((page) => {
      const adjacentParams: AllPurposeFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: byClusterQueryKey(adjacentParams),
        queryFn: () => apiClient.getAllPurposeGroupedByCluster(adjacentParams),
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

// Hook: paginated By-User chargeback table (`/api/all-purpose/grouped-by-user`).
// Same adjacent-page prefetch as the By-Cluster hook.
export const useAllPurposeClustersByUser = (params: AllPurposeFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery<PaginatedAllPurposeUsers>({
    queryKey: byUserQueryKey(params),
    queryFn: () => apiClient.getAllPurposeGroupedByUser(params),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    enabled: !!(params.start_date && params.end_date),
  });

  const totalPages = query.data?.total_pages ?? 0;
  const currentPage = params.page;

  useEffect(() => {
    if (!query.data || totalPages <= 1) return;

    const adjacent: number[] = [];
    if (currentPage + 1 <= totalPages) adjacent.push(currentPage + 1);
    if (currentPage - 1 >= 1) adjacent.push(currentPage - 1);

    adjacent.forEach((page) => {
      const adjacentParams: AllPurposeFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: byUserQueryKey(adjacentParams),
        queryFn: () => apiClient.getAllPurposeGroupedByUser(adjacentParams),
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

// Hook: KPI strip (`/api/all-purpose/summary`). Mirrors `useSummaryMetrics`.
export const useAllPurposeSummary = (dateRange: DateRange) => {
  return useQuery({
    queryKey: ['all-purpose-summary', dateRange],
    queryFn: () => apiClient.getAllPurposeSummaryMetrics(dateRange),
    staleTime: STALE_TIME_MS,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

// Hook: top-N most expensive clusters (`/api/all-purpose/top-clusters`).
// Mirrors `useTopJobs`. Server caps `limit` at 20.
export const useAllPurposeTopClusters = (
  dateRange: DateRange,
  limit: number = 5,
) => {
  return useQuery({
    queryKey: ['all-purpose-top-clusters', dateRange, limit],
    queryFn: () => apiClient.getAllPurposeTopClusters(dateRange, limit),
    staleTime: STALE_TIME_MS,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

// Hook: top-N most expensive users (`/api/all-purpose/top-users`). Chargeback
// counterpart to `useAllPurposeTopClusters`.
export const useAllPurposeTopUsers = (
  dateRange: DateRange,
  limit: number = 5,
) => {
  return useQuery({
    queryKey: ['all-purpose-top-users', dateRange, limit],
    queryFn: () => apiClient.getAllPurposeTopUsers(dateRange, limit),
    staleTime: STALE_TIME_MS,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

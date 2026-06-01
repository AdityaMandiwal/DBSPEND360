import { useEffect } from "react";
import {
  useQuery,
  useQueryClient,
  keepPreviousData,
  type QueryKey,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type {
  DateRange,
  SharedClusterFilter,
  PaginatedSharedClusters,
} from "@/types/job-spend";

const STALE_TIME_MS = 5 * 60 * 1000;

const queryKeyFor = (params: SharedClusterFilter): QueryKey => [
  "shared-clusters",
  params,
];

/**
 * Paginated list of shared / interactive clusters. Mirrors the
 * `useGroupedJobSpends` ergonomics: keeps the previous page on screen
 * during refetches and prefetches the adjacent pages so Prev/Next clicks
 * feel instant.
 */
export const useSharedClusters = (params: SharedClusterFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery<PaginatedSharedClusters>({
    queryKey: queryKeyFor(params),
    queryFn: () => apiClient.getSharedClusters(params),
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
      const adjacentParams: SharedClusterFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: queryKeyFor(adjacentParams),
        queryFn: () => apiClient.getSharedClusters(adjacentParams),
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
    params.owner,
    params.search,
  ]);

  return query;
};

export const useSharedClusterSummary = (dateRange: DateRange) => {
  return useQuery({
    queryKey: ["shared-cluster-summary", dateRange],
    queryFn: () => apiClient.getSharedClusterSummary(dateRange),
    staleTime: STALE_TIME_MS,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

export const useClusterDailyTrend = (
  clusterId: string | null,
  dateRange: DateRange,
) => {
  return useQuery({
    queryKey: ["cluster-daily-trend", clusterId, dateRange],
    queryFn: () =>
      apiClient.getClusterDailyTrend(clusterId as string, dateRange),
    staleTime: STALE_TIME_MS,
    enabled: !!(clusterId && dateRange.start_date && dateRange.end_date),
  });
};

export const useClusterSpendBreakdown = (
  clusterId: string | null,
  dateRange: DateRange,
) => {
  return useQuery({
    queryKey: ["cluster-spend-breakdown", clusterId, dateRange],
    queryFn: () =>
      apiClient.getClusterSpendBreakdown(clusterId as string, dateRange),
    staleTime: STALE_TIME_MS,
    enabled: !!(clusterId && dateRange.start_date && dateRange.end_date),
    retry: false,
  });
};

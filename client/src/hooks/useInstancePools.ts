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
  InstancePoolFilter,
  PaginatedInstancePools,
} from "@/types/job-spend";

const STALE_TIME_MS = 5 * 60 * 1000;

const queryKeyFor = (params: InstancePoolFilter): QueryKey => [
  "instance-pools",
  params,
];

/**
 * Paginated list of Databricks instance pools. Mirrors `useSharedClusters`:
 * keeps the previous page on screen during refetches and prefetches the
 * adjacent pages so Prev/Next clicks feel instant.
 */
export const useInstancePools = (params: InstancePoolFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery<PaginatedInstancePools>({
    queryKey: queryKeyFor(params),
    queryFn: () => apiClient.getInstancePools(params),
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
      const adjacentParams: InstancePoolFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: queryKeyFor(adjacentParams),
        queryFn: () => apiClient.getInstancePools(adjacentParams),
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

export const useInstancePoolsSummary = (dateRange: DateRange) => {
  return useQuery({
    queryKey: ["instance-pools-summary", dateRange],
    queryFn: () => apiClient.getInstancePoolsSummary(dateRange),
    staleTime: STALE_TIME_MS,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

export const useInstancePoolBreakdown = (
  poolId: string | null,
  dateRange: DateRange,
) => {
  return useQuery({
    queryKey: ["instance-pool-breakdown", poolId, dateRange],
    queryFn: () =>
      apiClient.getInstancePoolBreakdown(poolId as string, dateRange),
    staleTime: STALE_TIME_MS,
    enabled: !!(poolId && dateRange.start_date && dateRange.end_date),
    retry: false,
  });
};

export const useInstancePoolAttachedClusters = (poolId: string | null) => {
  return useQuery({
    queryKey: ["instance-pool-attached-clusters", poolId],
    queryFn: () => apiClient.getInstancePoolAttachedClusters(poolId as string),
    staleTime: STALE_TIME_MS,
    enabled: !!poolId,
  });
};

export const useInstancePoolAnalysis = (poolId: string | null) => {
  return useQuery({
    queryKey: ["instance-pool-analysis", poolId],
    // LLM analysis is steady — match `useClusterAnalysis` 1h staleness
    // so opening the modal a second time doesn't replay the model.
    queryFn: () => apiClient.getInstancePoolAnalysis(poolId as string),
    staleTime: 60 * 60 * 1000,
    enabled: !!poolId,
  });
};

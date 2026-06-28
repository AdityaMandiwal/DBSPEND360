// React Query hooks for the Instance Pools tab.
//
// Mirrors the all-purpose hook surface in `./useAllPurposeClusters.ts`
// (paginated table + adjacent-page prefetch, KPI summary, top-N flat
// list) and adds two cluster-style per-pool hooks (`useInstancePoolDetails`,
// `useInstancePoolAnalysis`) for the pool details modal. Endpoint methods
// live on `apiClient` (`client/src/lib/api-client.ts`).
//
// See plan §4.1 / CP9 (`docs/plan_instance_pools_tab.md`).

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
  InstancePoolFilter,
  PaginatedInstancePools,
} from '@/types/instance-pool';

// Match the staleness window used by the job-cluster and all-purpose
// hooks so all three tabs behave identically when the user pivots
// between them.
const STALE_TIME_MS = 5 * 60 * 1000;

// Pool config + the per-request REST-resolved creator GUID don't shift
// often; align with the existing cluster-details / cluster-analysis
// caches so the modal feels equally snappy on second open.
const DETAILS_STALE_TIME_MS = 30 * 60 * 1000;
const ANALYSIS_STALE_TIME_MS = 60 * 60 * 1000;

const groupedQueryKey = (params: InstancePoolFilter): QueryKey => [
  'instance-pools-grouped',
  params,
];

// Hook: paginated By-Pool table (`/api/instance-pools/grouped`).
// Adjacent-page prefetch matches `useGroupedJobSpends` /
// `useAllPurposeClustersByCluster` so Next/Previous clicks render from
// cache without a spinner round-trip.
export const useInstancePools = (params: InstancePoolFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery<PaginatedInstancePools>({
    queryKey: groupedQueryKey(params),
    queryFn: () => apiClient.getInstancePools(params),
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
      const adjacentParams: InstancePoolFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: groupedQueryKey(adjacentParams),
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

// Hook: KPI strip (`/api/instance-pools/summary`). Mirrors
// `useAllPurposeSummary` / `useSummaryMetrics`.
export const useInstancePoolSummary = (dateRange: DateRange) => {
  return useQuery({
    queryKey: ['instance-pools-summary', dateRange],
    queryFn: () => apiClient.getInstancePoolSummary(dateRange),
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    enabled: canQueryRange(dateRange.start_date, dateRange.end_date),
  });
};

// Hook: top-N most expensive pools (`/api/instance-pools/top-pools`).
// Mirrors `useAllPurposeTopClusters` / `useTopJobs`. Server caps `limit`
// at 20.
export const useTopInstancePools = (
  dateRange: DateRange,
  limit: number = 5,
) => {
  return useQuery({
    queryKey: ['instance-pools-top-pools', dateRange, limit],
    queryFn: () => apiClient.getTopInstancePools(dateRange, limit),
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    enabled: canQueryRange(dateRange.start_date, dateRange.end_date),
  });
};

// Hook: pool configuration details for the pool details modal
// (`/api/instance-pools/{id}/details`). Mirrors `useClusterDetails`.
// The response includes the REST-resolved creator GUID — see plan §3.4
// for why this surfaces only in the modal (not the list).
export const useInstancePoolDetails = (poolId: string) => {
  return useQuery({
    queryKey: ['instance-pool-details', poolId],
    queryFn: () => apiClient.getInstancePoolDetails(poolId),
    staleTime: DETAILS_STALE_TIME_MS,
    enabled: !!poolId,
  });
};

// Hook: LLM-powered pool configuration analysis
// (`/api/instance-pools/{id}/analyze`). Mirrors `useClusterAnalysis`.
// As of CP8 the analysis includes real pool EC2/EBS cost; the only caveat
// it carries is that the idle-vs-active VM cost split is not available yet
// (plan_pool_pipeline_ec2_cost.md §4.5).
export const useInstancePoolAnalysis = (poolId: string) => {
  return useQuery({
    queryKey: ['instance-pool-analysis', poolId],
    queryFn: () => apiClient.getInstancePoolAnalysis(poolId),
    staleTime: ANALYSIS_STALE_TIME_MS,
    enabled: !!poolId,
  });
};

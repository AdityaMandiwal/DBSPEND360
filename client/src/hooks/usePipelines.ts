// React Query hooks for the Pipeline Compute tab.
//
// Mirrors the instance-pools hook surface in `./useInstancePools.ts`
// (paginated table + adjacent-page prefetch, KPI summary, top-N flat list,
// per-pipeline details + LLM analysis for the modal). Endpoint methods live
// on `apiClient` (`client/src/lib/api-client.ts`).
//
// See plan §4.1 / CP9 (`docs/plan_dlt_tab.md`).

import { useEffect } from 'react';
import {
  useQuery,
  useQueryClient,
  keepPreviousData,
  type QueryKey,
} from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import type { DateRange } from '@/types/job-spend';
import type { PipelineFilter, PaginatedPipelines } from '@/types/pipeline';

// Match the staleness window used by the other three tabs so all four
// behave identically when the user pivots between them.
const STALE_TIME_MS = 5 * 60 * 1000;

// Pipeline config (from `system.lakeflow.pipelines`) doesn't shift often;
// align with the cluster/pool details + analysis caches so the modal feels
// equally snappy on second open.
const DETAILS_STALE_TIME_MS = 30 * 60 * 1000;
const ANALYSIS_STALE_TIME_MS = 60 * 60 * 1000;

const groupedQueryKey = (params: PipelineFilter): QueryKey => [
  'pipelines-grouped',
  params,
];

// Hook: paginated By-Pipeline table (`/api/pipelines/grouped`).
// Adjacent-page prefetch matches `useInstancePools` so Next/Previous clicks
// render from cache without a spinner round-trip. The `workload_type` chip
// selection is part of the query key, so changing chips refetches cleanly.
export const usePipelines = (params: PipelineFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery<PaginatedPipelines>({
    queryKey: groupedQueryKey(params),
    queryFn: () => apiClient.getPipelines(params),
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
      const adjacentParams: PipelineFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: groupedQueryKey(adjacentParams),
        queryFn: () => apiClient.getPipelines(adjacentParams),
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
    // Re-key the prefetch when the chip selection changes. Joined to a
    // stable string so the dep array compares by value, not reference.
    params.workload_type?.join(','),
  ]);

  return query;
};

// Hook: KPI strip (`/api/pipelines/summary`). Mirrors
// `useInstancePoolSummary`. `workloadType` narrows the summary to the
// selected chips (never drops spend — plan §3.1) and is part of the key.
export const usePipelineSummary = (
  dateRange: DateRange,
  workloadType?: string[],
) => {
  return useQuery({
    queryKey: ['pipelines-summary', dateRange, workloadType ?? null],
    queryFn: () => apiClient.getPipelineSummary(dateRange, workloadType),
    staleTime: STALE_TIME_MS,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

// Hook: top-N most expensive pipelines (`/api/pipelines/top-pipelines`).
// Mirrors `useTopInstancePools`. Server caps `limit` at 20. `workloadType`
// narrows the card in lock-step with the KPI strip and table (plan §3.1) and
// is part of the query key so toggling chips refetches cleanly.
export const useTopPipelines = (
  dateRange: DateRange,
  limit: number = 5,
  workloadType?: string[],
) => {
  return useQuery({
    queryKey: ['pipelines-top-pipelines', dateRange, limit, workloadType ?? null],
    queryFn: () => apiClient.getTopPipelines(dateRange, limit, workloadType),
    staleTime: STALE_TIME_MS,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

// Hook: pipeline configuration details for the pipeline details modal
// (`/api/pipelines/{id}/details`). Mirrors `useInstancePoolDetails`.
// `workspaceId` disambiguates a `pipeline_id` that spans >1 workspace
// (plan §3.3/§6); omit it on the single-workspace dev path.
export const usePipelineDetails = (
  pipelineId: string,
  workspaceId?: string,
) => {
  return useQuery({
    queryKey: ['pipeline-details', pipelineId, workspaceId ?? null],
    queryFn: () => apiClient.getPipelineDetails(pipelineId, workspaceId),
    staleTime: DETAILS_STALE_TIME_MS,
    enabled: !!pipelineId,
  });
};

// Hook: LLM-powered pipeline cost analysis
// (`/api/pipelines/{id}/analyze`). Mirrors `useInstancePoolAnalysis`. The
// analysis text is expected to include the DBU-only caveat iff
// `cost_basis != 'full'` (plan §3.2 / §9 acceptance criterion #14).
export const usePipelineAnalysis = (
  pipelineId: string,
  workspaceId?: string,
) => {
  return useQuery({
    queryKey: ['pipeline-analysis', pipelineId, workspaceId ?? null],
    queryFn: () => apiClient.getPipelineAnalysis(pipelineId, workspaceId),
    staleTime: ANALYSIS_STALE_TIME_MS,
    enabled: !!pipelineId,
  });
};

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { canQueryRange } from "@/lib/utils";
import {
  JobSpendFilter,
  DateRange,
  OtherCostBreakdownResponse,
} from "@/types/job-spend";

// Resolves the active AI model's display label from /api/ai-info so the
// "Powered by ..." badges aren't hard-coded. Falls back to "Claude Sonnet 4"
// while loading or if the endpoint is unavailable, so the badge always renders.
export const useAiModelLabel = (): string => {
  const { data } = useQuery({
    queryKey: ["ai-info"],
    queryFn: () => apiClient.getAiInfo(),
    staleTime: Infinity,
    retry: false,
  });
  return data?.model_label ?? "Claude Sonnet 4";
};

export const useJobSpends = (filter: JobSpendFilter) => {
  return useQuery({
    queryKey: ["job-spends", filter],
    queryFn: () => apiClient.getJobSpends(filter),
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: canQueryRange(filter.start_date, filter.end_date),
  });
};

export const useSummaryMetrics = (dateRange: DateRange) => {
  return useQuery({
    queryKey: ["summary-metrics", dateRange],
    queryFn: () => apiClient.getSummaryMetrics(dateRange),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
    enabled: canQueryRange(dateRange.start_date, dateRange.end_date),
  });
};

export const useJobBreakdown = (
  jobId: string,
  runId: string,
  dateRange: DateRange,
) => {
  return useQuery({
    queryKey: ["job-breakdown", jobId, runId, dateRange],
    queryFn: () => apiClient.getJobCostBreakdown(jobId, runId, dateRange),
    staleTime: 30 * 60 * 1000, // 30 minutes - breakdown data is less likely to change
    enabled: !!(jobId && runId),
  });
};

export const useJobCostAnalysis = (
  jobId: string,
  runId: string,
  dateRange: DateRange,
  enabled: boolean = true,
) => {
  return useQuery({
    queryKey: ["job-cost-analysis", jobId, runId, dateRange],
    queryFn: () => apiClient.getJobCostAnalysis(jobId, runId, dateRange),
    staleTime: 60 * 60 * 1000, // 1 hour - LLM analysis doesn't change frequently
    enabled: enabled && !!(jobId && runId),
  });
};

export const useClusterDetails = (clusterId: string) => {
  return useQuery({
    queryKey: ["cluster-details", clusterId],
    queryFn: () => apiClient.getClusterDetails(clusterId),
    staleTime: 30 * 60 * 1000, // 30 minutes - cluster config doesn't change often
    enabled: !!clusterId,
  });
};

export const useClusterAnalysis = (
  clusterId: string,
  clusterKind?: "job" | "all_purpose",
  enabled: boolean = true,
) => {
  return useQuery({
    // `clusterKind ?? 'auto'` keeps the React Query cache key stable
    // for the auto-detect path (Instance Pools drill-down) so two
    // pool clusters with different resolved kinds don't collide on
    // an `undefined` cache slot.
    queryKey: ["cluster-analysis", clusterId, clusterKind ?? "auto"],
    queryFn: () => apiClient.getClusterAnalysis(clusterId, clusterKind),
    staleTime: 60 * 60 * 1000, // 1 hour - LLM analysis doesn't change frequently
    enabled: enabled && !!clusterId,
  });
};

export const useTopJobs = (dateRange: DateRange, limit: number = 5) => {
  return useQuery({
    queryKey: ["top-jobs", dateRange, limit],
    queryFn: () => apiClient.getTopJobs(dateRange, limit),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
    enabled: canQueryRange(dateRange.start_date, dateRange.end_date),
  });
};

export const useDatePresets = () => {
  return useQuery({
    queryKey: ["date-presets"],
    queryFn: () => apiClient.getDatePresets(),
    staleTime: 60 * 60 * 1000, // 1 hour - presets don't change often
  });
};

export const useOtherCostBreakdown = (
  dateRange: DateRange,
  clusterId?: string,
  jobId?: string,
  runId?: string,
  clusterKind?: "job" | "all_purpose",
  enabled: boolean = true,
) => {
  return useQuery<OtherCostBreakdownResponse>({
    queryKey: [
      "other-cost-breakdown",
      dateRange,
      clusterId,
      jobId,
      runId,
      clusterKind,
    ],
    queryFn: () =>
      apiClient.getOtherCostBreakdown(
        dateRange,
        clusterId,
        jobId,
        runId,
        clusterKind,
      ),
    staleTime: 5 * 60 * 1000,
    enabled: enabled && canQueryRange(dateRange.start_date, dateRange.end_date),
  });
};

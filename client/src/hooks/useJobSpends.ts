import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import { JobSpendFilter, DateRange, OtherCostBreakdownResponse, CoverageTrendResponse } from '@/types/job-spend';

export const useJobSpends = (filter: JobSpendFilter) => {
  return useQuery({
    queryKey: ['job-spends', filter],
    queryFn: () => apiClient.getJobSpends(filter),
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: !!(filter.start_date && filter.end_date),
  });
};

export const useSummaryMetrics = (dateRange: DateRange) => {
  return useQuery({
    queryKey: ['summary-metrics', dateRange],
    queryFn: () => apiClient.getSummaryMetrics(dateRange),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

export const useJobBreakdown = (jobId: string, runId: string) => {
  return useQuery({
    queryKey: ['job-breakdown', jobId, runId],
    queryFn: () => apiClient.getJobCostBreakdown(jobId, runId),
    staleTime: 30 * 60 * 1000, // 30 minutes - breakdown data is less likely to change
    enabled: !!(jobId && runId),
  });
};

export const useJobCostAnalysis = (jobId: string, runId: string) => {
  return useQuery({
    queryKey: ['job-cost-analysis', jobId, runId],
    queryFn: () => apiClient.getJobCostAnalysis(jobId, runId),
    staleTime: 60 * 60 * 1000, // 1 hour - LLM analysis doesn't change frequently
    enabled: !!(jobId && runId),
  });
};

export const useClusterDetails = (clusterId: string) => {
  return useQuery({
    queryKey: ['cluster-details', clusterId],
    queryFn: () => apiClient.getClusterDetails(clusterId),
    staleTime: 30 * 60 * 1000, // 30 minutes - cluster config doesn't change often
    enabled: !!clusterId,
  });
};

export const useClusterAnalysis = (
  clusterId: string,
  clusterKind?: 'job' | 'all_purpose',
) => {
  return useQuery({
    // `clusterKind ?? 'auto'` keeps the React Query cache key stable
    // for the auto-detect path (Instance Pools drill-down) so two
    // pool clusters with different resolved kinds don't collide on
    // an `undefined` cache slot.
    queryKey: ['cluster-analysis', clusterId, clusterKind ?? 'auto'],
    queryFn: () => apiClient.getClusterAnalysis(clusterId, clusterKind),
    staleTime: 60 * 60 * 1000, // 1 hour - LLM analysis doesn't change frequently
    enabled: !!clusterId,
  });
};

export const useTopJobs = (dateRange: DateRange, limit: number = 5) => {
  return useQuery({
    queryKey: ['top-jobs', dateRange, limit],
    queryFn: () => apiClient.getTopJobs(dateRange, limit),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
    enabled: !!(dateRange.start_date && dateRange.end_date),
  });
};

export const useDatePresets = () => {
  return useQuery({
    queryKey: ['date-presets'],
    queryFn: () => apiClient.getDatePresets(),
    staleTime: 60 * 60 * 1000, // 1 hour - presets don't change often
  });
};

export const useOtherCostBreakdown = (
  dateRange: DateRange,
  clusterId?: string,
  enabled: boolean = true,
) => {
  return useQuery<OtherCostBreakdownResponse>({
    queryKey: ['other-cost-breakdown', dateRange, clusterId],
    queryFn: () => apiClient.getOtherCostBreakdown(dateRange, clusterId),
    staleTime: 5 * 60 * 1000,
    enabled: enabled && !!(dateRange.start_date && dateRange.end_date),
  });
};

export const useCoverageTrend = (dateRange?: DateRange) => {
  return useQuery<CoverageTrendResponse>({
    queryKey: ['coverage-trend', dateRange?.start_date, dateRange?.end_date],
    queryFn: () => apiClient.getCoverageTrend(dateRange),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
};
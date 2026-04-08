import { JobSpend, SummaryMetrics, CostBreakdown, PaginatedJobSpends, DateRange, JobSpendFilter, DatePreset, CostAnalysis, ClusterDetails, ClusterAnalysis, CloudPlatformConfig, OtherCostBreakdownResponse, CoverageTrendResponse } from '@/types/job-spend';
import { API_BASE_URL } from '@/lib/api-config';

class ApiClient {
  private async fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
    }

    return response.json();
  }

  async getJobSpends(filter: JobSpendFilter): Promise<PaginatedJobSpends> {
    const params = new URLSearchParams({
      start_date: filter.start_date,
      end_date: filter.end_date,
      page: filter.page.toString(),
      per_page: filter.per_page.toString(),
    });

    if (filter.job_name) {
      params.append('job_name', filter.job_name);
    }

    return this.fetchApi<PaginatedJobSpends>(`/job-spends?${params}`);
  }

  async getSummaryMetrics(dateRange: DateRange): Promise<SummaryMetrics> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
    });

    return this.fetchApi<SummaryMetrics>(`/summary?${params}`);
  }

  async getJobCostBreakdown(jobId: string, runId: string): Promise<CostBreakdown> {
    const params = new URLSearchParams({ run_id: runId });
    return this.fetchApi<CostBreakdown>(`/job/${jobId}/breakdown?${params}`);
  }

  async getJobCostAnalysis(jobId: string, runId: string): Promise<CostAnalysis> {
    const params = new URLSearchParams({ run_id: runId });
    return this.fetchApi<CostAnalysis>(`/job/${jobId}/analyze?${params}`);
  }

  async getClusterDetails(clusterId: string): Promise<ClusterDetails> {
    return this.fetchApi<ClusterDetails>(`/cluster/${clusterId}/details`);
  }

  async getClusterAnalysis(clusterId: string): Promise<ClusterAnalysis> {
    return this.fetchApi<ClusterAnalysis>(`/cluster/${clusterId}/analyze`);
  }

  async getTopJobs(dateRange: DateRange, limit: number = 5): Promise<JobSpend[]> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
      limit: limit.toString(),
    });

    return this.fetchApi<JobSpend[]>(`/top-jobs?${params}`);
  }

  async getDatePresets(): Promise<Record<string, DatePreset>> {
    return this.fetchApi<Record<string, DatePreset>>('/date-presets');
  }

  async getCloudPlatformConfig(): Promise<CloudPlatformConfig> {
    return this.fetchApi<CloudPlatformConfig>('/cloud-platform');
  }

  async getOtherCostBreakdown(
    dateRange: DateRange,
    clusterId?: string,
  ): Promise<OtherCostBreakdownResponse> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
    });
    if (clusterId) {
      params.append('cluster_id', clusterId);
    }
    return this.fetchApi<OtherCostBreakdownResponse>(`/other-cost-breakdown?${params}`);
  }

  async getCoverageTrend(limit: number = 30): Promise<CoverageTrendResponse> {
    const params = new URLSearchParams({ limit: limit.toString() });
    return this.fetchApi<CoverageTrendResponse>(`/classification-coverage-trend?${params}`);
  }

  async healthCheck(): Promise<{ status: string; service: string }> {
    return this.fetchApi<{ status: string; service: string }>('/health');
  }
}

export const apiClient = new ApiClient();
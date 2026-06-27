import { SummaryMetrics, CostBreakdown, PaginatedJobSpends, DateRange, JobSpendFilter, DatePreset, CostAnalysis, ClusterDetails, ClusterAnalysis, CloudPlatformConfig, OtherCostBreakdownResponse, CoverageTrendResponse, GroupedJob } from '@/types/job-spend';
import {
  AllPurposeFilter,
  AllPurposeSummaryMetrics,
  GroupedAllPurposeCluster,
  GroupedAllPurposeUser,
  PaginatedAllPurposeClusters,
  PaginatedAllPurposeUsers,
} from '@/types/all-purpose';
import {
  GroupedInstancePool,
  InstancePoolAnalysis,
  InstancePoolDetails,
  InstancePoolFilter,
  InstancePoolSummaryMetrics,
  PaginatedInstancePools,
} from '@/types/instance-pool';
import {
  GroupedPipeline,
  PaginatedPipelines,
  PipelineAnalysis,
  PipelineDetails,
  PipelineFilter,
  PipelineSummaryMetrics,
} from '@/types/pipeline';
import { API_BASE_URL } from '@/lib/api-config';

// Error thrown by `fetchApi` for any non-2xx response. Subclasses `Error`
// (so existing `error.message` rendering keeps working) but also carries the
// HTTP `status`, letting callers branch on specific codes — e.g. the pipeline
// modal renders a disambiguation hint on a 409 instead of a raw message
// (plan §7.1).
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

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
      throw new ApiError(
        response.status,
        errorData.detail || `HTTP ${response.status}: ${response.statusText}`,
      );
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

  async getClusterAnalysis(
    clusterId: string,
    clusterKind?: 'job' | 'all_purpose',
  ): Promise<ClusterAnalysis> {
    // Pass `clusterKind` explicitly from a tab that knows the source
    // (Job-tab / All-Purpose tab). Leave it undefined from the Instance
    // Pools drill-down — the pool rollup row doesn't carry
    // `cluster_source`, so the backend probes
    // `system.compute.clusters.cluster_source` to pick the right rollup
    // (see plan CP10 review #2).
    const params = new URLSearchParams();
    if (clusterKind) params.set('cluster_kind', clusterKind);
    const qs = params.toString();
    return this.fetchApi<ClusterAnalysis>(
      `/cluster/${clusterId}/analyze${qs ? `?${qs}` : ''}`,
    );
  }

  async getTopJobs(dateRange: DateRange, limit: number = 5): Promise<GroupedJob[]> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
      limit: limit.toString(),
    });

    return this.fetchApi<GroupedJob[]>(`/top-jobs?${params}`);
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

  async getCoverageTrend(
    dateRange?: DateRange,
    limit: number = 100,
  ): Promise<CoverageTrendResponse> {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (dateRange?.start_date) {
      params.append('start_date', dateRange.start_date);
    }
    if (dateRange?.end_date) {
      params.append('end_date', dateRange.end_date);
    }
    return this.fetchApi<CoverageTrendResponse>(`/classification-coverage-trend?${params}`);
  }

  async healthCheck(): Promise<{ status: string; service: string }> {
    return this.fetchApi<{ status: string; service: string }>('/health');
  }

  // ---------------------------------------------------------------------
  // All-Purpose Clusters tab
  //
  // Mirrors the job-cluster methods above; all under `/api/all-purpose/*`.
  // See `server/routers/all_purpose.py` and plan §6
  // (`docs/plan_all_purpose_clusters_tab.md`) for endpoint contracts.
  // ---------------------------------------------------------------------

  async getAllPurposeSummaryMetrics(
    dateRange: DateRange,
  ): Promise<AllPurposeSummaryMetrics> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
    });
    return this.fetchApi<AllPurposeSummaryMetrics>(
      `/all-purpose/summary?${params}`,
    );
  }

  async getAllPurposeGroupedByCluster(
    filter: AllPurposeFilter,
  ): Promise<PaginatedAllPurposeClusters> {
    const params = new URLSearchParams({
      start_date: filter.start_date,
      end_date: filter.end_date,
      page: filter.page.toString(),
      per_page: filter.per_page.toString(),
    });

    if (filter.search) {
      params.append('search', filter.search);
    }

    return this.fetchApi<PaginatedAllPurposeClusters>(
      `/all-purpose/grouped-by-cluster?${params}`,
    );
  }

  async getAllPurposeGroupedByUser(
    filter: AllPurposeFilter,
  ): Promise<PaginatedAllPurposeUsers> {
    const params = new URLSearchParams({
      start_date: filter.start_date,
      end_date: filter.end_date,
      page: filter.page.toString(),
      per_page: filter.per_page.toString(),
    });

    if (filter.search) {
      params.append('search', filter.search);
    }

    return this.fetchApi<PaginatedAllPurposeUsers>(
      `/all-purpose/grouped-by-user?${params}`,
    );
  }

  async getAllPurposeTopClusters(
    dateRange: DateRange,
    limit: number = 5,
  ): Promise<GroupedAllPurposeCluster[]> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
      limit: limit.toString(),
    });
    return this.fetchApi<GroupedAllPurposeCluster[]>(
      `/all-purpose/top-clusters?${params}`,
    );
  }

  async getAllPurposeTopUsers(
    dateRange: DateRange,
    limit: number = 5,
  ): Promise<GroupedAllPurposeUser[]> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
      limit: limit.toString(),
    });
    return this.fetchApi<GroupedAllPurposeUser[]>(
      `/all-purpose/top-users?${params}`,
    );
  }

  // ---------------------------------------------------------------------
  // Instance Pools tab
  //
  // Mirrors the all-purpose surface above; all under `/api/instance-pools/*`.
  // See `server/routers/instance_pools.py` and plan §6 / CP9
  // (`docs/plan_instance_pools_tab.md`) for endpoint contracts.
  //
  // The list endpoint deliberately does NOT enrich each row with the
  // REST-resolved creator GUID (plan §3.4 / §4.1 — the
  // `system.compute.instance_pools.tags` source column excludes default
  // tags, so the creator tag is REST-only; fanning out one REST call per
  // row would defeat the table's caching story). Creator info is
  // populated only on `/details` and `/analyze`.
  // ---------------------------------------------------------------------

  async getInstancePoolSummary(
    dateRange: DateRange,
  ): Promise<InstancePoolSummaryMetrics> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
    });
    return this.fetchApi<InstancePoolSummaryMetrics>(
      `/instance-pools/summary?${params}`,
    );
  }

  async getInstancePools(
    filter: InstancePoolFilter,
  ): Promise<PaginatedInstancePools> {
    const params = new URLSearchParams({
      start_date: filter.start_date,
      end_date: filter.end_date,
      page: filter.page.toString(),
      per_page: filter.per_page.toString(),
    });

    if (filter.search) {
      params.append('search', filter.search);
    }

    return this.fetchApi<PaginatedInstancePools>(
      `/instance-pools/grouped?${params}`,
    );
  }

  async getTopInstancePools(
    dateRange: DateRange,
    limit: number = 5,
  ): Promise<GroupedInstancePool[]> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
      limit: limit.toString(),
    });
    return this.fetchApi<GroupedInstancePool[]>(
      `/instance-pools/top-pools?${params}`,
    );
  }

  async getInstancePoolDetails(
    poolId: string,
  ): Promise<InstancePoolDetails> {
    return this.fetchApi<InstancePoolDetails>(
      `/instance-pools/${encodeURIComponent(poolId)}/details`,
    );
  }

  async getInstancePoolAnalysis(
    poolId: string,
  ): Promise<InstancePoolAnalysis> {
    return this.fetchApi<InstancePoolAnalysis>(
      `/instance-pools/${encodeURIComponent(poolId)}/analyze`,
    );
  }

  // ---------------------------------------------------------------------
  // Pipeline Compute tab
  //
  // Mirrors the instance-pools surface above; all under `/api/pipelines/*`.
  // See `server/routers/pipelines.py` and plan §6 / CP9
  // (`docs/plan_dlt_tab.md`) for endpoint contracts.
  //
  // `workload_type` is an optional MULTI-VALUE chip filter on the summary
  // and grouped endpoints — it only labels / narrows the view, never drops
  // spend (plan §3.1). Each selected value is appended as its own
  // `workload_type=` param so FastAPI parses it as `List[str]`.
  //
  // `pipeline_id` is only unique within a workspace (plan §3.3/§6), so the
  // two id-keyed endpoints accept an optional `workspaceId`; when omitted
  // and the id is ambiguous across workspaces the backend returns HTTP 409
  // (surfaced as a thrown Error by `fetchApi`) rather than silently picking
  // a workspace.
  // ---------------------------------------------------------------------

  async getPipelineSummary(
    dateRange: DateRange,
    workloadType?: string[],
  ): Promise<PipelineSummaryMetrics> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
    });
    workloadType?.forEach((wt) => params.append('workload_type', wt));
    return this.fetchApi<PipelineSummaryMetrics>(`/pipelines/summary?${params}`);
  }

  async getPipelines(filter: PipelineFilter): Promise<PaginatedPipelines> {
    const params = new URLSearchParams({
      start_date: filter.start_date,
      end_date: filter.end_date,
      page: filter.page.toString(),
      per_page: filter.per_page.toString(),
    });

    if (filter.search) {
      params.append('search', filter.search);
    }
    filter.workload_type?.forEach((wt) => params.append('workload_type', wt));

    return this.fetchApi<PaginatedPipelines>(`/pipelines/grouped?${params}`);
  }

  async getTopPipelines(
    dateRange: DateRange,
    limit: number = 5,
    workloadType?: string[],
  ): Promise<GroupedPipeline[]> {
    const params = new URLSearchParams({
      start_date: dateRange.start_date,
      end_date: dateRange.end_date,
      limit: limit.toString(),
    });
    workloadType?.forEach((wt) => params.append('workload_type', wt));
    return this.fetchApi<GroupedPipeline[]>(`/pipelines/top-pipelines?${params}`);
  }

  async getPipelineDetails(
    pipelineId: string,
    workspaceId?: string,
  ): Promise<PipelineDetails> {
    const params = new URLSearchParams();
    if (workspaceId) params.set('workspace_id', workspaceId);
    const qs = params.toString();
    return this.fetchApi<PipelineDetails>(
      `/pipelines/${encodeURIComponent(pipelineId)}/details${qs ? `?${qs}` : ''}`,
    );
  }

  async getPipelineAnalysis(
    pipelineId: string,
    workspaceId?: string,
  ): Promise<PipelineAnalysis> {
    const params = new URLSearchParams();
    if (workspaceId) params.set('workspace_id', workspaceId);
    const qs = params.toString();
    return this.fetchApi<PipelineAnalysis>(
      `/pipelines/${encodeURIComponent(pipelineId)}/analyze${qs ? `?${qs}` : ''}`,
    );
  }
}

export const apiClient = new ApiClient();
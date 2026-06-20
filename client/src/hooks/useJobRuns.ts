import { useQuery } from '@tanstack/react-query';
import type { JobRun } from '@/types/job-spend';
import { API_BASE_URL } from '@/lib/api-config';

const STALE_TIME_MS = 5 * 60 * 1000;

interface JobRunsParams {
  start_date: string;
  end_date: string;
  limit?: number;
}

const fetchJobRuns = async (
  jobId: string,
  params: JobRunsParams,
): Promise<JobRun[]> => {
  const searchParams = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });
  if (params.limit != null) {
    searchParams.append('limit', params.limit.toString());
  }

  const response = await fetch(
    `${API_BASE_URL}/job/${encodeURIComponent(jobId)}/runs?${searchParams}`,
    { headers: { 'Content-Type': 'application/json' } },
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch job runs: ${response.statusText}`);
  }

  return response.json();
};

/**
 * Lazily fetch the runs for a single job. Pass `enabled: false` so the request
 * only fires when the job's row is actually expanded. Results are cached per
 * (job_id, date range), so re-expanding a row is instant.
 */
export const useJobRuns = (
  jobId: string,
  params: JobRunsParams,
  enabled: boolean,
) => {
  return useQuery({
    queryKey: ['job-runs', jobId, params],
    queryFn: () => fetchJobRuns(jobId, params),
    enabled,
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
  });
};

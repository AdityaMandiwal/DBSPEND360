import { useQuery } from '@tanstack/react-query';
import type { JobProductBreakdownResponse } from '@/types/job-spend';
import { API_BASE_URL } from '@/lib/api-config';

const STALE_TIME_MS = 5 * 60 * 1000;

interface JobProductBreakdownParams {
  start_date: string;
  end_date: string;
}

const fetchJobProductBreakdown = async (
  jobId: string,
  params: JobProductBreakdownParams,
): Promise<JobProductBreakdownResponse> => {
  const searchParams = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });

  const response = await fetch(
    `${API_BASE_URL}/job/${encodeURIComponent(jobId)}/product-breakdown?${searchParams}`,
    { headers: { 'Content-Type': 'application/json' } },
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch job product breakdown: ${response.statusText}`);
  }

  return response.json();
};

/**
 * Lazily fetch the DBU product breakdown for a single job. Pass `enabled: false`
 * until the user opens the popover. Results are cached per (job_id, date range).
 */
export const useJobProductBreakdown = (
  jobId: string,
  params: JobProductBreakdownParams,
  enabled: boolean,
) => {
  return useQuery({
    queryKey: ['job-product-breakdown', jobId, params],
    queryFn: () => fetchJobProductBreakdown(jobId, params),
    enabled,
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
  });
};

import { useEffect } from 'react';
import {
  useQuery,
  useQueryClient,
  keepPreviousData,
  type QueryKey,
} from '@tanstack/react-query';
import type { PaginatedGroupedJobs, JobSpendFilter } from '@/types/job-spend';
import { API_BASE_URL } from '@/lib/api-config';
import { canQueryRange } from '@/lib/utils';

const STALE_TIME_MS = 5 * 60 * 1000;

const fetchGroupedJobSpends = async (
  params: JobSpendFilter,
): Promise<PaginatedGroupedJobs> => {
  const searchParams = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
    page: params.page.toString(),
    per_page: params.per_page.toString(),
  });

  if (params.job_name) {
    searchParams.append('job_name', params.job_name);
  }

  if (params.sort_by) {
    searchParams.append('sort_by', params.sort_by);
  }

  if (params.sort_dir) {
    searchParams.append('sort_dir', params.sort_dir);
  }

  const response = await fetch(
    `${API_BASE_URL}/grouped-job-spends?${searchParams}`,
    {
      headers: {
        'Content-Type': 'application/json',
      },
    },
  );

  if (!response.ok) {
    throw new Error(
      `Failed to fetch grouped job spends: ${response.statusText}`,
    );
  }

  return response.json();
};

const queryKeyFor = (params: JobSpendFilter): QueryKey => [
  'grouped-job-spends',
  params,
];

export const useGroupedJobSpends = (params: JobSpendFilter) => {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: queryKeyFor(params),
    queryFn: () => fetchGroupedJobSpends(params),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
    // Don't fire on an inverted range (start > end) — the API would 400.
    enabled: canQueryRange(params.start_date, params.end_date),
  });

  // Prefetch adjacent pages so Next/Previous clicks feel instant.
  // Only prefetch when the current page's data is available and we know
  // how many total pages exist.
  const totalPages = query.data?.total_pages ?? 0;
  const currentPage = params.page;

  useEffect(() => {
    if (!query.data || totalPages <= 1) return;

    const adjacent: number[] = [];
    if (currentPage + 1 <= totalPages) adjacent.push(currentPage + 1);
    if (currentPage - 1 >= 1) adjacent.push(currentPage - 1);

    adjacent.forEach((page) => {
      const adjacentParams: JobSpendFilter = { ...params, page };
      queryClient.prefetchQuery({
        queryKey: queryKeyFor(adjacentParams),
        queryFn: () => fetchGroupedJobSpends(adjacentParams),
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
    params.job_name,
    params.sort_by,
    params.sort_dir,
  ]);

  return query;
};

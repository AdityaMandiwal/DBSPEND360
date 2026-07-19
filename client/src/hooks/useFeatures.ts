import { useQuery } from '@tanstack/react-query';
import type { FeatureFlagsResponse } from '@/types/job-spend';
import { API_BASE_URL } from '@/lib/api-config';

const STALE_TIME_MS = 60 * 60 * 1000;

const fetchFeatures = async (): Promise<FeatureFlagsResponse> => {
  const response = await fetch(`${API_BASE_URL}/features`, {
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch feature flags: ${response.statusText}`);
  }

  return response.json();
};

export const useFeatures = () => {
  return useQuery({
    queryKey: ['features'],
    queryFn: fetchFeatures,
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: false,
  });
};

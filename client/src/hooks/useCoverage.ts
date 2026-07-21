import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import type {
  CoverageSummary,
  CoverageTabKey,
  ExcludedWorkspace,
} from '@/types/coverage';

export type {
  CoverageSummary,
  CoverageTabKey,
  ExcludedDbuByTab,
  ExcludedWorkspace,
} from '@/types/coverage';

const COVERAGE_QUERY_KEY = ['coverage-summary'] as const;

async function fetchCoverageSummary(): Promise<CoverageSummary> {
  return apiClient.getCoverageSummary();
}

/** Single param-less fetch, cached for all tab banners. */
export function useCoverageSummary() {
  return useQuery({
    queryKey: COVERAGE_QUERY_KEY,
    queryFn: fetchCoverageSummary,
    staleTime: 5 * 60 * 1000,
  });
}

export function formatExampleWorkspaceNames(
  workspaces: ExcludedWorkspace[],
  maxNames = 3,
): string {
  const names = workspaces
    .map((w) => w.workspace_name || `workspace ${w.workspace_id}`)
    .slice(0, maxNames);
  if (names.length === 0) {
    return 'none listed';
  }
  return names.join(', ');
}

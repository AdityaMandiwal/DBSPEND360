import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { ExcludedWorkspace } from "@/types/coverage";
import type { DateRange } from "@/types/job-spend";

export type {
  CoverageSummary,
  CoverageTabKey,
  ExcludedDbuByTab,
  ExcludedWorkspace,
} from "@/types/coverage";

/** Cached by optional date range so a tab's banner reconciles to its KPIs. */
export function useCoverageSummary(dateRange?: DateRange) {
  return useQuery({
    queryKey: ["coverage-summary", dateRange],
    queryFn: () => apiClient.getCoverageSummary(dateRange),
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
    return "none listed";
  }
  return names.join(", ");
}

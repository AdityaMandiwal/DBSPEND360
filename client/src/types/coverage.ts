export type ExcludedWorkspace = {
  workspace_id: string;
  workspace_name?: string | null;
  dbu_dollars: number;
};

export type ExcludedDbuByTab = {
  job: number;
  all_purpose: number;
  pipeline: number;
  pool: number;
};

export type CoverageSummary = {
  covered_subscription_ids: string[];
  covered_workspace_count: number;
  excluded_workspaces: ExcludedWorkspace[];
  excluded_dbu_by_tab: ExcludedDbuByTab;
  currency: string;
};

export type CoverageTabKey = keyof ExcludedDbuByTab;

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
  sql_warehouse: number;
};

export type ExcludedWorkspaceCountByTab = {
  [K in keyof ExcludedDbuByTab]: number;
};

export type CoverageSummary = {
  covered_subscription_ids: string[];
  covered_workspace_count: number;
  excluded_workspaces: ExcludedWorkspace[];
  excluded_dbu_by_tab: ExcludedDbuByTab;
  excluded_workspace_count_by_tab: ExcludedWorkspaceCountByTab;
  currency: string;
};

export type CoverageTabKey = keyof ExcludedDbuByTab;

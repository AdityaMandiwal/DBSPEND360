/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ExcludedDbuByTab } from './ExcludedDbuByTab';
import type { ExcludedWorkspace } from './ExcludedWorkspace';
import type { ExcludedWorkspaceCountByTab } from './ExcludedWorkspaceCountByTab';
/**
 * Aggregate subscription-coverage map for banners and KPI segmentation.
 */
export type CoverageSummaryResponse = {
    covered_subscription_ids: Array<string>;
    covered_workspace_count: number;
    excluded_workspaces: Array<ExcludedWorkspace>;
    excluded_dbu_by_tab: ExcludedDbuByTab;
    excluded_workspace_count_by_tab: ExcludedWorkspaceCountByTab;
    currency?: string;
};


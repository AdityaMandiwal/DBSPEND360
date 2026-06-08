/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedAllPurposeCluster } from './GroupedAllPurposeCluster';
/**
 * Paginated response for the By-Cluster sub-tab.
 */
export type PaginatedAllPurposeClusters = {
    data: Array<GroupedAllPurposeCluster>;
    total_count: number;
    page: number;
    per_page: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
};


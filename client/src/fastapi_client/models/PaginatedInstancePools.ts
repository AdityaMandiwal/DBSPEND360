/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedInstancePool } from './GroupedInstancePool';
/**
 * Paginated response for the By-Pool list view.
 */
export type PaginatedInstancePools = {
    data: Array<GroupedInstancePool>;
    total_count: number;
    page: number;
    per_page: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
};


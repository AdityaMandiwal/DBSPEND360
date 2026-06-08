/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedAllPurposeUser } from './GroupedAllPurposeUser';
/**
 * Paginated response for the By-User sub-tab.
 */
export type PaginatedAllPurposeUsers = {
    data: Array<GroupedAllPurposeUser>;
    total_count: number;
    page: number;
    per_page: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
};


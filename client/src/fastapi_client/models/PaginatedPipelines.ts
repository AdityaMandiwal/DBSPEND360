/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedPipeline } from './GroupedPipeline';
/**
 * Paginated response for the By-Pipeline list view.
 */
export type PaginatedPipelines = {
    data: Array<GroupedPipeline>;
    total_count: number;
    page: number;
    per_page: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
};


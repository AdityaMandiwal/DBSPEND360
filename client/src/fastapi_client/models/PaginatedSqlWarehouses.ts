/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GroupedSqlWarehouse } from './GroupedSqlWarehouse';
/**
 * Paginated response for the By-Warehouse list view.
 */
export type PaginatedSqlWarehouses = {
    data: Array<GroupedSqlWarehouse>;
    total_count: number;
    page: number;
    per_page: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
};


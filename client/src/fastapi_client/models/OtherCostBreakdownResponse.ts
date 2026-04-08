/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { OtherCostBreakdownItem } from './OtherCostBreakdownItem';
/**
 * Response for other cost breakdown drilldown.
 */
export type OtherCostBreakdownResponse = {
    items: Array<OtherCostBreakdownItem>;
    total_other_cost: number;
    start_date: string;
    end_date: string;
};


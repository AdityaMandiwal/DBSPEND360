/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * One calendar day of aggregate pool spend for the trend sparkline.
 *
 * `total_cost` is covered-workspace pool spend (DBU + cloud) for that day,
 * zero-filled when no pool rows landed. Used by `/api/instance-pools/daily-trend`.
 */
export type InstancePoolDailyTrendPoint = {
    usage_date: string;
    total_cost?: number;
};

